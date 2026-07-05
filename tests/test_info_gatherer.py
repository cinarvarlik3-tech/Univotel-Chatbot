"""Unit tests for the InfoGatherer state machine helpers."""
import pytest
import re

from app.layers.info_gatherer import (
    GENDER_FEMALE,
    GENDER_MALE,
    _extract_university_candidate,
    _extract_gender,
)
from app.layers.matching import word_count_after_normalize


def test_gender_female_match():
    assert GENDER_FEMALE.search("kız yurdu")


def test_gender_male_match():
    assert GENDER_MALE.search("erkek")


def test_gender_no_match():
    assert not GENDER_FEMALE.search("okul arkadaşı")
    assert not GENDER_MALE.search("okul arkadaşı")


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


def test_extract_gender_female():
    assert _extract_gender("kız yurdu") == "female"


def test_extract_gender_male():
    assert _extract_gender("erkek öğrenci") == "male"


@pytest.mark.parametrize("text,expected", [
    ("boğaziçi", 1),
    ("istanbul teknik üniversitesi", 2),
    ("", 0),
])
def test_word_count_for_invalid_university_logic(text, expected):
    assert word_count_after_normalize(text) == expected
