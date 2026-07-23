"""
Attribute writes for InfoGatherer flow completion (spec 018).

InfoGatherer writes university and ogrenci_cinsiyet to Chatwoot after RecEngine.
Does not auto-write ilgili_otel. TagAssigner uses a separate merge path.
"""
from __future__ import annotations
import logging
import uuid

from app.db import queries
from app.chatwoot_client import set_custom_attributes
from app.tagassigner.attribute_helpers import gender_enum_to_display

logger = logging.getLogger(__name__)


async def write_attributes_at_flow_completion(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
) -> bool:
    """
    InfoGatherer entry point after RecEngine / direct hotel path completes.
    Pushes university and gender only; ilgili_otel is left for human / TagAssigner.
    """
    conv = await queries.get_conversation_by_id(conversation_id)
    if not conv:
        return False

    attributes: dict = {}

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
        wrote_ilgili_otel=False,
        ilgili_otel=None,
        ilgili_otel_set_at=None,
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
