"""
Deterministic attribute writes (§6.9 of tagassigner-v1-spec.md).

Writes university, ogrenci_cinsiyet, and ilgili_otel to Chatwoot.
Gemini never decides these — the Router always computes them from DB columns.
All three are net-new Chatwoot writes (build brief #2).
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
    Resolves and writes the three deterministic attributes to Chatwoot.
    Returns True if all writes succeeded (or nothing needed writing).
    """
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    attributes: dict = {}

    # university: FK → human-readable name
    if conv.university_id:
        uni = await queries.get_university_by_id(conv.university_id)
        if uni:
            attributes["university"] = uni.name
        else:
            logger.error(
                "attribute_resolver: university_id=%s has no universities row (conversation=%s)",
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
        return True

    result = await set_custom_attributes(chatwoot_conversation_id, attributes)

    await queries.write_tagassigner_log(TagAssignerLog(
        run_id=run_id,
        conversation_id=conversation_id,
        request_type="api",
        request_from="router",
        request_to="chatwoot",
        is_success=result.ok,
        status_code=str(result.status_code),
        fail_reason=result.error if not result.ok else None,
    ))

    if not result.ok:
        logger.error(
            "attribute_resolver: failed to write attributes for conversation %s: %s",
            conversation_id, result.error,
        )

    # If ilgili_otel was written, update the DB companions atomically
    if result.ok and ilgili_otel_value is not None:
        await queries.sync_conversation_labels_and_attributes(
            conversation_id=conversation_id,
            labels=None,
            ilgili_otel=ilgili_otel_value,
            ilgili_otel_set_at=datetime.now(tz=timezone.utc),
            ilgili_otel_set_by="tagAssigner",
        )

    return result.ok


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
