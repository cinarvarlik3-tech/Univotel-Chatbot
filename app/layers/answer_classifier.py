"""
Answer-vs-off-script classification for InfoGatherer slot-filling replies.

Runs only after match_university() and match_out_of_city() both fail. Pure
functions — no DB or I/O. Biased toward NOT_AN_ANSWER when ambiguous so
off-script questions are not reprompted as bad university names.
"""
from __future__ import annotations
import re
from enum import Enum

from app.layers.matching import (
    is_near_miss_university,
    word_count_after_normalize,
)
from app.db.models import University

# Fold Turkish diacritics for marker matching (same map as matching.py).
_DIACRITIC_MAP = str.maketrans(
    "şŞğĞıİöÖüÜçÇ",
    "sSgGiIoOuUcC",
)

# Short tokens matched with word boundaries to avoid false positives (e.g. Cihangir/hangi).
_BOUNDARY_QUESTION_WORDS = frozenset({
    "ne", "nerede", "nerde", "nasil", "neden", "nicin", "niye",
    "kac", "kim", "hangi",
})
# Multi-word / unambiguous phrases keep substring matching.
_SUBSTRING_QUESTION_WORDS = (
    "ne zaman", "ne kadar",
)
_REQUEST_VERBS = (
    "istiyorum", "ariyorum", "bakiyorum", "bakiyoruz", "alabilir",
    "olur mu", "mumkun mu", "var mi",
)
_THIRD_PERSON_REFERENTS = (
    "kizim", "oglum", "cocugum", "kardesim", "arkadasim", "yegenim", "esim",
)
_EDUCATION_ANCHORS = (
    "universite", "university", "fakulte", "kampus", "yuksekokol", "myo",
)
_QUESTION_CLITICS = frozenset({"mi", "mı", "mu", "mü"})

_SHORT_ANSWER_MAX_WORDS = 2


class AnswerAssessment(str, Enum):
    ANSWER_ATTEMPT = "answer_attempt"
    NOT_AN_ANSWER = "not_an_answer"


def _fold_diacritics(text: str) -> str:
    """Lowercase and strip Turkish diacritics without university suffix stripping."""
    text = text.replace("İ", "i").replace("I", "ı")
    return text.lower().translate(_DIACRITIC_MAP)


def _tokenize_for_markers(text: str) -> list[str]:
    """Split on non-word characters; preserve clitic tokens like mı/mi."""
    folded = _fold_diacritics(text.strip())
    if not folded:
        return []
    return [t for t in re.split(r"[^\w]+", folded) if t]


def _contains_phrase(folded_text: str, phrase: str) -> bool:
    """Substring match for multi-word phrases on diacritic-folded text."""
    return _fold_diacritics(phrase) in folded_text


def _contains_boundary_word(folded_text: str, word: str) -> bool:
    """Whole-token match on diacritic-folded text (same pattern as phrase_gate greetings)."""
    return bool(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", folded_text))


def _offscript_markers(content: str) -> bool:
    """
    True when the message reads as a question, request, or third-person context
    rather than a direct university-name answer.
    """
    stripped = content.strip()
    if not stripped:
        return False

    if stripped.rstrip().endswith("?"):
        return True

    folded = _fold_diacritics(stripped)
    tokens = _tokenize_for_markers(stripped)

    if any(t in _QUESTION_CLITICS for t in tokens):
        return True

    for word in _BOUNDARY_QUESTION_WORDS:
        if _contains_boundary_word(folded, word):
            return True

    for phrase in _SUBSTRING_QUESTION_WORDS + _REQUEST_VERBS + _THIRD_PERSON_REFERENTS:
        if _contains_phrase(folded, phrase):
            return True

    return False


def _has_education_anchor(folded_text: str) -> bool:
    """True when the message mentions university/school vocabulary (answer-shaped)."""
    for anchor in _EDUCATION_ANCHORS:
        if anchor in folded_text:
            return True
    return False


def classify_university_reply(
    content: str,
    universities: list[University],
) -> AnswerAssessment:
    """
    Classify a reply that already failed university and out-of-city matching.

    Decision order (recall-biased against treating off-script as answer attempts):
    1. Off-script markers → NOT_AN_ANSWER
    2. Near-miss to a known university name → ANSWER_ATTEMPT
    3. Short reply (≤2 words, no off-script) → ANSWER_ATTEMPT (bare name / abbreviation)
    4. Education vocabulary present → ANSWER_ATTEMPT (long fake uni name attempts)
    5. Otherwise → NOT_AN_ANSWER (long rambling with no answer shape)
    """
    if _offscript_markers(content):
        return AnswerAssessment.NOT_AN_ANSWER

    if is_near_miss_university(content, universities):
        return AnswerAssessment.ANSWER_ATTEMPT

    if word_count_after_normalize(content) <= _SHORT_ANSWER_MAX_WORDS:
        return AnswerAssessment.ANSWER_ATTEMPT

    folded = _fold_diacritics(content)
    if _has_education_anchor(folded):
        return AnswerAssessment.ANSWER_ATTEMPT

    return AnswerAssessment.NOT_AN_ANSWER
