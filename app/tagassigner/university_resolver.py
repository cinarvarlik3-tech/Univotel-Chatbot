"""
TagAssigner university list-value resolution (option-3 belt, spec 027).

Resolves Gemini's proposed university string to a university_id via
university_chatwoot_label_map. Used only by the Router — not by webhooks
or InfoGatherer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.layers.matching import levenshtein_distance, normalize
from app.tagassigner.attribute_helpers import UNIVERSITY_CAMPUS_AMBIGUOUS

_SENTINELS = frozenset({"bilinmiyor", UNIVERSITY_CAMPUS_AMBIGUOUS, "boş", ""})


@dataclass
class UniversityResolveResult:
    university_id: Optional[uuid.UUID]
    matched_list_value: Optional[str]
    method: str  # exact | normalized | levenshtein | none | ambiguous


def resolve_university_list_value(
    proposed: str,
    label_map: list[tuple[uuid.UUID, str]],
) -> UniversityResolveResult:
    """
    Resolve proposed Chatwoot list string to university_id.

    Resolution order: exact → normalized-exact → Levenshtein distance 1 (unique only).
    Returns method='ambiguous' when LD1 or normalized-exact matches more than one row.
    """
    raw = proposed.strip()
    if not raw or raw in _SENTINELS:
        return UniversityResolveResult(None, None, "none")

    for university_id, list_value in label_map:
        if list_value == raw:
            return UniversityResolveResult(university_id, list_value, "exact")

    norm_proposed = normalize(raw)
    normalized_matches = [
        (university_id, list_value)
        for university_id, list_value in label_map
        if normalize(list_value) == norm_proposed
    ]
    if len(normalized_matches) == 1:
        university_id, list_value = normalized_matches[0]
        return UniversityResolveResult(university_id, list_value, "normalized")
    if len(normalized_matches) > 1:
        return UniversityResolveResult(None, None, "ambiguous")

    ld1_matches = [
        (university_id, list_value)
        for university_id, list_value in label_map
        if levenshtein_distance(norm_proposed, normalize(list_value)) == 1
    ]
    if len(ld1_matches) == 1:
        university_id, list_value = ld1_matches[0]
        return UniversityResolveResult(university_id, list_value, "levenshtein")
    if len(ld1_matches) > 1:
        return UniversityResolveResult(None, None, "ambiguous")

    return UniversityResolveResult(None, None, "none")
