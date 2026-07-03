"""
Deterministic attribute writes (§6.9 of tagassigner-v1-spec.md).

Writes university, ogrenci_cinsiyet, and ilgili_otel to Chatwoot.
Gemini never decides these — the Router always computes them from DB columns.

Two public entry points:
  - resolve_and_write_attributes()  — TagAssigner's caller; logs to tag_assigner_logs
  - write_attributes_at_flow_completion()  — InfoGatherer's caller; no run_id
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.db import queries
from app.db.models import TagAssignerLog
from app.chatwoot_client import set_custom_attributes
from app.tagassigner.conflict import may_overwrite

logger = logging.getLogger(__name__)


async def resolve_and_write_attributes(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
    run_id: uuid.UUID,
    newest_ilgili_otel_evidence_at: Optional[datetime],
) -> bool:
    """
    TagAssigner entry point. Resolves and writes attributes, then records
    the result in tag_assigner_logs under the given run_id.
    Returns True if all writes succeeded (or nothing needed writing).
    """
    ok, chatwoot_result = await _resolve_and_write(
        conversation_id,
        chatwoot_conversation_id,
        newest_ilgili_otel_evidence_at,
        set_by="tagAssigner",
    )

    if chatwoot_result is not None:
        await queries.write_tagassigner_log(TagAssignerLog(
            run_id=run_id,
            conversation_id=conversation_id,
            request_type="api",
            request_from="router",
            request_to="chatwoot",
            is_success=chatwoot_result.ok,
            status_code=str(chatwoot_result.status_code),
            fail_reason=chatwoot_result.error if not chatwoot_result.ok else None,
        ))
        if not chatwoot_result.ok:
            logger.error(
                "attribute_resolver: failed to write attributes for conversation %s: %s",
                conversation_id, chatwoot_result.error,
            )

    return ok


async def write_attributes_at_flow_completion(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
) -> bool:
    """
    InfoGatherer entry point. Called immediately after RecEngine completes so
    that university, gender, and ilgili_otel are visible in Chatwoot without
    waiting for the next TagAssigner run.

    No run_id: this is not a TagAssigner run. ilgili_otel_set_by is recorded
    as 'infoGatherer' so the audit trail distinguishes InfoGatherer-written
    values from TagAssigner-written ones.

    newest_ilgili_otel_evidence_at is None because InfoGatherer is always the
    *first* writer — the conflict rule allows the write unconditionally when
    the field has no existing value.
    """
    ok, chatwoot_result = await _resolve_and_write(
        conversation_id,
        chatwoot_conversation_id,
        newest_ilgili_otel_evidence_at=None,
        set_by="infoGatherer",
    )

    if chatwoot_result is not None and not chatwoot_result.ok:
        logger.error(
            "attribute_resolver: InfoGatherer completion write failed for conversation %s: %s",
            conversation_id, chatwoot_result.error,
        )

    return ok


# ---------------------------------------------------------------------------
# Shared core
# ---------------------------------------------------------------------------

async def _resolve_and_write(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
    newest_ilgili_otel_evidence_at: Optional[datetime],
    set_by: str,
):
    """
    Resolves attributes from DB state, writes to Chatwoot, syncs ilgili_otel
    companions. Returns (ok, chatwoot_result) where chatwoot_result is None if
    there was nothing to write (callers skip logging in that case).
    """
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False, None

    attributes: dict = {}

    # university: FK → exact Chatwoot List string via university_chatwoot_label_map
    if conv.university_id:
        list_value = await queries.get_chatwoot_list_value_for_university(conv.university_id)
        if list_value:
            attributes["university"] = list_value
        else:
            logger.warning(
                "attribute_resolver: university_id=%s has no university_chatwoot_label_map row "
                "— skipping university attribute (conversation=%s)",
                conv.university_id, conversation_id,
            )

    # ogrenci_cinsiyet: gender enum → Turkish display value
    if conv.gender == "male":
        attributes["ogrenci_cinsiyet"] = "Erkek"
    elif conv.gender == "female":
        attributes["ogrenci_cinsiyet"] = "Kız"
    else:
        attributes["ogrenci_cinsiyet"] = "Bilinmiyor"

    # ilgili_otel: hotels.id → exact Chatwoot list string, under Option A conflict rule
    ilgili_otel_value = await _resolve_ilgili_otel(
        conv.university_id,
        conv.gender,
        conv.ilgili_otel,
        conv.ilgili_otel_set_at,
        newest_ilgili_otel_evidence_at,
    )
    if ilgili_otel_value is not None:
        attributes["ilgili_otel"] = ilgili_otel_value

    if not attributes:
        return True, None

    result = await set_custom_attributes(chatwoot_conversation_id, attributes)

    # If ilgili_otel was written, update the DB companions atomically
    if result.ok and ilgili_otel_value is not None:
        await queries.sync_conversation_labels_and_attributes(
            conversation_id=conversation_id,
            labels=None,
            ilgili_otel=ilgili_otel_value,
            ilgili_otel_set_at=datetime.now(tz=timezone.utc),
            ilgili_otel_set_by=set_by,
        )

    return result.ok, result


async def _resolve_ilgili_otel(
    university_id: Optional[uuid.UUID],
    gender: Optional[str],
    current_value: Optional[str],
    field_set_at: Optional[datetime],
    newest_evidence_at: Optional[datetime],
) -> Optional[str]:
    """
    Resolves the recommended hotel → exact Chatwoot list string, respecting Option A.
    Returns None if nothing should be written (no match, or conflict rule blocks it).
    """
    if not university_id or not gender:
        return None

    candidates = await queries.find_hotels_by_gender_and_university(gender, university_id)
    if not candidates:
        return None

    hotel = max(candidates, key=lambda h: h.priority_score or 0)
    list_value = await queries.get_chatwoot_list_value_for_hotel(hotel.id)
    if not list_value:
        logger.warning(
            "attribute_resolver: hotel %s has no hotel_chatwoot_label_map row — skipping ilgili_otel",
            hotel.id,
        )
        return None

    if not may_overwrite(list_value, current_value, field_set_at, newest_evidence_at):
        logger.info(
            "attribute_resolver: Option A blocks ilgili_otel change "
            "(current=%r set_at=%s evidence_at=%s)",
            current_value, field_set_at, newest_evidence_at,
        )
        return None

    return list_value
