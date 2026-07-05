"""
Phrase gate evaluation for InfoGatherer (§1 of chatbot-phrase-gate-and-matching-spec).

Pre-conditions A (first inbound message) and B (hotel n-gram match), plus seven
keyword filters. Failed gates return IGNORE without state changes.
"""
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rapidfuzz.distance import Levenshtein as _Lev

from app.db.models import Hotel, University, UniversityAlias
from app.layers.matching import (
    LEVENSHTEIN_CUTOFF,
    match_hotel_by_ngram,
    normalize,
    scan_entities_by_ngram,
    MatchConfidence,
)

levenshtein_distance = _Lev.distance

# Filter 1 — fixed widget templates (exact substring or Levenshtein ≤ 2 on full message)
_WIDGET_TEMPLATES = [
    "Merhaba! Bunun hakkında daha faza bilgi alabilir miyim?",
    "Merhabalar Univotel!",
    "Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum.",
    "Bana en yakın Univotel neresi?",
    "Hello! Can I get more info on this?",
    "Hello Univotel!",
]

_WILDCARD_PREFIX = normalize("Merhaba!")
_WILDCARD_SUFFIX = normalize("yakınında öğrenci konaklaması")

# Filter 3 — greeting words (normalized); short tokens use word boundaries
_GREETING_WORDS = [
    "merhaba", "merhabalar", "selam", "selamlar", "hi", "hello", "hey",
    "iyi günler", "iyi akşamlar", "iyi sabahlar", "günaydın", "kolay gelsin",
]
_BOUNDARY_GREETINGS = {"hi", "hey"}

# Filter 4 — housing intent
_HOUSING_WORDS = ["konaklama", "yurt", "oda", "öğrenci oteli", "residence"]
_BOUNDARY_HOUSING = {"oda", "yurt"}

# Filter 5 — staj/dönem context
_STAJ_WORDS = [
    "staj", "stajyer", "yaz dönemi", "güz dönemi", "sonbahar dönemi", "dönem için",
]
_BOUNDARY_STAJ = {"staj"}

# Filter 6 — proximity intent
_PROXIMITY_WORDS = [
    "yakınında", "yakın", "bölgesinde", "en yakın", "üniversiteme yakın",
]

# Filter 7 — price/info intent (≥ 2 of 3 required)
_FILTER7_TERMS = ("fiyat", "bilgi", "icin")


class PhraseGateAction(str, Enum):
    IGNORE = "ignore"
    GREETING = "greeting"
    HOTEL_PATH = "hotel_path"


@dataclass
class PhraseGateResult:
    action: PhraseGateAction
    matched_hotel: Optional[Hotel] = None
    reason: str = ""


def _contains_keyword(normalized_text: str, keyword: str, boundary_tokens: set[str]) -> bool:
    """
    Match a filter keyword in normalized text.
    Short tokens use word boundaries; longer phrases use substring match.
    """
    kw = normalize(keyword)
    if not kw:
        return False
    if kw in boundary_tokens:
        return bool(re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", normalized_text))
    return kw in normalized_text


def _filter1_widget_match(content: str) -> bool:
    """Filter 1 — fixed widget substring or Levenshtein ≤ 2 on full message."""
    normalized_full = normalize(content)
    for template in _WIDGET_TEMPLATES:
        if template in content:
            return True
        if levenshtein_distance(normalize(template), normalized_full) <= LEVENSHTEIN_CUTOFF:
            return True
    if _WILDCARD_PREFIX in normalized_full and _WILDCARD_SUFFIX in normalized_full:
        return True
    return False


def _filter3_greeting(normalized_text: str) -> bool:
    return any(
        _contains_keyword(normalized_text, w, _BOUNDARY_GREETINGS)
        for w in _GREETING_WORDS
    )


def _filter4_housing(normalized_text: str) -> bool:
    return any(
        _contains_keyword(normalized_text, w, _BOUNDARY_HOUSING)
        for w in _HOUSING_WORDS
    )


def _filter5_staj(normalized_text: str) -> bool:
    return any(
        _contains_keyword(normalized_text, w, _BOUNDARY_STAJ)
        for w in _STAJ_WORDS
    )


def _filter6_proximity(normalized_text: str) -> bool:
    return any(normalize(w) in normalized_text for w in _PROXIMITY_WORDS)


def _filter7_price_info(normalized_text: str) -> bool:
    hits = sum(1 for term in _FILTER7_TERMS if term in normalized_text)
    return hits >= 2


def _any_keyword_filter(content: str) -> bool:
    normalized_text = normalize(content)
    return (
        _filter1_widget_match(content)
        or _filter3_greeting(normalized_text)
        or _filter4_housing(normalized_text)
        or _filter5_staj(normalized_text)
        or _filter6_proximity(normalized_text)
        or _filter7_price_info(normalized_text)
    )


def evaluate_phrase_gate(
    content: str,
    *,
    is_first_inbound: bool,
    hotels: list[Hotel],
    universities: list[University],
    aliases: list[UniversityAlias],
) -> PhraseGateResult:
    """
    Apply pre-conditions A/B and keyword filters (§1.3 decision table).

    Pre-condition B (hotel match) skips filters and fires even when A is false.
    """
    hotel = match_hotel_by_ngram(content, hotels)
    if hotel is not None:
        return PhraseGateResult(
            action=PhraseGateAction.HOTEL_PATH,
            matched_hotel=hotel,
            reason="precondition_b_hotel_match",
        )

    if not is_first_inbound:
        return PhraseGateResult(
            action=PhraseGateAction.IGNORE,
            reason="not_first_inbound_and_no_hotel_match",
        )

    if _filter1_widget_match(content):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter1_widget")

    entity = scan_entities_by_ngram(content, universities, aliases)
    if entity.confidence != MatchConfidence.NONE:
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter2_entity")

    normalized_text = normalize(content)
    if _filter3_greeting(normalized_text):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter3_greeting")
    if _filter4_housing(normalized_text):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter4_housing")
    if _filter5_staj(normalized_text):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter5_staj")
    if _filter6_proximity(normalized_text):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter6_proximity")
    if _filter7_price_info(normalized_text):
        return PhraseGateResult(action=PhraseGateAction.GREETING, reason="filter7_price_info")

    return PhraseGateResult(
        action=PhraseGateAction.IGNORE,
        reason="first_inbound_but_no_filter_matched",
    )
