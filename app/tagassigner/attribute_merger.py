"""
Pure attribute merge logic for TagAssigner (spec 018).

Gemini proposes a full attribute snapshot; this module applies Router gates and
returns accepted DB updates plus blocked mismatches for info-check.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import TAGASSIGNER_ROOM_TYPE_VALUES
from app.db.models import Conversation
from app.tagassigner.attribute_helpers import (
    UNIVERSITY_CAMPUS_AMBIGUOUS,
    gender_enum_to_display,
    gender_display_to_enum,
    normalize_attribute_value,
    values_differ,
)


@dataclass
class BlockedMismatch:
    field: str
    current: str
    proposed: str
    reason: str


@dataclass
class AttributeMergeResult:
    university_id: Optional[uuid.UUID] = None
    gender: Optional[str] = None
    gender_clear: bool = False
    oda_tiipi: Optional[str] = None
    chatwoot_patches: dict[str, str] = field(default_factory=dict)
    blocked_mismatches: list[BlockedMismatch] = field(default_factory=list)

    @property
    def has_accepted_updates(self) -> bool:
        return (
            self.university_id is not None
            or self.gender is not None
            or self.gender_clear
            or self.oda_tiipi is not None
        )


def merge_attributes(
    conv: Conversation,
    proposed: dict[str, str],
    *,
    current_university_display: Optional[str],
    resolved_university_id: Optional[uuid.UUID],
    chat_has_multiple_universities: bool = False,
) -> AttributeMergeResult:
    """
    Merge Gemini's attribute snapshot against DB state under Router gates.

    resolved_university_id: FK from proposed university Chatwoot string (None if lookup failed).
    """
    result = AttributeMergeResult()

    _merge_university(
        conv,
        proposed.get("university", "bilinmiyor"),
        current_university_display,
        resolved_university_id,
        chat_has_multiple_universities,
        result,
    )
    _merge_gender(conv, proposed.get("ogrenci_cinsiyet", "bilinmiyor"), result)
    _merge_oda_tiipi(conv, proposed.get("oda_tiipi", "boş"), result)

    return result


def _merge_university(
    conv: Conversation,
    proposed_raw: str,
    current_display: Optional[str],
    resolved_id: Optional[uuid.UUID],
    multi_uni: bool,
    result: AttributeMergeResult,
) -> None:
    if proposed_raw.strip() == UNIVERSITY_CAMPUS_AMBIGUOUS:
        current_id_str = str(conv.university_id) if conv.university_id else ""
        current = normalize_attribute_value(current_display)
        result.blocked_mismatches.append(BlockedMismatch(
            field="university",
            current=current_id_str or (current or ""),
            proposed=proposed_raw.strip(),
            reason="campus_ambiguous",
        ))
        return

    proposed = normalize_attribute_value(proposed_raw)
    current = normalize_attribute_value(current_display)

    if not values_differ(current_display, proposed_raw):
        return
    if proposed is None and current is not None:
        return  # no clearing

    current_id_str = str(conv.university_id) if conv.university_id else ""
    proposed_id_str = str(resolved_id) if resolved_id else proposed_raw or ""

    if conv.university_set_by == "human":
        result.blocked_mismatches.append(BlockedMismatch(
            field="university",
            current=current_id_str or (current or ""),
            proposed=proposed_id_str,
            reason="human_set",
        ))
        return

    if multi_uni:
        result.blocked_mismatches.append(BlockedMismatch(
            field="university",
            current=current_id_str or (current or ""),
            proposed=proposed_id_str,
            reason="multi_university",
        ))
        return

    if resolved_id is None:
        result.blocked_mismatches.append(BlockedMismatch(
            field="university",
            current=current_id_str or (current or ""),
            proposed=proposed_raw,
            reason="validation_failed",
        ))
        return

    result.university_id = resolved_id
    result.chatwoot_patches["university"] = proposed_raw.strip()


def _merge_gender(conv: Conversation, proposed_raw: str, result: AttributeMergeResult) -> None:
    current_display = gender_enum_to_display(conv.gender)
    if not values_differ(current_display, proposed_raw):
        return

    proposed = normalize_attribute_value(proposed_raw)
    if proposed is None and conv.gender is not None:
        return

    if conv.gender_set_by == "human":
        result.blocked_mismatches.append(BlockedMismatch(
            field="ogrenci_cinsiyet",
            current=current_display,
            proposed=proposed_raw,
            reason="human_set",
        ))
        return

    try:
        gender_enum = gender_display_to_enum(proposed_raw)
    except ValueError:
        result.blocked_mismatches.append(BlockedMismatch(
            field="ogrenci_cinsiyet",
            current=current_display,
            proposed=proposed_raw,
            reason="validation_failed",
        ))
        return

    # gender_display_to_enum returns None for Bilinmiyor — clear DB gender
    if gender_enum is None:
        result.gender_clear = True
    else:
        result.gender = gender_enum
    result.chatwoot_patches["ogrenci_cinsiyet"] = gender_enum_to_display(gender_enum)


def _merge_oda_tiipi(conv: Conversation, proposed_raw: str, result: AttributeMergeResult) -> None:
    current = conv.oda_tiipi
    if not values_differ(current, proposed_raw):
        return

    proposed = normalize_attribute_value(proposed_raw)
    if proposed is None and current is not None:
        return

    if conv.oda_tiipi_set_by == "human":
        result.blocked_mismatches.append(BlockedMismatch(
            field="oda_tiipi",
            current=current or "",
            proposed=proposed_raw,
            reason="human_set",
        ))
        return

    if current is not None and proposed is not None and current != proposed:
        # Spec: add-if-missing for room type; block changes once set (non-human)
        result.blocked_mismatches.append(BlockedMismatch(
            field="oda_tiipi",
            current=current,
            proposed=proposed_raw,
            reason="already_set",
        ))
        return

    if proposed not in TAGASSIGNER_ROOM_TYPE_VALUES:
        result.blocked_mismatches.append(BlockedMismatch(
            field="oda_tiipi",
            current=current or "",
            proposed=proposed_raw,
            reason="validation_failed",
        ))
        return

    result.oda_tiipi = proposed
    result.chatwoot_patches["oda_tiipi"] = proposed


_SET_BY_FIELD = {
    "university": "university_set_by",
    "ogrenci_cinsiyet": "gender_set_by",
    "oda_tiipi": "oda_tiipi_set_by",
}


def reconcile_chatwoot_attributes(
    conv: Conversation,
    chatwoot_attrs: dict[str, Any],
    *,
    university_display: Optional[str],
) -> dict[str, str]:
    """
    Emit Chatwoot patches when DB holds a real value but Chatwoot is empty/stale.
    Covers the DB→Chatwoot sync gap without overwriting human-set Chatwoot edits.
    """
    patches: dict[str, str] = {}

    desired_by_key: dict[str, Optional[str]] = {
        "university": university_display if conv.university_id else None,
        "ogrenci_cinsiyet": gender_enum_to_display(conv.gender) if conv.gender else None,
        "oda_tiipi": conv.oda_tiipi,
    }

    for key, desired in desired_by_key.items():
        if normalize_attribute_value(desired) is None:
            continue

        chatwoot_current = chatwoot_attrs.get(key)
        if not values_differ(chatwoot_current, desired):
            continue

        set_by_field = _SET_BY_FIELD[key]
        if getattr(conv, set_by_field, None) == "human":
            if normalize_attribute_value(chatwoot_current) is not None:
                if values_differ(chatwoot_current, desired):
                    continue

        patches[key] = desired.strip() if isinstance(desired, str) else str(desired)

    return patches
