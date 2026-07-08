"""
University matching algorithm (§8.1).
Three tiers: exact → alias → Levenshtein ≤ 2.
Returns a MatchResult describing confidence and the matched university_id.

Also exposes n-gram scanning helpers for phrase-gate entity and hotel matching.
"""
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional

from rapidfuzz.distance import Levenshtein as _Lev
levenshtein_distance = _Lev.distance

from app.db.models import Hotel, OutOfCityUniversity, University, UniversityAlias, UniversityParentMap

LEVENSHTEIN_CUTOFF = 2  # legacy reference; comparisons use _get_levenshtein_cutoff()
NEAR_MISS_BAND = 2  # extra Levenshtein distance beyond accept cutoff for answer-likelihood
NEAR_MISS_MIN_LEN = 4  # inputs shorter than this never count as near-miss


def _get_levenshtein_cutoff(normalized: str) -> int:
    """Length-based Levenshtein tolerance — short inputs disable fuzzy Tier 3."""
    length = len(normalized)
    if length <= 3:
        return 0
    if length <= 5:
        return 1
    if length <= 7:
        return 2
    return 3


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


def tokenize(text: str) -> list[str]:
    """Split normalized text into word tokens for n-gram windows."""
    normalized = normalize(text)
    if not normalized:
        return []
    return normalized.split()


def scan_ngrams(text: str, min_n: int = 1, max_n: int = 4) -> Iterator[str]:
    """
    Yield contiguous word n-grams longest-first (max_n down to min_n).
    Used by phrase-gate entity and hotel scans.
    """
    words = tokenize(text)
    if not words:
        return
    upper = min(max_n, len(words))
    for n in range(upper, min_n - 1, -1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i : i + n])


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
    for alias in aliases:
        if normalize(alias.alias) == normalized and alias.parent_university_id:
            return MatchResult(
                confidence=MatchConfidence.ALIAS,
                parent_university_id=alias.parent_university_id,
            )

    # Tier 1 — exact match against name or short_name
    for uni in universities:
        if normalize(uni.name) == normalized:
            return MatchResult(confidence=MatchConfidence.EXACT, university_id=uni.id)
        if uni.university_short_name and normalize(uni.university_short_name) == normalized:
            return MatchResult(confidence=MatchConfidence.EXACT, university_id=uni.id)

    # Tier 2 — campus-level alias lookup
    for alias in aliases:
        if normalize(alias.alias) == normalized and alias.university_id:
            return MatchResult(confidence=MatchConfidence.ALIAS, university_id=alias.university_id)

    # Tier 3 — Levenshtein ≤ dynamic cutoff
    cutoff = _get_levenshtein_cutoff(normalized)
    hits: list[tuple[int, uuid.UUID]] = []
    for uni in universities:
        norm_name = normalize(uni.name)
        dist = levenshtein_distance(normalized, norm_name)
        if dist <= cutoff:
            hits.append((dist, uni.id))

    if not hits:
        return MatchResult(confidence=MatchConfidence.NONE)

    min_dist = min(d for d, _ in hits)
    closest = [uid for d, uid in hits if d == min_dist]

    if len(closest) == 1:
        return MatchResult(confidence=MatchConfidence.LEVENSHTEIN, university_id=closest[0])

    return MatchResult(confidence=MatchConfidence.AMBIGUOUS)


def match_out_of_city(
    raw_text: str,
    out_of_city_unis: list[OutOfCityUniversity],
) -> Optional[OutOfCityUniversity]:
    """
    Scan out_of_city_universities by name and short_name.
    Returns the first matching university, or None.
    Called only after match_university() returns NONE.
    """
    normalized = normalize(raw_text)
    if not normalized:
        return None

    cutoff = _get_levenshtein_cutoff(normalized)

    for uni in out_of_city_unis:
        if normalize(uni.name) == normalized:
            return uni
        if uni.short_name and normalize(uni.short_name) == normalized:
            return uni

    if cutoff > 0:
        hits: list[tuple[int, OutOfCityUniversity]] = []
        for uni in out_of_city_unis:
            dist = levenshtein_distance(normalized, normalize(uni.name))
            if dist <= cutoff:
                hits.append((dist, uni))
            if uni.short_name:
                dist_short = levenshtein_distance(normalized, normalize(uni.short_name))
                if dist_short <= cutoff:
                    hits.append((dist_short, uni))

        if hits:
            hits.sort(key=lambda x: x[0])
            return hits[0][1]

    return None


def match_campus(
    raw_text: str,
    parent_university_id: uuid.UUID,
    campuses: list[UniversityParentMap],
    aliases: list[UniversityAlias],
) -> Optional[UniversityParentMap]:
    """
    Match a campus label or alias scoped to a parent university.
    Scans n-grams longest-first so campus names embedded in longer replies resolve.
    """
    if not campuses:
        return None

    scoped_aliases = [
        a for a in aliases
        if a.university_id and any(c.university_id == a.university_id for c in campuses)
    ]

    for candidate in scan_ngrams(raw_text):
        normalized = normalize(candidate)
        if not normalized:
            continue
        for campus in campuses:
            if campus.parent_university_id != parent_university_id:
                continue
            if normalize(campus.campus_label) == normalized:
                return campus
            for alias in scoped_aliases:
                if alias.university_id == campus.university_id and normalize(alias.alias) == normalized:
                    return campus

    normalized_full = normalize(raw_text)
    if normalized_full:
        for campus in campuses:
            if campus.parent_university_id != parent_university_id:
                continue
            if normalize(campus.campus_label) == normalized_full:
                return campus
            for alias in scoped_aliases:
                if alias.university_id == campus.university_id and normalize(alias.alias) == normalized_full:
                    return campus

    return None


def scan_entities_by_ngram(
    text: str,
    universities: list[University],
    aliases: list[UniversityAlias],
) -> MatchResult:
    """
    Phrase-gate Filter 2: scan 1–4 word n-grams (longest first) via match_university.
    """
    for candidate in scan_ngrams(text):
        result = match_university(candidate, universities, aliases)
        if result.confidence != MatchConfidence.NONE:
            return result
    return MatchResult(confidence=MatchConfidence.NONE)


def match_hotel_by_ngram(text: str, hotels: list[Hotel]) -> Optional[Hotel]:
    """
    Pre-condition B / hotel path: n-gram Levenshtein scan against hotels.name.
    Returns the first matching visible hotel (longest n-gram wins via scan order).
    """
    for candidate in scan_ngrams(text):
        normalized_candidate = normalize(candidate)
        if not normalized_candidate:
            continue
        for hotel in hotels:
            if not hotel.is_visible:
                continue
            normalized_name = normalize(hotel.name)
            if not normalized_name:
                continue
            if normalized_candidate == normalized_name:
                return hotel
            if levenshtein_distance(normalized_candidate, normalized_name) <= _get_levenshtein_cutoff(normalized_candidate):
                return hotel
    return None


def word_count_after_normalize(text: str) -> int:
    """Token count after normalize(); used for invalid-university input handling."""
    return len(tokenize(text))


def is_near_miss_university(
    raw_text: str,
    universities: list[University],
    *,
    band: int = NEAR_MISS_BAND,
) -> bool:
    """
    True when raw_text is close enough to a known university name to plausibly
    be a typo'd answer, but beyond the Levenshtein accept cutoff used by
    match_university(). Used only after match_university() returns NONE.
    """
    normalized = normalize(raw_text)
    if len(normalized) < NEAR_MISS_MIN_LEN:
        return False

    cutoff = _get_levenshtein_cutoff(normalized)
    max_dist = cutoff + band

    for uni in universities:
        for candidate in (uni.name, uni.university_short_name):
            if not candidate:
                continue
            norm_candidate = normalize(candidate)
            if not norm_candidate:
                continue
            dist = levenshtein_distance(normalized, norm_candidate)
            if cutoff < dist <= max_dist:
                return True

    return False
