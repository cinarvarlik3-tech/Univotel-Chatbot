"""
TagAssigner Script Router — the single I/O broker (§1 of tagassigner-v1-spec.md).

Orchestrates the full pipeline per run:
  1. Read current labels live from Chatwoot (not the DB replica)
  2. Fetch messages (full history or since-last-run)
  3. Call Gemini → receive proposed label set
  4. Run label resolution (4-list enforce, mutex, terminal guard, merge)
  5. Write resolved labels to Chatwoot
  6. Write deterministic attributes (university / ogrenci_cinsiyet / ilgili_otel)
  7. Mark run success + reset message counter

Gemini never touches the DB or Chatwoot directly. The Router is the only caller.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings, TESTING_PHONE_ALLOWLIST
from app.db import queries
from app.db.models import Conversation, TagAssignerLog
from app.chatwoot_client import get_labels, set_labels
from app.tagassigner.label_resolver import resolve_labels, remove_tag_trigger_label
from app.tagassigner.payload_builder import build_payload
from app.tagassigner.gemini_client import call_gemini
from app.tagassigner.attribute_resolver import resolve_and_write_attributes
from app.webhooks.chatwoot import record_self_write

logger = logging.getLogger(__name__)

# Write-back retry delays (1s/2s/4s — mirrors send_retry.py)
_WRITEBACK_DELAYS = [1.0, 2.0, 4.0]


def _is_taggable_in_testing_mode(conv: Conversation) -> bool:
    """
    Backstop for TESTING_LIMITATIONS_MODE at the router (the universal chokepoint
    for the live Gemini path). When testing mode is off, everything is taggable.
    When on, only conversations whose contact_phone is on the allowlist may run.
    contact_phone is stored already-normalized (digits only) at webhook ingest.
    """
    if not settings.testing_limitations_mode:
        return True
    return conv.contact_phone in TESTING_PHONE_ALLOWLIST


async def run_tagging(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    trigger_type: str,
    read_full_history: bool,
) -> bool:
    """
    Full TagAssigner run. run_id is pre-generated; the 'processing' row is written
    before this is called (by the queue worker). Returns True on success.
    """
    # Guard: if the run row is already resolved (retry found a prior success), no-op.
    existing = await queries.get_tagassigner_run(run_id)
    if existing and existing.status in ("success", "failed"):
        logger.info(
            "TagAssigner router: run %s already resolved (%s) — no-op",
            run_id, existing.status,
        )
        return existing.status == "success"

    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        logger.error("TagAssigner router: conversation %s not found", conversation_id)
        await queries.update_tagassigner_run_failed(run_id)
        return False

    # Testing-mode backstop: even if something was enqueued, never tag a
    # conversation whose contact is off the allowlist while testing mode is on.
    if not _is_taggable_in_testing_mode(conv):
        logger.info(
            "TagAssigner router: TESTING_MODE — conversation %s not on allowlist, skipping run %s",
            conversation_id, run_id,
        )
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "db_read", "router", "supabase", True, "200")

    # Step 1: read current labels live from Chatwoot
    current_labels = await get_labels(conv.chatwoot_conversation_id)
    if current_labels is None:
        logger.error(
            "TagAssigner router: could not fetch labels for conversation %s", conversation_id
        )
        await _log(run_id, conversation_id, "api", "router", "chatwoot", False, "0",
                   "Failed to fetch current labels")
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "api", "router", "chatwoot", True, "200")

    # Remove the 'tag' trigger label before passing to Gemini (it's a trigger, not a state)
    current_labels_clean = remove_tag_trigger_label(current_labels)

    # Step 2: fetch messages
    if read_full_history:
        messages = await queries.get_messages_for_conversation(conversation_id)
    else:
        # Message-triggered run: read only since last successful run
        last_run = await _get_last_successful_run(conversation_id)
        since = last_run.completed_at if last_run else None
        messages = await queries.get_messages_for_conversation(conversation_id, since=since)

    # Step 3: call Gemini
    payload = build_payload(conv, messages, current_labels_clean)

    proposed_labels = await call_gemini(
        system_prompt=payload["system_prompt"],
        user_content=payload["user_content"],
    )

    if proposed_labels is None:
        logger.error(
            "TagAssigner router: Gemini call failed for conversation %s", conversation_id
        )
        await _log(run_id, conversation_id, "api", "router", "gemini", False, "0",
                   "Gemini call returned None")
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "api", "router", "gemini", True, "200")

    # Cache the Gemini result for write-back retry (never re-calls Gemini on retry)
    await queries.update_tagassigner_run_success(run_id, {"labels": proposed_labels})

    return await apply_resolved_labels(conversation_id, run_id, proposed_labels,
                                       current_labels=current_labels_clean)


async def apply_resolved_labels(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    proposed_labels: list[str],
    current_labels: Optional[list[str]] = None,
) -> bool:
    """
    Apply the resolved label pipeline and write back to Chatwoot.
    Called both by run_tagging() and by the batch results handler.
    Uses cached gemini_result for write-back retry — never re-calls Gemini.
    """
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    if current_labels is None:
        current_labels = await get_labels(conv.chatwoot_conversation_id) or conv.labels or []

    # Step 4: label resolution (pure — no I/O)
    resolved = resolve_labels(current_labels, proposed_labels)

    # Step 5: write resolved labels to Chatwoot (merge — only if changed)
    if set(resolved) != set(current_labels):
        success = await _write_labels_with_retry(
            conversation_id, run_id, conv.chatwoot_conversation_id, resolved
        )
        if not success:
            await queries.update_tagassigner_run_failed(run_id)
            return False
    else:
        logger.info(
            "TagAssigner router: no label changes for conversation %s — skipping write",
            conversation_id,
        )

    # Step 6: deterministic attribute writes (university / ogrenci_cinsiyet / ilgili_otel)
    # newest_evidence_at: latest message timestamp as the Option A comparison point
    newest_evidence_at = await _newest_message_at(conversation_id)
    attr_ok = await resolve_and_write_attributes(
        conversation_id=conversation_id,
        chatwoot_conversation_id=conv.chatwoot_conversation_id,
        run_id=run_id,
        newest_ilgili_otel_evidence_at=newest_evidence_at,
    )

    if not attr_ok:
        logger.error(
            "TagAssigner router: attribute write failed for conversation %s", conversation_id
        )
        await queries.update_tagassigner_run_failed(run_id)
        return False

    # Step 7: reset message counter + mark success
    await queries.reset_tagassigner_run_counts(conversation_id)
    await queries.update_tagassigner_run_success(run_id, {"labels": proposed_labels})

    logger.info(
        "TagAssigner router: run %s completed for conversation %s",
        run_id, conversation_id,
    )
    return True


async def _write_labels_with_retry(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    chatwoot_conversation_id: int,
    labels: list[str],
) -> bool:
    """
    Write the full label set to Chatwoot with exponential backoff retry.
    Records self-write before each attempt (feedback-loop guard).
    Retryable: 5xx / timeout. Non-retryable: 4xx → straight to fatal.
    """
    last_error: Optional[str] = None

    for attempt, delay in enumerate(_WRITEBACK_DELAYS, start=1):
        # Record self-write BEFORE the call for the feedback-loop guard (§6.5)
        record_self_write(chatwoot_conversation_id)

        result = await set_labels(chatwoot_conversation_id, labels)

        await _log(
            run_id, conversation_id, "api", "router", "chatwoot",
            result.ok, str(result.status_code),
            result.error if not result.ok else None,
        )

        if result.ok:
            return True

        last_error = result.error

        if result.status_code and 400 <= result.status_code < 500:
            logger.error(
                "TagAssigner router: non-retryable %d writing labels for conversation %s — aborting",
                result.status_code, conversation_id,
            )
            return False

        logger.warning(
            "TagAssigner router: label write attempt %d failed (HTTP %d) for conversation %s",
            attempt, result.status_code, conversation_id,
        )

        if attempt < len(_WRITEBACK_DELAYS):
            import asyncio
            await asyncio.sleep(delay)

    logger.fatal(
        "TagAssigner router: all label write retries exhausted for conversation %s — last error: %s",
        conversation_id, last_error,
    )
    return False


async def _get_last_successful_run(conversation_id: uuid.UUID):
    """Return the most recent successful run for this conversation, or None."""
    pool = queries.get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM tag_assigner_runs
        WHERE conversation_id = $1 AND status = 'success'
        ORDER BY completed_at DESC
        LIMIT 1
        """,
        conversation_id,
    )
    if not row:
        return None
    from app.db.models import TagAssignerRun
    import json
    data = dict(row)
    if data.get("gemini_result") and isinstance(data["gemini_result"], str):
        data["gemini_result"] = json.loads(data["gemini_result"])
    return TagAssignerRun(**data)


async def _newest_message_at(conversation_id: uuid.UUID) -> Optional[datetime]:
    pool = queries.get_pool()
    row = await pool.fetchrow(
        "SELECT MAX(created_at) AS newest FROM messages WHERE conversation_id = $1 AND is_private = false",
        conversation_id,
    )
    return row["newest"] if row else None


async def _log(
    run_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request_type: str,
    request_from: str,
    request_to: str,
    is_success: bool,
    status_code: str,
    fail_reason: Optional[str] = None,
) -> None:
    try:
        await queries.write_tagassigner_log(TagAssignerLog(
            run_id=run_id,
            conversation_id=conversation_id,
            request_type=request_type,
            request_from=request_from,
            request_to=request_to,
            is_success=is_success,
            status_code=status_code,
            fail_reason=fail_reason,
        ))
    except Exception as exc:
        logger.error("TagAssigner router: failed to write audit log: %s", exc)
