"""
Attribute writes for InfoGatherer flow completion (spec 018).

InfoGatherer writes university, ogrenci_cinsiyet, and ilgili_otel to Chatwoot after
RecEngine. TagAssigner uses a separate merge path — it never writes ilgili_otel.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.db import queries
from app.chatwoot_client import set_custom_attributes
from app.tagassigner.attribute_helpers import gender_enum_to_display
from app.tagassigner.conflict import may_overwrite

logger = logging.getLogger(__name__)


async def write_attributes_at_flow_completion(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
) -> bool:
    """
    InfoGatherer entry point. Called immediately after RecEngine completes so
    university, gender, and ilgili_otel are visible in Chatwoot without waiting
    for the next TagAssigner run.

    Sets set_by=infoGatherer companions on written fields.
    """
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    attributes: dict = {}
    now = datetime.now(tz=timezone.utc)

    if conv.university_id:
        list_value = await queries.get_chatwoot_list_value_for_university(conv.university_id)
        if list_value:
            attributes["university"] = list_value
        else:
            logger.warning(
                "attribute_resolver: university_id=%s has no map row — skipping university",
                conv.university_id,
            )

    attributes["ogrenci_cinsiyet"] = gender_enum_to_display(conv.gender)

    ilgili_otel_value = await _resolve_ilgili_otel_for_infogatherer(
        conv.university_id,
        conv.gender,
        conv.ilgili_otel,
        conv.ilgili_otel_set_at,
    )
    if ilgili_otel_value is not None:
        attributes["ilgili_otel"] = ilgili_otel_value

    if not attributes:
        return True

    result = await set_custom_attributes(chatwoot_conversation_id, attributes)
    if not result.ok:
        logger.error(
            "attribute_resolver: InfoGatherer completion write failed for conversation %s: %s",
            conversation_id, result.error,
        )
        return False

    await queries.mark_infogatherer_attribute_companions(
        conversation_id=conversation_id,
        wrote_university="university" in attributes,
        wrote_gender=True,
        wrote_ilgili_otel=ilgili_otel_value is not None,
        ilgili_otel=ilgili_otel_value,
        ilgili_otel_set_at=now if ilgili_otel_value is not None else None,
    )
    return True


async def push_chatwoot_attribute_patches(
    chatwoot_conversation_id: int,
    patches: dict[str, str],
) -> bool:
    """TagAssigner: push changed bot-writable keys only (spec 018)."""
    if not patches:
        return True
    result = await set_custom_attributes(chatwoot_conversation_id, patches)
    if not result.ok:
        logger.error(
            "attribute_resolver: Chatwoot patch failed for conversation %d: %s",
            chatwoot_conversation_id, result.error,
        )
    return result.ok


async def _resolve_ilgili_otel_for_infogatherer(
    university_id: Optional[uuid.UUID],
    gender: Optional[str],
    current_value: Optional[str],
    field_set_at: Optional[datetime],
) -> Optional[str]:
    if not university_id or not gender:
        return None

    candidates = await queries.find_hotels_by_gender_and_university(gender, university_id)
    if not candidates:
        return None

    hotel = max(candidates, key=lambda h: h.priority_score or 0)
    list_value = await queries.get_chatwoot_list_value_for_hotel(hotel.id)
    if not list_value:
        return None

    if not may_overwrite(list_value, current_value, field_set_at, None):
        return None

    return list_value
