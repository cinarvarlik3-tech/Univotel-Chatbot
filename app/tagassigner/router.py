"""
TagAssigner Script Router — the single I/O broker (§1 of tagassigner-v1-spec.md).

Orchestrates the full pipeline per run (spec 018):
  DB → Router → LLM → Router → DB → Chatwoot

The LLM never touches the DB or Chatwoot directly. The Router is the sole authority.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Union

from app.config import settings, TESTING_PHONE_ALLOWLIST
from app.db import queries
from app.db.models import Conversation, Message, TagAssignerLog
from app.chatwoot_client import get_labels, set_labels, fetch_conversation
from app.tagassigner.label_resolver import (
    resolve_labels,
    remove_tag_trigger_label,
    strip_gemini_deal_awaiting,
    strip_llm_fiyat_soruyor,
)
from app.tagassigner.deal_awaiting import apply_deal_awaiting
from app.tagassigner.fiyat_soruyor import compute_fiyat_soruyor
from app.tagassigner.hizmet_veremiyoruz import (
    compute_hizmet_veremiyoruz,
    strip_llm_hizmet_veremiyoruz,
)
from app.tagassigner.payload_builder import build_payload
from app.tagassigner.university_list_context import load_formatted_university_list_lines
from app.llm.factory import resolve_task_config
from app.tagassigner.llm_client import call_llm
from app.tagassigner.attribute_resolver import push_chatwoot_attribute_patches
from app.tagassigner.llm_types import TagResult
from app.tagassigner.attribute_merger import (
    inbound_gender_signal,
    merge_attributes,
    reconcile_chatwoot_attributes,
)
from app.tagassigner.attribute_helpers import UNIVERSITY_CAMPUS_AMBIGUOUS, gender_enum_to_display
from app.tagassigner.info_check import apply_info_check, strip_gemini_info_check
from app.tagassigner.university_resolver import resolve_university_list_value
from app.tagassigner.university_canonicalizer import (
    extract_university_phrase_from_messages,
    get_university_universe,
    resolve_university_override,
)
from app.tagassigner.context_backfill import backfill_conversation_messages
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
        inserted = await backfill_conversation_messages(
            conversation_id, conv.chatwoot_conversation_id
        )
        logger.info(
            "TagAssigner router: context backfill conversation=%s inserted=%d",
            conversation_id, inserted,
        )
        messages = await queries.get_messages_for_conversation(conversation_id)
        logger.info(
            "TagAssigner router: transcript coverage conversation=%s local_msgs=%d",
            conversation_id, len(messages),
        )
    else:
        last_run = await _get_last_successful_run(conversation_id)
        since = last_run.completed_at if last_run else None
        messages = await queries.get_messages_for_conversation(conversation_id, since=since)

    university_display = await _university_display_for_conv(conv)
    university_list_lines = await load_formatted_university_list_lines()
    payload = build_payload(
        conv,
        messages,
        current_labels_clean,
        university_display,
        university_list_lines=university_list_lines,
    )

    llm_provider = resolve_task_config("tagassigner").provider
    tag_result = await call_llm(
        system_prompt=payload["system_prompt"],
        user_content=payload["user_content"],
    )

    if tag_result is None:
        logger.error(
            "TagAssigner router: LLM call failed for conversation %s", conversation_id
        )
        await _log(run_id, conversation_id, "api", "router", llm_provider, False, "0",
                   "LLM call returned None")
        await queries.update_tagassigner_run_failed(run_id)
        return False

    await _log(run_id, conversation_id, "api", "router", llm_provider, True, "200")

    await queries.update_tagassigner_run_success(
        run_id,
        {"labels": tag_result.labels, "attributes": tag_result.attributes},
    )

    # Only a full (non-windowed) history load doubles as the full_history
    # compute_fiyat_soruyor needs later — the incremental `since`-windowed
    # branch above is not a substitute and must not be passed through.
    full_history_messages = messages if read_full_history else None

    return await apply_tagassigner_result(
        conversation_id, run_id, tag_result,
        current_labels=current_labels_clean,
        full_history_messages=full_history_messages,
    )


async def apply_tagassigner_result(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    result: Union[TagResult, dict],
    current_labels: Optional[list[str]] = None,
    full_history_messages: Optional[list[Message]] = None,
) -> bool:
    """
    Apply label + attribute merge pipeline and write back to Chatwoot.
    Called by run_tagging() and the batch results handler.

    full_history_messages: pre-loaded full (non-windowed) conversation history,
    if the caller already has it (run_tagging's read_full_history=True path) —
    avoids a duplicate full-table message fetch for compute_fiyat_soruyor.
    Callers without it (batch path, incremental runs) leave it None and this
    function loads it itself.
    """
    if isinstance(result, dict):
        result = _tag_result_from_dict(result)
        if result is None:
            await queries.update_tagassigner_run_failed(run_id)
            return False

    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    if current_labels is None:
        current_labels = await get_labels(conv.chatwoot_conversation_id) or conv.labels or []

    labels_for_resolve = strip_llm_fiyat_soruyor(
        strip_llm_hizmet_veremiyoruz(
            strip_gemini_deal_awaiting(
                strip_gemini_info_check(result.labels)
            )
        )
    )
    resolved = resolve_labels(current_labels, labels_for_resolve)

    university_display = await _university_display_for_conv(conv)
    proposed_uni = result.attributes.get("university", "bilinmiyor")
    label_map = await queries.get_university_chatwoot_label_map()

    # Full (non-windowed) history, needed here for the deterministic Mode C
    # scan and again below for compute_fiyat_soruyor (Mode B) — loaded once
    # and reused for both, per spec 028.1 §2.3 (no duplicate DB round-trip).
    full_history = full_history_messages
    if full_history is None:
        full_history = await queries.get_messages_for_conversation(conversation_id)

    # Option-3 override (spec 027, Mode C; corrected by spec 028.1): the LLM's
    # list-value guess is the "belt"; the deterministic canonicalizer (app.
    # tagassigner.university_canonicalizer) is the "suspenders". The primary
    # mention input is now the Router's own scan of the lead's inbound
    # messages (authoritative), not the LLM's optional university_mention
    # echo — that echo is only used as a fallback when the deterministic
    # scan finds nothing. Pure decision logic lives in
    # resolve_university_override — see its docstring for the full precedence.
    universe = await get_university_universe()
    out_of_city_unis = await queries.get_all_out_of_city_universities()
    deterministic_mention = extract_university_phrase_from_messages(full_history)
    override_uni = resolve_university_override(
        proposed_uni,
        deterministic_mention or result.university_mention,
        label_map,
        universe,
        mention_is_authoritative=bool(deterministic_mention),
    )
    if override_uni != proposed_uni:
        logger.info(
            "TagAssigner router: Mode C override conversation=%s llm=%r deterministic=%r",
            conversation_id, proposed_uni, override_uni,
        )

    merge_attrs = dict(result.attributes)
    merge_attrs["university"] = override_uni

    proposed_uni_for_resolve = merge_attrs.get("university", "bilinmiyor")
    if proposed_uni_for_resolve.strip() not in ("bilinmiyor", UNIVERSITY_CAMPUS_AMBIGUOUS, "boş", ""):
        resolve_result = resolve_university_list_value(proposed_uni_for_resolve, label_map)
        resolved_uni_id = resolve_result.university_id
        logger.debug(
            "TagAssigner router: university resolve conversation=%s method=%s",
            conversation_id,
            resolve_result.method,
        )
    else:
        resolved_uni_id = None

    merge_result = merge_attributes(
        conv,
        merge_attrs,
        current_university_display=university_display,
        resolved_university_id=resolved_uni_id,
        chat_has_multiple_universities=False,
        inbound_gender=inbound_gender_signal(full_history),
    )

    llm_patch_keys = set(merge_result.chatwoot_patches.keys())

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

    university_display = await _university_display_for_conv(conv)
    fetch = await fetch_conversation(conv.chatwoot_conversation_id)
    chatwoot_attrs = (
        (fetch.data.get("custom_attributes") or {}) if fetch.ok and fetch.data else {}
    )
    if not fetch.ok:
        logger.warning(
            "TagAssigner router: could not fetch Chatwoot attributes for conversation %s — "
            "skipping reconciliation",
            conversation_id,
        )

    recon_patches = reconcile_chatwoot_attributes(
        conv,
        chatwoot_attrs,
        university_display=university_display,
    )
    recon_patch_keys = {
        k for k in recon_patches.keys() if k not in llm_patch_keys
    }
    all_patches = dict(recon_patches)
    all_patches.update(merge_result.chatwoot_patches)

    logger.info(
        "TagAssigner router: merge conversation=%s llm_patches=%s recon_patches=%s blocked=%s",
        conversation_id,
        list(llm_patch_keys) or "none",
        list(recon_patch_keys) or "none",
        [(m.field, m.reason) for m in merge_result.blocked_mismatches] or "none",
    )

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

    labels_with_fiyat = compute_fiyat_soruyor(full_history, info_decision.labels)

    labels_with_hizmet = compute_hizmet_veremiyoruz(
        deterministic_mention,
        universe,
        out_of_city_unis,
        conv.university_id,
        labels_with_fiyat,
    )

    final_labels = await apply_deal_awaiting(
        conv.university_id, conv.gender, labels_with_hizmet
    )
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

    if all_patches:
        record_self_write(conv.chatwoot_conversation_id)
        attr_ok = await push_chatwoot_attribute_patches(
            conv.chatwoot_conversation_id,
            all_patches,
        )
        if not attr_ok:
            await queries.update_tagassigner_run_failed(run_id)
            return False
        await _log(run_id, conversation_id, "api", "router", "chatwoot", True, "200")
    else:
        logger.debug(
            "TagAssigner router: no attribute patches for conversation %s — skipping Chatwoot write",
            conversation_id,
        )

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
        TagResult(
            labels=proposed_labels,
            attributes={
                "university": uni,
                "ogrenci_cinsiyet": gender_disp,
                "oda_tiipi": conv.oda_tiipi or "boş",
            },
        ),
        current_labels=current_labels,
    )


def _tag_result_from_dict(data: dict) -> Optional[TagResult]:
    labels = data.get("labels")
    if not isinstance(labels, list):
        return None
    university_mention_raw = data.get("university_mention")
    university_mention = (
        university_mention_raw if isinstance(university_mention_raw, str) else None
    )
    attributes = data.get("attributes")
    if isinstance(attributes, dict):
        return TagResult(
            labels=[str(l) for l in labels if isinstance(l, str)],
            attributes={str(k): str(v) for k, v in attributes.items()},
            university_mention=university_mention,
        )
    # Legacy runs: labels only — echo current state is unsafe; use sentinels (no-op merge)
    return TagResult(
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
