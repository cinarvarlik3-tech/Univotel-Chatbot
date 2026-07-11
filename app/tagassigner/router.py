"""
TagAssigner Script Router — the single I/O broker (§1 of tagassigner-v1-spec.md).

Orchestrates the full pipeline per run (spec 018):
  DB → Router → Gemini → Router → DB → Chatwoot

Gemini never touches the DB or Chatwoot directly. The Router is the sole authority.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Union

from app.config import settings, TESTING_PHONE_ALLOWLIST
from app.db import queries
from app.db.models import Conversation, TagAssignerLog
from app.chatwoot_client import get_labels, set_labels
from app.tagassigner.label_resolver import (
    resolve_labels,
    remove_tag_trigger_label,
    strip_gemini_deal_awaiting,
)
from app.tagassigner.deal_awaiting import apply_deal_awaiting
from app.tagassigner.payload_builder import build_payload
from app.tagassigner.gemini_client import call_gemini
from app.tagassigner.attribute_resolver import push_chatwoot_attribute_patches
from app.tagassigner.gemini_types import GeminiTagResult
from app.tagassigner.attribute_merger import merge_attributes
from app.tagassigner.attribute_helpers import gender_enum_to_display
from app.tagassigner.info_check import apply_info_check, strip_gemini_info_check
from app.webhooks.chatwoot import record_self_write

logger = logging.getLogger(__name__)

_WRITEBACK_DELAYS = [1.0, 2.0, 4.0]


def _is_taggable_in_testing_mode(conv: Conversation) -> bool:
    if not settings.testing_limitations_mode:
        return True
    return conv.contact_phone in TESTING_PHONE_ALLOWLIST


async def run_tagging(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    trigger_type: str,
    read_full_history: bool,
) -> bool:
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

    if not _is_taggable_in_testing_mode(conv):
        logger.info(
            "TagAssigner router: TESTING_MODE — conversation %s not on allowlist, skipping run %s",
            conversation_id, run_id,
        )
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "db_read", "router", "supabase", True, "200")

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

    current_labels_clean = remove_tag_trigger_label(current_labels)

    if read_full_history:
        messages = await queries.get_messages_for_conversation(conversation_id)
    else:
        last_run = await _get_last_successful_run(conversation_id)
        since = last_run.completed_at if last_run else None
        messages = await queries.get_messages_for_conversation(conversation_id, since=since)

    university_display = await _university_display_for_conv(conv)
    payload = build_payload(conv, messages, current_labels_clean, university_display)

    gemini_result = await call_gemini(
        system_prompt=payload["system_prompt"],
        user_content=payload["user_content"],
    )

    if gemini_result is None:
        logger.error(
            "TagAssigner router: Gemini call failed for conversation %s", conversation_id
        )
        await _log(run_id, conversation_id, "api", "router", "gemini", False, "0",
                   "Gemini call returned None")
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "api", "router", "gemini", True, "200")

    await queries.update_tagassigner_run_success(
        run_id,
        {"labels": gemini_result.labels, "attributes": gemini_result.attributes},
    )

    return await apply_tagassigner_result(
        conversation_id, run_id, gemini_result, current_labels=current_labels_clean
    )


async def apply_tagassigner_result(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    result: Union[GeminiTagResult, dict],
    current_labels: Optional[list[str]] = None,
) -> bool:
    """
    Apply label + attribute merge pipeline and write back to Chatwoot.
    Called by run_tagging() and the batch results handler.
    """
    if isinstance(result, dict):
        result = _gemini_result_from_dict(result)
        if result is None:
            await queries.update_tagassigner_run_failed(run_id)
            return False

    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    if current_labels is None:
        current_labels = await get_labels(conv.chatwoot_conversation_id) or conv.labels or []

    labels_for_resolve = strip_gemini_deal_awaiting(
        strip_gemini_info_check(result.labels)
    )
    resolved = resolve_labels(current_labels, labels_for_resolve)

    university_display = await _university_display_for_conv(conv)
    proposed_uni = result.attributes.get("university", "bilinmiyor")
    resolved_uni_id = await queries.get_university_id_for_chatwoot_list_value(
        proposed_uni.strip()
    ) if proposed_uni.strip() not in ("bilinmiyor", "boş", "") else None

    merge_result = merge_attributes(
        conv,
        result.attributes,
        current_university_display=university_display,
        resolved_university_id=resolved_uni_id,
        chat_has_multiple_universities=False,
    )

    if merge_result.has_accepted_updates:
        await queries.apply_tagassigner_attribute_updates(
            conversation_id,
            university_id=merge_result.university_id,
            gender=merge_result.gender,
            gender_clear=merge_result.gender_clear,
            oda_tiipi=merge_result.oda_tiipi,
        )
        conv = await queries.get_conversation_by_id(conversation_id)
        if not conv:
            return False

    now = datetime.now(tz=timezone.utc)
    info_decision = apply_info_check(resolved, conv, merge_result.blocked_mismatches, now)

    if info_decision.clear_active:
        await queries.update_info_check_state(conversation_id, clear_active=True)
    elif info_decision.fingerprint:
        await queries.update_info_check_state(
            conversation_id,
            fingerprint=info_decision.fingerprint,
            added_at=info_decision.added_at,
        )

    final_labels = await apply_deal_awaiting(conv.university_id, info_decision.labels)
    if set(final_labels) != set(current_labels):
        success = await _write_labels_with_retry(
            conversation_id, run_id, conv.chatwoot_conversation_id, final_labels
        )
        if not success:
            await queries.update_tagassigner_run_failed(run_id)
            return False
    else:
        logger.info(
            "TagAssigner router: no label changes for conversation %s — skipping write",
            conversation_id,
        )

    if merge_result.chatwoot_patches:
        record_self_write(conv.chatwoot_conversation_id)
        attr_ok = await push_chatwoot_attribute_patches(
            conv.chatwoot_conversation_id,
            merge_result.chatwoot_patches,
        )
        if not attr_ok:
            await queries.update_tagassigner_run_failed(run_id)
            return False
        await _log(run_id, conversation_id, "api", "router", "chatwoot", True, "200")

    await queries.reset_tagassigner_run_counts(conversation_id)
    await queries.update_tagassigner_run_success(
        run_id,
        {"labels": result.labels, "attributes": result.attributes},
    )

    logger.info(
        "TagAssigner router: run %s completed for conversation %s",
        run_id, conversation_id,
    )
    return True


async def apply_resolved_labels(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    proposed_labels: list[str],
    current_labels: Optional[list[str]] = None,
) -> bool:
    """Backward-compatible entry for callers that only have labels (no attributes)."""
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False
    uni = await _university_display_for_conv(conv) or "bilinmiyor"
    gender_disp = gender_enum_to_display(conv.gender) if conv.gender else "bilinmiyor"
    return await apply_tagassigner_result(
        conversation_id,
        run_id,
        GeminiTagResult(
            labels=proposed_labels,
            attributes={
                "university": uni,
                "ogrenci_cinsiyet": gender_disp,
                "oda_tiipi": conv.oda_tiipi or "boş",
            },
        ),
        current_labels=current_labels,
    )


def _gemini_result_from_dict(data: dict) -> Optional[GeminiTagResult]:
    labels = data.get("labels")
    if not isinstance(labels, list):
        return None
    attributes = data.get("attributes")
    if isinstance(attributes, dict):
        return GeminiTagResult(
            labels=[str(l) for l in labels if isinstance(l, str)],
            attributes={str(k): str(v) for k, v in attributes.items()},
        )
    # Legacy runs: labels only — echo current state is unsafe; use sentinels (no-op merge)
    return GeminiTagResult(
        labels=[str(l) for l in labels if isinstance(l, str)],
        attributes={
            "university": "bilinmiyor",
            "ogrenci_cinsiyet": "bilinmiyor",
            "oda_tiipi": "boş",
        },
    )


async def _university_display_for_conv(conv: Conversation) -> Optional[str]:
    if not conv.university_id:
        return None
    return await queries.get_chatwoot_list_value_for_university(conv.university_id)


async def _write_labels_with_retry(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    chatwoot_conversation_id: int,
    labels: list[str],
) -> bool:
    last_error: Optional[str] = None

    for attempt, delay in enumerate(_WRITEBACK_DELAYS, start=1):
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
    data = dict(row)
    if data.get("gemini_result") and isinstance(data["gemini_result"], str):
        data["gemini_result"] = json.loads(data["gemini_result"])
    return TagAssignerRun(**data)


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
