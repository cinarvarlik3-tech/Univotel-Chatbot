"""
University matching algorithm (§8.1).
Three tiers: exact → alias → Levenshtein ≤ 2.
Returns a MatchResult describing confidence and the matched university_id.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rapidfuzz.distance import Levenshtein as _Lev
levenshtein_distance = _Lev.distance

from app.db.models import University, UniversityAlias

LEVENSHTEIN_CUTOFF = 2

_SUFFIXES = [
    "üniversitesi", "universitesi", "university", "uni", "üni",
]

_DIACRITIC_MAP = str.maketrans(
    "şŞğĞıİöÖüÜçÇ",
    "sSgGiIoOuUcC",
)


class MatchConfidence(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    LEVENSHTEIN = "levenshtein"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass
class MatchResult:
    confidence: MatchConfidence
    university_id: Optional[uuid.UUID] = None
    parent_university_id: Optional[uuid.UUID] = None


def normalize(text: str) -> str:
    """Lowercase, strip Turkish diacritics, strip university suffixes, trim."""
    # İ (U+0130) lowercases to i+combining-dot in Python; replace it first.
    text = text.replace("İ", "i").replace("I", "ı")
    text = text.lower().translate(_DIACRITIC_MAP).strip()
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text


def match_university(
    raw_text: str,
    universities: list[University],
    aliases: list[UniversityAlias],
) -> MatchResult:
    """
    Run the three-tier matching algorithm against a candidate string.
    Empty / whitespace-only input is treated identically to no-match.
    """
    normalized = normalize(raw_text)
    if not normalized:
        return MatchResult(confidence=MatchConfidence.NONE)

    # Parent alias check — runs BEFORE Tier 1 exact match.
    # A string registered as a parent-level alias is an inherently ambiguous
    # reference (e.g. "itü", "bau", "ytu") and must always escalate to campus
    # clarification, even if a campus row happens to carry the same short_name.
    # Hoisting this above Tier 1 fixes the systemic short_name collision where
    # one campus was mistakenly given the parent's own identifier.
    for alias in aliases:
        if alias.alias == normalized and alias.parent_university_id:
            return MatchResult(confidence=MatchConfidence.ALIAS, parent_university_id=alias.parent_university_id)

    # Tier 1 — exact match against name or short_name
    for uni in universities:
        if normalize(uni.name) == normalized:
            return MatchResult(confidence=MatchConfidence.EXACT, university_id=uni.id)
        if uni.university_short_name and normalize(uni.university_short_name) == normalized:
            return MatchResult(confidence=MatchConfidence.EXACT, university_id=uni.id)

    # Tier 2 — campus-level alias lookup
    for alias in aliases:
        if alias.alias == normalized and alias.university_id:
            return MatchResult(confidence=MatchConfidence.ALIAS, university_id=alias.university_id)

    # Tier 3 — Levenshtein ≤ CUTOFF
    hits: list[tuple[int, uuid.UUID]] = []
    for uni in universities:
        norm_name = normalize(uni.name)
        dist = levenshtein_distance(normalized, norm_name)
        if dist <= LEVENSHTEIN_CUTOFF:
            hits.append((dist, uni.id))

    if not hits:
        return MatchResult(confidence=MatchConfidence.NONE)

    min_dist = min(d for d, _ in hits)
    closest = [uid for d, uid in hits if d == min_dist]

    if len(closest) == 1:
        return MatchResult(confidence=MatchConfidence.LEVENSHTEIN, university_id=closest[0])

    return MatchResult(confidence=MatchConfidence.AMBIGUOUS)
