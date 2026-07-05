"""
All database query functions for the Univotel Chatbot.
Callers never write raw SQL — they call functions here.
"""
from __future__ import annotations
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from app.db.client import get_pool
from app.db.models import (
    Conversation, Hotel, University, UniversityAlias,
    CannedResponse, ResponseSchema, RecEngineLog, ChatbotLog,
    HotelChatwootLabelMap, UniversityChatwootLabelMap,
    ParentUniversity, UniversityParentMap,
    TagAssignerRun, TagAssignerLog, TagAssignerQueueItem,
    Message,
)

logger = logging.getLogger(__name__)

GLOBAL_NULL_STATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEAL_AWAITING_STATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

async def get_conversation_by_id(conversation_id: uuid.UUID) -> Optional[Conversation]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM conversations WHERE id = $1",
        conversation_id,
    )
    return Conversation(**dict(row)) if row else None


async def get_conversation_by_chatwoot_id_by_id(conversation_id: uuid.UUID) -> Optional[Conversation]:
    return await get_conversation_by_id(conversation_id)


async def get_conversation_by_chatwoot_id(chatwoot_id: int) -> Optional[Conversation]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM conversations WHERE chatwoot_conversation_id = $1",
        chatwoot_id,
    )
    return Conversation(**dict(row)) if row else None


async def upsert_conversation(chatwoot_id: int, contact_phone: Optional[str] = None) -> Conversation:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO conversations (chatwoot_conversation_id, contact_phone)
        VALUES ($1, $2)
        ON CONFLICT (chatwoot_conversation_id) DO UPDATE
            SET contact_phone = COALESCE(EXCLUDED.contact_phone, conversations.contact_phone)
        """,
        chatwoot_id, contact_phone,
    )
    row = await pool.fetchrow(
        "SELECT * FROM conversations WHERE chatwoot_conversation_id = $1",
        chatwoot_id,
    )
    return Conversation(**dict(row))


async def update_conversation_state(
    conversation_id: uuid.UUID,
    new_state: str,
    expected_state: str,
) -> bool:
    """Optimistic concurrency update. Returns False if the state race was lost."""
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE conversations
        SET flow_state = $1, last_updated_at = now()
        WHERE id = $2 AND flow_state = $3
        """,
        new_state, conversation_id, expected_state,
    )
    rows_affected = int(result.split()[-1])
    return rows_affected > 0


async def set_conversation_university(
    conversation_id: uuid.UUID, university_id: uuid.UUID
) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET university_id = $1, last_updated_at = now() WHERE id = $2",
        university_id, conversation_id,
    )


async def set_conversation_gender(
    conversation_id: uuid.UUID, gender: str
) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET gender = $1, last_updated_at = now() WHERE id = $2",
        gender, conversation_id,
    )


async def set_conversation_human_needed(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET flow_state = 'human_needed', last_updated_at = now() WHERE id = $1",
        conversation_id,
    )


async def set_conversation_stopped(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET flow_state = 'stopped', last_updated_at = now() WHERE id = $1",
        conversation_id,
    )


async def is_first_inbound_message(
    conversation_id: uuid.UUID,
    chatwoot_message_id: int,
) -> bool:
    """
    True when this inbound message has the lowest chatwoot_message_id for the conversation.
    Used for phrase-gate pre-condition A.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT (
            SELECT MIN(m.chatwoot_message_id)
            FROM messages m
            WHERE m.conversation_id = $1
              AND m.message_type = 'inbound'
        ) = $2 AS is_first
        """,
        conversation_id,
        chatwoot_message_id,
    )
    return bool(row and row["is_first"])


async def reset_clarification_attempt(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE conversations
        SET clarification_attempt = 0, last_updated_at = now()
        WHERE id = $1
        """,
        conversation_id,
    )


async def increment_clarification_attempt(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE conversations
        SET clarification_attempt = clarification_attempt + 1, last_updated_at = now()
        WHERE id = $1
        """,
        conversation_id,
    )


async def increment_reprompt_count(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE conversations
        SET reprompt_count = reprompt_count + 1,
            last_reprompt_sent_at = now(),
            last_updated_at = now()
        WHERE id = $1
        """,
        conversation_id,
    )


async def get_conversations_awaiting_reprompt() -> list[Conversation]:
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()

    base_sql = """
        SELECT * FROM conversations
        WHERE flow_state IN (
            'awaiting_university',
            'awaiting_university_clarification',
            'awaiting_campus_clarification',
            'awaiting_gender'
        )
        AND reprompt_count < 3
        AND (
            (reprompt_count = 0 AND last_updated_at < now() - interval '3 hours')
            OR (reprompt_count = 1 AND last_reprompt_sent_at < now() - interval '3 hours')
            OR (reprompt_count = 2 AND last_reprompt_sent_at < now() - interval '3 hours')
        )
    """

    if settings.testing_limitations_mode:
        allowlist = list(TESTING_PHONE_ALLOWLIST)
        rows = await pool.fetch(
            base_sql + " AND contact_phone = ANY($1::text[])",
            allowlist,
        )
    else:
        rows = await pool.fetch(base_sql)

    return [Conversation(**dict(r)) for r in rows]


async def sync_conversation_labels_and_attributes(
    conversation_id: uuid.UUID,
    labels: Optional[list[str]],
    ilgili_otel: Optional[str],
    ilgili_otel_set_at: Optional[datetime],
    ilgili_otel_set_by: Optional[str],
    tasinma_tarihi=None,
    kayip_nedeni: Optional[str] = None,
    oda_tiipi: Optional[str] = None,
    butce: Optional[str] = None,
) -> None:
    """
    Downstream-replica sync from a Chatwoot conversation_updated webhook.
    Updates atomically so _set_at/_set_by are never stale relative to the value.
    """
    pool = get_pool()
    await pool.execute(
        """
        UPDATE conversations SET
            last_updated_at      = now(),
            labels               = COALESCE($2, labels),
            ilgili_otel          = $3,
            ilgili_otel_set_at   = $4,
            ilgili_otel_set_by   = $5,
            tasinma_tarihi       = $6,
            kayip_nedeni         = $7,
            oda_tiipi            = $8,
            butce                = $9
        WHERE id = $1
        """,
        conversation_id,
        labels,
        ilgili_otel, ilgili_otel_set_at, ilgili_otel_set_by,
        tasinma_tarihi, kayip_nedeni, oda_tiipi, butce,
    )


async def reset_tagassigner_run_counts(conversation_id: uuid.UUID) -> None:
    """Called after a successful TagAssigner run completes."""
    pool = get_pool()
    await pool.execute(
        """
        UPDATE conversations
        SET messages_since_last_run = 0,
            last_updated_at = now()
        WHERE id = $1
        """,
        conversation_id,
    )


async def increment_auto_run_count(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET auto_run_count = auto_run_count + 1, last_updated_at = now() WHERE id = $1",
        conversation_id,
    )


async def increment_manual_run_count(conversation_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET manual_run_count = manual_run_count + 1, last_updated_at = now() WHERE id = $1",
        conversation_id,
    )


async def reset_daily_run_counts() -> None:
    """Called at Istanbul midnight by the in-process daily reset sweep."""
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET auto_run_count = 0, manual_run_count = 0 WHERE auto_run_count > 0 OR manual_run_count > 0"
    )


async def get_conversations_eligible_for_tagging() -> list[Conversation]:
    """
    Conversations that meet the message-trigger gate:
    - >= 5 messages since last run, at least one inbound
    - last_message_at < now() - 15 minutes
    - auto_run_count < 5
    - no pending/processing queue item already
    """
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()

    base_sql = """
        SELECT c.* FROM conversations c
        WHERE c.messages_since_last_run >= 5
          AND c.last_message_at IS NOT NULL
          AND c.last_message_at < now() - interval '15 minutes'
          AND c.auto_run_count < 5
          AND NOT EXISTS (
              SELECT 1 FROM tag_assigner_queue q
              WHERE q.conversation_id = c.id
                AND q.status IN ('pending', 'processing', 'submitted', 'awaiting_results')
          )
          AND EXISTS (
              SELECT 1 FROM messages m
              WHERE m.conversation_id = c.id
                AND m.message_type = 'inbound'
                AND m.is_private = false
                AND m.created_at > COALESCE(
                    (SELECT r.completed_at FROM tag_assigner_runs r
                     WHERE r.conversation_id = c.id AND r.status = 'success'
                     ORDER BY r.completed_at DESC LIMIT 1),
                    '1970-01-01'::timestamptz
                )
          )
    """

    if settings.testing_limitations_mode:
        allowlist = list(TESTING_PHONE_ALLOWLIST)
        rows = await pool.fetch(
            base_sql + " AND c.contact_phone = ANY($1::text[])",
            allowlist,
        )
    else:
        rows = await pool.fetch(base_sql)

    return [Conversation(**dict(r)) for r in rows]


async def get_conversations_eligible_for_nightly_batch() -> list[Conversation]:
    """
    Nightly sweep eligibility:
    - Never tagged + >= 5 messages: sweep
    - Previously tagged + >= 1 new message since last run: sweep
    - auto_run_count < 5
    """
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()

    base_sql = """
        SELECT c.* FROM conversations c
        WHERE c.auto_run_count < 5
          AND NOT EXISTS (
              SELECT 1 FROM tag_assigner_queue q
              WHERE q.conversation_id = c.id
                AND q.status IN ('pending', 'processing', 'submitted', 'awaiting_results')
          )
          AND (
              -- Never tagged + >= 5 messages
              (
                  NOT EXISTS (SELECT 1 FROM tag_assigner_runs r WHERE r.conversation_id = c.id AND r.status = 'success')
                  AND c.messages_since_last_run >= 5
              )
              OR
              -- Previously tagged + >= 1 new message since last run
              (
                  EXISTS (SELECT 1 FROM tag_assigner_runs r WHERE r.conversation_id = c.id AND r.status = 'success')
                  AND c.messages_since_last_run >= 1
              )
          )
    """

    if settings.testing_limitations_mode:
        allowlist = list(TESTING_PHONE_ALLOWLIST)
        rows = await pool.fetch(
            base_sql + " AND c.contact_phone = ANY($1::text[])",
            allowlist,
        )
    else:
        rows = await pool.fetch(base_sql)

    return [Conversation(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def message_exists(chatwoot_message_id: int) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM messages WHERE chatwoot_message_id = $1",
        chatwoot_message_id,
    )
    return row is not None


async def insert_message(
    conversation_id: uuid.UUID,
    chatwoot_message_id: int,
    content: Optional[str],
    message_type: str,
    sender_type: str,
    sender_id: Optional[str],
    sender_name: Optional[str],
    is_private: bool = False,
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO messages
            (conversation_id, chatwoot_message_id, content, message_type,
             sender_type, sender_id, sender_name, is_private)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (chatwoot_message_id) DO NOTHING
        """,
        conversation_id, chatwoot_message_id, content,
        message_type, sender_type, sender_id, sender_name, is_private,
    )
    # Only real messages advance the activity clock and the 5-message counter.
    if not is_private:
        await pool.execute(
            """
            UPDATE conversations
            SET last_message_at          = now(),
                messages_since_last_run  = messages_since_last_run + 1,
                last_updated_at          = now()
            WHERE id = $1
            """,
            conversation_id,
        )


async def get_messages_for_conversation(
    conversation_id: uuid.UUID,
    since: Optional[datetime] = None,
) -> list[Message]:
    pool = get_pool()
    if since:
        rows = await pool.fetch(
            """
            SELECT * FROM messages
            WHERE conversation_id = $1 AND created_at > $2 AND is_private = false
            ORDER BY created_at
            """,
            conversation_id, since,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT * FROM messages
            WHERE conversation_id = $1 AND is_private = false
            ORDER BY created_at
            """,
            conversation_id,
        )
    return [Message(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------

async def get_all_hotels() -> list[Hotel]:
    pool = get_pool()
    rows = await pool.fetch("SELECT id, name, gender_scope, priority_score, is_visible FROM hotels")
    return [Hotel(**dict(r)) for r in rows]


async def get_hotel_by_id(hotel_id: uuid.UUID) -> Optional[Hotel]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, gender_scope, priority_score, is_visible FROM hotels WHERE id = $1",
        hotel_id,
    )
    return Hotel(**dict(row)) if row else None


async def find_hotels_by_gender_and_university(
    gender: str, university_id: uuid.UUID
) -> list[Hotel]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT h.id, h.name, h.gender_scope, h.priority_score, h.is_visible
        FROM hotels h
        JOIN hotel_accessible_universities hau ON hau.hotel_id = h.id
        WHERE hau.university_id = $1
          AND (h.gender_scope = $2 OR h.gender_scope = 'mixed')
          AND h.is_visible = true
          AND h.gender_scope IS NOT NULL
          AND h.id != $3
        ORDER BY h.priority_score DESC
        """,
        university_id, gender, GLOBAL_NULL_STATE_ID,
    )
    return [Hotel(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# hotel_chatwoot_label_map
# ---------------------------------------------------------------------------

async def get_hotel_chatwoot_label_map() -> list[HotelChatwootLabelMap]:
    pool = get_pool()
    rows = await pool.fetch("SELECT hotel_id, chatwoot_list_value FROM hotel_chatwoot_label_map")
    return [HotelChatwootLabelMap(**dict(r)) for r in rows]


async def get_chatwoot_list_value_for_hotel(hotel_id: uuid.UUID) -> Optional[str]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT chatwoot_list_value FROM hotel_chatwoot_label_map WHERE hotel_id = $1",
        hotel_id,
    )
    return row["chatwoot_list_value"] if row else None


# ---------------------------------------------------------------------------
# university_chatwoot_label_map
# ---------------------------------------------------------------------------

async def get_chatwoot_list_value_for_university(university_id: uuid.UUID) -> Optional[str]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT chatwoot_list_value FROM university_chatwoot_label_map WHERE university_id = $1",
        university_id,
    )
    return row["chatwoot_list_value"] if row else None


# ---------------------------------------------------------------------------
# Universities
# ---------------------------------------------------------------------------

async def get_all_universities() -> list[University]:
    pool = get_pool()
    rows = await pool.fetch("SELECT id, name, university_short_name FROM universities")
    return [University(**dict(r)) for r in rows]


async def get_all_university_aliases() -> list[UniversityAlias]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, university_id, alias, parent_university_id FROM university_aliases"
    )
    return [UniversityAlias(**dict(r)) for r in rows]


async def get_university_by_id(university_id: uuid.UUID) -> Optional[University]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, university_short_name FROM universities WHERE id = $1",
        university_id,
    )
    return University(**dict(row)) if row else None


async def set_conversation_pending_parent(
    conversation_id: uuid.UUID, parent_university_id: Optional[uuid.UUID]
) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE conversations SET pending_parent_university_id = $1, last_updated_at = now() WHERE id = $2",
        parent_university_id, conversation_id,
    )


async def get_campuses_for_parent(parent_university_id: uuid.UUID) -> list[UniversityParentMap]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT university_id, parent_university_id, campus_label
        FROM university_parent_map
        WHERE parent_university_id = $1
        ORDER BY campus_label
        """,
        parent_university_id,
    )
    return [UniversityParentMap(**dict(r)) for r in rows]


async def get_parent_university_by_id(parent_id: uuid.UUID) -> Optional[ParentUniversity]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, question FROM parent_universities WHERE id = $1",
        parent_id,
    )
    return ParentUniversity(**dict(row)) if row else None


async def is_deal_awaiting_university(university_id: uuid.UUID) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM deal_awaiting_universities WHERE university_id = $1",
        university_id,
    )
    return row is not None


# ---------------------------------------------------------------------------
# Canned responses & response schemas
# ---------------------------------------------------------------------------

async def get_canned_responses_for_hotel(hotel_id: uuid.UUID) -> list[str]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT cr.content
        FROM response_schemas rs
        JOIN canned_responses cr ON cr.id = rs.response_id
        WHERE rs.hotel_id = $1
        ORDER BY rs.sending_order
        """,
        hotel_id,
    )
    return [r["content"] for r in rows]


async def get_canned_response_by_short_code(short_code: str) -> Optional[CannedResponse]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, short_code, content FROM canned_responses WHERE short_code = $1",
        short_code,
    )
    return CannedResponse(**dict(row)) if row else None


# ---------------------------------------------------------------------------
# RecEngine logs
# ---------------------------------------------------------------------------

async def insert_rec_engine_processing(
    conversation_id: uuid.UUID, idempotency_key: uuid.UUID
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO rec_engine_logs (conversation_id, idempotency_key, status)
        VALUES ($1, $2, 'processing')
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        conversation_id, idempotency_key,
    )


async def get_rec_engine_log(idempotency_key: uuid.UUID) -> Optional[RecEngineLog]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM rec_engine_logs WHERE idempotency_key = $1",
        idempotency_key,
    )
    return RecEngineLog(**dict(row)) if row else None


async def update_rec_engine_log(
    idempotency_key: uuid.UUID,
    status: str,
    hotel_rec: Optional[uuid.UUID],
    status_code: Optional[str] = None,
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE rec_engine_logs
        SET status = $1, hotel_rec = $2, status_code = $3
        WHERE idempotency_key = $4
        """,
        status, hotel_rec, status_code, idempotency_key,
    )


# ---------------------------------------------------------------------------
# Chatbot logs
# ---------------------------------------------------------------------------

async def write_log(log: ChatbotLog) -> uuid.UUID:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO chatbot_logs
            (conversation_id, operation_layer, which_run, from_state, to_state,
             log_level, is_success, status_code, internal_class,
             network_status, database_status, explanation)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        RETURNING id
        """,
        log.conversation_id, log.operation_layer, log.which_run,
        log.from_state, log.to_state, log.log_level, log.is_success,
        log.status_code, log.internal_class, log.network_status,
        log.database_status, log.explanation,
    )
    return row["id"]


# ---------------------------------------------------------------------------
# TagAssigner runs
# ---------------------------------------------------------------------------

async def insert_tagassigner_run(
    run_id: uuid.UUID,
    conversation_id: uuid.UUID,
    trigger_type: str,
) -> None:
    """Write the 'processing' row before calling Gemini (idempotency guarantee)."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO tag_assigner_runs (run_id, conversation_id, trigger_type, status)
        VALUES ($1, $2, $3, 'processing')
        ON CONFLICT (run_id) DO NOTHING
        """,
        run_id, conversation_id, trigger_type,
    )


async def get_tagassigner_run(run_id: uuid.UUID) -> Optional[TagAssignerRun]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM tag_assigner_runs WHERE run_id = $1",
        run_id,
    )
    if not row:
        return None
    data = dict(row)
    if data.get("gemini_result") and isinstance(data["gemini_result"], str):
        data["gemini_result"] = json.loads(data["gemini_result"])
    return TagAssignerRun(**data)


async def update_tagassigner_run_success(
    run_id: uuid.UUID,
    gemini_result: dict,
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE tag_assigner_runs
        SET status = 'success', completed_at = now(), gemini_result = $2
        WHERE run_id = $1
        """,
        run_id, json.dumps(gemini_result),
    )


async def update_tagassigner_run_failed(run_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE tag_assigner_runs SET status = 'failed', completed_at = now() WHERE run_id = $1",
        run_id,
    )


async def update_tagassigner_run_batch(
    run_id: uuid.UUID,
    batch_job_name: str,
) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE tag_assigner_runs SET batch_job_name = $2 WHERE run_id = $1",
        run_id, batch_job_name,
    )


async def claim_batch_webhook(run_id: uuid.UUID, webhook_id: str) -> bool:
    """
    Atomically claim a batch.succeeded delivery for deduplication.
    Returns True if this delivery is the first (i.e. we should process it);
    False if the webhook_id was already recorded (duplicate — skip).
    """
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE tag_assigner_runs
        SET batch_webhook_id = $2
        WHERE run_id = $1 AND batch_webhook_id IS NULL AND status = 'processing'
        """,
        run_id, webhook_id,
    )
    rows_affected = int(result.split()[-1])
    return rows_affected > 0


async def get_run_by_batch_job_name(batch_job_name: str) -> Optional[TagAssignerRun]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM tag_assigner_runs WHERE batch_job_name = $1",
        batch_job_name,
    )
    if not row:
        return None
    data = dict(row)
    if data.get("gemini_result") and isinstance(data["gemini_result"], str):
        data["gemini_result"] = json.loads(data["gemini_result"])
    return TagAssignerRun(**data)


# ---------------------------------------------------------------------------
# TagAssigner logs
# ---------------------------------------------------------------------------

async def write_tagassigner_log(log: TagAssignerLog) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO tag_assigner_logs
            (run_id, conversation_id, request_type, request_from, request_to,
             is_success, status_code, fail_reason)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        log.run_id, log.conversation_id, log.request_type,
        log.request_from, log.request_to, log.is_success,
        log.status_code, log.fail_reason,
    )


# ---------------------------------------------------------------------------
# TagAssigner queue
# ---------------------------------------------------------------------------

async def enqueue_tagassigner_run(
    conversation_id: uuid.UUID,
    trigger_type: str,
) -> bool:
    """
    Enqueue a conversation for tagging. Returns False if already pending (dedupe index).
    """
    pool = get_pool()
    try:
        await pool.execute(
            """
            INSERT INTO tag_assigner_queue (conversation_id, status, trigger_type)
            VALUES ($1, 'pending', $2)
            """,
            conversation_id, trigger_type,
        )
        return True
    except Exception:
        return False


async def get_pending_queue_items(limit: int = 10) -> list[TagAssignerQueueItem]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM tag_assigner_queue
        WHERE status = 'pending'
        ORDER BY enqueued_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        limit,
    )
    return [TagAssignerQueueItem(**dict(r)) for r in rows]


async def claim_queue_item(item_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Atomically move a 'pending' item to 'processing', binding the run_id."""
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE tag_assigner_queue
        SET status = 'processing', run_id = $2
        WHERE id = $1 AND status = 'pending'
        """,
        item_id, run_id,
    )
    return int(result.split()[-1]) > 0


async def update_queue_item_status(item_id: uuid.UUID, status: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE tag_assigner_queue SET status = $2 WHERE id = $1",
        item_id, status,
    )


async def mark_queue_item_submitted(item_id: uuid.UUID) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE tag_assigner_queue SET status = 'submitted' WHERE id = $1",
        item_id,
    )


async def mark_queue_items_awaiting_results(run_ids: list[uuid.UUID]) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE tag_assigner_queue SET status = 'awaiting_results' WHERE run_id = ANY($1::uuid[])",
        run_ids,
    )


async def get_queue_item_by_run_id(run_id: uuid.UUID) -> Optional[TagAssignerQueueItem]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM tag_assigner_queue WHERE run_id = $1",
        run_id,
    )
    return TagAssignerQueueItem(**dict(row)) if row else None


async def has_processing_run(conversation_id: uuid.UUID) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT 1 FROM tag_assigner_queue
        WHERE conversation_id = $1
          AND status IN ('processing', 'submitted', 'awaiting_results')
        """,
        conversation_id,
    )
    return row is not None


# ---------------------------------------------------------------------------
# Integrity check helpers
# ---------------------------------------------------------------------------

async def get_hotels_missing_response_schemas() -> list[uuid.UUID]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT h.id FROM hotels h
        WHERE h.is_visible = true
          AND NOT EXISTS (
            SELECT 1 FROM response_schemas rs WHERE rs.hotel_id = h.id
          )
        """
    )
    return [r["id"] for r in rows]


async def get_orphaned_response_schema_entries() -> list[uuid.UUID]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT rs.id FROM response_schemas rs
        WHERE NOT EXISTS (SELECT 1 FROM canned_responses cr WHERE cr.id = rs.response_id)
           OR NOT EXISTS (SELECT 1 FROM hotels h WHERE h.id = rs.hotel_id)
        """
    )
    return [r["id"] for r in rows]


async def global_null_state_is_wired() -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM response_schemas WHERE hotel_id = $1",
        GLOBAL_NULL_STATE_ID,
    )
    return row["cnt"] > 0


async def deal_awaiting_state_is_wired() -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM response_schemas WHERE hotel_id = $1",
        DEAL_AWAITING_STATE_ID,
    )
    return row["cnt"] > 0


async def get_visible_hotels_missing_label_map() -> list[uuid.UUID]:
    """Returns ids of visible (recommendable) hotels with no hotel_chatwoot_label_map row."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT h.id FROM hotels h
        WHERE h.is_visible = true
          AND h.id NOT IN ($1, $2)
          AND NOT EXISTS (
              SELECT 1 FROM hotel_chatwoot_label_map m WHERE m.hotel_id = h.id
          )
        """,
        GLOBAL_NULL_STATE_ID, DEAL_AWAITING_STATE_ID,
    )
    return [r["id"] for r in rows]


async def get_campus_university_ids_missing_chatwoot_label_map() -> list[uuid.UUID]:
    """Campus rows in university_parent_map with no university_chatwoot_label_map entry."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT upm.university_id FROM university_parent_map upm
        WHERE NOT EXISTS (
            SELECT 1 FROM university_chatwoot_label_map m WHERE m.university_id = upm.university_id
        )
        """
    )
    return [r["university_id"] for r in rows]


async def get_universities_missing_parent_map() -> list[uuid.UUID]:
    """University ids with no row in university_parent_map."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.id FROM universities u
        WHERE NOT EXISTS (
            SELECT 1 FROM university_parent_map upm WHERE upm.university_id = u.id
        )
        """
    )
    return [r["id"] for r in rows]


async def get_parent_map_orphan_campuses() -> list[uuid.UUID]:
    """Campus rows in university_parent_map whose parent doesn't exist in parent_universities."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT upm.university_id FROM university_parent_map upm
        WHERE NOT EXISTS (
            SELECT 1 FROM parent_universities p WHERE p.id = upm.parent_university_id
        )
        """
    )
    return [r["university_id"] for r in rows]


async def get_parent_ids_with_duplicate_campus_labels() -> list[uuid.UUID]:
    """Parent university ids where two or more campus rows share the same campus_label."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT parent_university_id FROM university_parent_map
        GROUP BY parent_university_id, campus_label
        HAVING COUNT(*) > 1
        """
    )
    return [r["parent_university_id"] for r in rows]
