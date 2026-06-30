"""Unit tests for the InfoGatherer state machine helpers."""
import pytest
import re

from app.layers.info_gatherer import (
    PHRASE_GATE,
    GENDER_FEMALE,
    GENDER_MALE,
    _extract_university_candidate,
)


# ---------------------------------------------------------------------------
# Phrase gate
# ---------------------------------------------------------------------------

def test_phrase_gate_match():
    for phrase in PHRASE_GATE:
        assert phrase in f"blah {phrase} blah"


def test_phrase_gate_no_match():
    assert not any(p in "Merhaba nasılsınız" for p in PHRASE_GATE)


# ---------------------------------------------------------------------------
# Gender regex
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "kız yurdu", "Kız", "bayan", "Bayan", "kadın", "kiz",
])
def test_gender_female_match(text):
    assert GENDER_FEMALE.search(text)


@pytest.mark.parametrize("text", [
    "bay", "erkek", "oğlan", "oglan", "Erkek",
])
def test_gender_male_match(text):
    assert GENDER_MALE.search(text)


def test_gender_no_match():
    assert not GENDER_FEMALE.search("okul arkadaşı")
    assert not GENDER_MALE.search("okul arkadaşı")


# ---------------------------------------------------------------------------
# University candidate extraction
# ---------------------------------------------------------------------------

def test_extract_from_univeritem_label():
    text = "Üniversitem: Boğaziçi Üniversitesi\nCinsiyet: Kız"
    candidate = _extract_university_candidate(text)
    assert candidate is not None
    assert "Boğaziçi" in candidate


def test_extract_from_univeritem_label_next_line():
    text = "Üniversitem:\nBoğaziçi Üniversitesi"
    candidate = _extract_university_candidate(text)
    assert candidate is not None
    assert "Boğaziçi" in candidate


def test_extract_keyword_based():
    text = "Marmara Üniversitesi öğrencisiyim"
    candidate = _extract_university_candidate(text)
    assert candidate is not None
    assert "Marmara" in candidate


def test_extract_no_university_info():
    candidate = _extract_university_candidate("Merhaba! İyi günler.")
    assert candidate is None
