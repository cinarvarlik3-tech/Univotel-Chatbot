"""
Router-computed deal_awaiting label (spec 021).

deal_awaiting is never assigned by Gemini (label_resolver strips any Gemini
proposal of it). It is computed deterministically from the conversation's
resolved university: membership in deal_awaiting_universities. Add-only —
never removed here.

This mirrors the RecEngine callback trigger. TagAssigner is the safety net for
conversations where InfoGatherer broke before the RecEngine callback fired and
a human did not add the label manually.
"""
from __future__ import annotations
import uuid
from typing import Optional

from app.db import queries

DEAL_AWAITING_LABEL = "deal_awaiting"


async def apply_deal_awaiting(
    university_id: Optional[uuid.UUID],
    labels: list[str],
) -> list[str]:
    """
    Add deal_awaiting to the desired label set iff the conversation's university
    is on the deal_awaiting list and the label is not already present.
    Add-only: never removes. No-op when university_id is None.
    """
    if university_id is None:
        return labels
    if DEAL_AWAITING_LABEL in labels:
        return labels
    if await queries.is_deal_awaiting_university(university_id):
        return sorted(set(labels) | {DEAL_AWAITING_LABEL})
    return labels
