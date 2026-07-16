"""
Import conversation histories from the Univotel CRM DB into the chatbot DB.

Used by `tag importConvo` for TagAssigner accuracy testing: selects random CRM
conversations with full lead_messages transcripts and seeds the local chatbot DB.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from app.config import settings

_NON_DIGIT = re.compile(r"\D+")
_BOT_AGENT_ID = str(settings.chatwoot_bot_agent_id)
_MIN_TEXT_MESSAGES = 3

_SELECT_RANDOM_CONVERSATIONS_SQL = """
WITH eligible AS (
    SELECT
        l.chatwoot_conversation_id,
        l.lead_phone
    FROM lead_messages lm
    INNER JOIN leads l ON l.uuid = lm.lead_uuid
    WHERE l.chatwoot_conversation_id IS NOT NULL
      AND l.is_deleted = false
    GROUP BY l.chatwoot_conversation_id, l.lead_phone
    HAVING COUNT(*) FILTER (
        WHERE lm.is_private = false
          AND lm.content IS NOT NULL
          AND TRIM(lm.content) != ''
          AND lm.message_type != 'activity'
    ) >= $2
    ORDER BY RANDOM()
    LIMIT $1
)
SELECT
    lm.chatwoot_message_id,
    lm.chatwoot_conversation_id,
    lm.message_type,
    lm.content,
    lm.sender_type,
    lm.sender_id,
    lm.sender_name,
    lm.is_private,
    lm.created_at,
    lm.direction,
    l.lead_phone
FROM lead_messages lm
INNER JOIN leads l ON l.uuid = lm.lead_uuid
INNER JOIN eligible e ON e.chatwoot_conversation_id = l.chatwoot_conversation_id
WHERE l.is_deleted = false
ORDER BY lm.chatwoot_conversation_id, lm.created_at
"""


@dataclass(frozen=True)
class ConversationSeed:
    """One CRM conversation to import into the chatbot DB."""

    chatwoot_conversation_id: int
    lead_phone: str


@dataclass
class CrmImportResult:
    """Summary of a CRM import run."""

    conversations_imported: int = 0
    messages_inserted: int = 0
    conversation_ids: list[int] | None = None

    def __post_init__(self) -> None:
        if self.conversation_ids is None:
            self.conversation_ids = []


def normalize_phone(raw: str | None) -> str:
    """Strip non-digits; Turkish local numbers get a 90 country prefix."""
    if not raw:
        return ""
    digits = _NON_DIGIT.sub("", raw)
    if digits.startswith("0") and len(digits) == 11:
        return "90" + digits[1:]
    return digits


def parse_ts(raw: str | datetime) -> datetime:
    """Parse CRM timestamps into timezone-aware datetimes."""
    if isinstance(raw, datetime):
        dt = raw
    else:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def map_crm_message(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map a CRM lead_messages row to chatbot messages schema; None = skip."""
    if row.get("message_type") == "activity":
        return None
    if row.get("is_private"):
        return None

    direction = row.get("direction")
    if direction == "incoming":
        local_type = "inbound"
        sender_type = "contact"
    elif direction == "outgoing":
        local_type = "outbound"
        sender_id = str(row["sender_id"]) if row.get("sender_id") is not None else None
        if sender_id == _BOT_AGENT_ID:
            sender_type = "infoGatherer"
        elif row.get("sender_type") == "user":
            sender_type = "user"
        else:
            sender_type = "user"
    else:
        mt = row.get("message_type")
        if mt == "incoming":
            local_type, sender_type = "inbound", "contact"
        elif mt == "outgoing":
            local_type, sender_type = "outbound", "user"
        else:
            return None

    sender_id = str(row["sender_id"]) if row.get("sender_id") is not None else None
    if local_type == "inbound":
        sender_type = "contact"

    return {
        "chatwoot_message_id": int(row["chatwoot_message_id"]),
        "content": row.get("content"),
        "message_type": local_type,
        "sender_type": sender_type,
        "sender_id": sender_id,
        "sender_name": row.get("sender_name"),
        "is_private": False,
        "sent_at": parse_ts(row["created_at"]),
        "created_at": parse_ts(row["created_at"]),
    }


async def wipe_all_conversations(conn: asyncpg.Connection) -> None:
    """Remove all conversation-linked rows so we can seed a fresh test set."""
    await conn.execute(
        "UPDATE conversations SET last_processed_log_id = NULL "
        "WHERE last_processed_log_id IS NOT NULL"
    )
    for table in (
        "tag_assigner_queue",
        "tag_assigner_logs",
        "tag_assigner_runs",
        "rec_engine_logs",
        "messages",
        "chatbot_logs",
        "conversations",
    ):
        result = await conn.execute(f"DELETE FROM {table}")
        print(f"cleared {table}: {result}")


async def fetch_random_crm_messages(
    crm_conn: asyncpg.Connection,
    limit: int,
    *,
    min_text_messages: int = _MIN_TEXT_MESSAGES,
) -> tuple[list[ConversationSeed], list[dict[str, Any]]]:
    """
    Select random CRM conversations and return their full message rows.

    Input:
        crm_conn: open asyncpg connection to the CRM database
        limit: number of conversations to select
        min_text_messages: minimum non-empty public text messages required

    Output:
        (conversation seeds, flat list of CRM lead_messages rows as dicts)
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    rows = await crm_conn.fetch(
        _SELECT_RANDOM_CONVERSATIONS_SQL,
        limit,
        min_text_messages,
    )
    if not rows:
        return [], []

    seeds: list[ConversationSeed] = []
    seen_cw: set[int] = set()
    data: list[dict[str, Any]] = []

    for row in rows:
        record = dict(row)
        cwid = int(record["chatwoot_conversation_id"])
        if cwid not in seen_cw:
            seen_cw.add(cwid)
            seeds.append(
                ConversationSeed(
                    chatwoot_conversation_id=cwid,
                    lead_phone=str(record.get("lead_phone") or ""),
                )
            )
        data.append(record)

    return seeds, data


async def import_conversations(
    chatbot_conn: asyncpg.Connection,
    conversations: list[ConversationSeed],
    message_rows: list[dict[str, Any]],
    *,
    wipe_existing: bool = True,
) -> CrmImportResult:
    """
    Insert conversations + messages into the chatbot DB.

    Input:
        chatbot_conn: open asyncpg connection to the chatbot database
        conversations: conversation seeds (order preserved for logging)
        message_rows: CRM lead_messages rows (may include lead_phone)
        wipe_existing: when True, delete existing conversation-linked rows first
    """
    by_conv: dict[int, list[dict[str, Any]]] = {}
    for row in message_rows:
        cwid = int(row["chatwoot_conversation_id"])
        by_conv.setdefault(cwid, []).append(row)

    result = CrmImportResult()

    async with chatbot_conn.transaction():
        if wipe_existing:
            await wipe_all_conversations(chatbot_conn)

        for conv in conversations:
            cwid = conv.chatwoot_conversation_id
            phone = normalize_phone(conv.lead_phone)
            conv_id = uuid.uuid4()

            await chatbot_conn.execute(
                """
                INSERT INTO conversations (id, chatwoot_conversation_id, contact_phone)
                VALUES ($1, $2, $3)
                """,
                conv_id,
                cwid,
                phone or None,
            )

            rows = sorted(
                by_conv.get(cwid, []),
                key=lambda r: parse_ts(r["created_at"]),
            )
            mapped = [m for r in rows if (m := map_crm_message(r)) is not None]
            last_at: Optional[datetime] = None

            for msg in mapped:
                await chatbot_conn.execute(
                    """
                    INSERT INTO messages
                        (conversation_id, chatwoot_message_id, content, message_type,
                         sender_type, sender_id, sender_name, is_private, sent_at, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (chatwoot_message_id) DO NOTHING
                    """,
                    conv_id,
                    msg["chatwoot_message_id"],
                    msg["content"],
                    msg["message_type"],
                    msg["sender_type"],
                    msg["sender_id"],
                    msg["sender_name"],
                    msg["is_private"],
                    msg["sent_at"],
                    msg["created_at"],
                )
                last_at = msg["created_at"]
                result.messages_inserted += 1

            if last_at:
                await chatbot_conn.execute(
                    """
                    UPDATE conversations
                    SET last_message_at = $2, last_updated_at = $2
                    WHERE id = $1
                    """,
                    conv_id,
                    last_at,
                )

            text_count = sum(
                1 for m in mapped if m.get("content") and str(m["content"]).strip()
            )
            print(
                f"imported cw={cwid} phone={phone} messages={len(mapped)} "
                f"with_text={text_count}"
            )
            result.conversations_imported += 1
            result.conversation_ids.append(cwid)

    return result


def _require_crm_database_url() -> str:
    url = settings.crm_database_url
    if not url or not url.strip():
        raise RuntimeError(
            "CRM_DATABASE_URL is not set. Add the Univotel CRM Postgres connection "
            "string to .env before running importConvo."
        )
    return url.strip()


async def run_import_from_crm(limit: int) -> CrmImportResult:
    """
    Select random CRM conversations and import their full transcripts locally.

    Input:
        limit: number of conversations to import

    Output:
        CrmImportResult summary
    """
    crm_url = _require_crm_database_url()
    crm_conn = await asyncpg.connect(crm_url)
    chatbot_conn = await asyncpg.connect(settings.database_url)
    try:
        conversations, message_rows = await fetch_random_crm_messages(crm_conn, limit)
        if not conversations:
            print(
                f"No eligible CRM conversations found "
                f"(need >= {_MIN_TEXT_MESSAGES} public text messages each)."
            )
            return CrmImportResult()

        print(
            f"Selected {len(conversations)} random CRM conversation(s): "
            f"{', '.join(str(c.chatwoot_conversation_id) for c in conversations)}"
        )
        result = await import_conversations(chatbot_conn, conversations, message_rows)
        conv_count = await chatbot_conn.fetchval("SELECT count(*) FROM conversations")
        msg_count = await chatbot_conn.fetchval("SELECT count(*) FROM messages")
        print(
            f"\nDone: {conv_count} conversations, {msg_count} messages "
            f"({result.messages_inserted} inserted this run)"
        )
        return result
    finally:
        await crm_conn.close()
        await chatbot_conn.close()
