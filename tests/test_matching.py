"""Unit tests for the university matching algorithm (app/layers/matching.py)."""
import uuid
import pytest

from app.layers.matching import (
    MatchConfidence,
    normalize,
    match_university,
)
from app.db.models import University, UniversityAlias


def _uni(name: str, short_name: str | None = None) -> University:
    return University(id=uuid.uuid4(), name=name, university_short_name=short_name)


def _alias(university_id: uuid.UUID, alias: str) -> UniversityAlias:
    return UniversityAlias(id=uuid.uuid4(), university_id=university_id, alias=alias)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------

def test_normalize_strips_suffix():
    assert normalize("İstanbul Üniversitesi") == "istanbul"
    assert normalize("Bogazici Universitesi") == "bogazici"


def test_normalize_strips_turkish_diacritics():
    assert normalize("Şişli") == "sisli"
    assert normalize("ÜÖ") == "uo"
    assert normalize("Ğ") == "g"
    assert normalize("İ") == "i"


def test_normalize_lowercase():
    assert normalize("ISTANBUL") == "istanbul"


def test_normalize_empty():
    assert normalize("") == ""
    assert normalize("   ") == ""


# ---------------------------------------------------------------------------
# match_university() — exact
# ---------------------------------------------------------------------------

def test_exact_match_by_name():
    unis = [_uni("Boğaziçi Üniversitesi")]
    result = match_university("Boğaziçi Üniversitesi", unis, [])
    assert result.confidence == MatchConfidence.EXACT
    assert result.university_id == unis[0].id


def test_exact_match_by_short_name():
    unis = [_uni("İstanbul Kültür Üniversitesi", short_name="İKÜ")]
    result = match_university("İKÜ", unis, [])
    assert result.confidence == MatchConfidence.EXACT


def test_exact_match_case_insensitive():
    unis = [_uni("Marmara Üniversitesi")]
    result = match_university("marmara", unis, [])
    assert result.confidence == MatchConfidence.EXACT


# ---------------------------------------------------------------------------
# match_university() — alias
# ---------------------------------------------------------------------------

def test_alias_match():
    uni = _uni("İstanbul Teknik Üniversitesi")
    aliases = [_alias(uni.id, "itu")]
    result = match_university("itu", [uni], aliases)
    assert result.confidence == MatchConfidence.ALIAS
    assert result.university_id == uni.id


# ---------------------------------------------------------------------------
# match_university() — Levenshtein
# ---------------------------------------------------------------------------

def test_levenshtein_single_typo():
    unis = [_uni("Yıldız Teknik Üniversitesi")]
    # "yidiz" vs "yildiz" — 1 char diff
    result = match_university("Yıdız Teknik", unis, [])
    assert result.confidence == MatchConfidence.LEVENSHTEIN


def test_levenshtein_ambiguous_tie():
    unis = [
        _uni("Anadolu Üniversitesi"),
        _uni("Anadol Üniversitesi"),  # synthetic tie
    ]
    # Force a tie by crafting a query equidistant from both
    result = match_university("anadolu", unis, [])
    # "anadolu" exactly matches first → EXACT, not AMBIGUOUS
    assert result.confidence == MatchConfidence.EXACT


def test_levenshtein_ambiguous():
    unis = [
        _uni("Abcde Üniversitesi"),
        _uni("Abcdf Üniversitesi"),
    ]
    # "abcdx" is distance 1 from both
    result = match_university("abcdx", unis, [])
    assert result.confidence == MatchConfidence.AMBIGUOUS
    assert result.university_id is None


# ---------------------------------------------------------------------------
# match_university() — no match
# ---------------------------------------------------------------------------

def test_no_match():
    unis = [_uni("Boğaziçi Üniversitesi")]
    result = match_university("Harvard", unis, [])
    assert result.confidence == MatchConfidence.NONE
    assert result.university_id is None


def test_empty_input():
    unis = [_uni("Boğaziçi Üniversitesi")]
    result = match_university("", unis, [])
    assert result.confidence == MatchConfidence.NONE


def test_whitespace_input():
    unis = [_uni("Boğaziçi Üniversitesi")]
    result = match_university("   ", unis, [])
    assert result.confidence == MatchConfidence.NONE
