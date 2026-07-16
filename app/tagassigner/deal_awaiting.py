"""
Router-computed deal_awaiting label (spec 021, serviceability gate spec 027).

deal_awaiting is never assigned by Gemini (label_resolver strips any Gemini
proposal of it). It is computed deterministically from the conversation's
resolved university: membership in deal_awaiting_universities AND the absence
of a serviceable property for the lead's gender. Add-only — never removed
here; closing a deal_awaiting lead is a deliberate human/command workflow.

This mirrors RecEngine's own NOT_FOUND predicate (app/layers/rec_engine.py) so
TagAssigner's safety-net sweep can never disagree with what a live RecEngine
run would have produced. TagAssigner is the safety net for conversations
where InfoGatherer broke before the RecEngine callback fired and a human did
not add the label manually.
"""
from __future__ import annotations
import uuid
from typing import Optional

from app.db import queries

DEAL_AWAITING_LABEL = "deal_awaiting"


async def _is_serviceable(university_id: uuid.UUID, gender: Optional[str]) -> bool:
    """
    True when we have inventory the lead can actually be placed into.

    Known gender: mirrors RecEngine's find_hotels_by_gender_and_university —
    non-empty means FOUND, which always wins over deal_awaiting.
    Unknown gender: conservative — any serviceable property (either gender)
    is treated as coverage, since we cannot yet tell which one applies.
    """
    if gender in ("female", "male"):
        hotels = await queries.find_hotels_by_gender_and_university(gender, university_id)
        return len(hotels) > 0
    return await queries.has_any_serviceable_property(university_id)


async def apply_deal_awaiting(
    university_id: Optional[uuid.UUID],
    gender: Optional[str],
    labels: list[str],
) -> list[str]:
    """
    Add deal_awaiting to the desired label set iff the conversation's university
    is on the deal_awaiting list AND no serviceable property covers this lead's
    gender. Add-only: never removes. No-op when university_id is None.
    """
    if university_id is None:
        return labels
    if DEAL_AWAITING_LABEL in labels:
        return labels
    if not await queries.is_deal_awaiting_university(university_id):
        return labels
    if await _is_serviceable(university_id, gender):
        return labels
    return sorted(set(labels) | {DEAL_AWAITING_LABEL})
