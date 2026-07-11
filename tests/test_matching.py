"""Unit tests for the university matching algorithm (app/layers/matching.py)."""
import uuid
import pytest

from app.layers.matching import (
    MatchConfidence,
    normalize,
    match_university,
    match_campus,
    match_out_of_city,
    match_hotel_by_ngram,
    scan_entities_by_ngram,
    word_count_after_normalize,
    is_near_miss_university,
    is_question_form,
    NEAR_MISS_BAND,
    ALIAS_FUZZY_MAX_DIST,
    ALIAS_FUZZY_MIN_LEN,
    NEAR_MISS_MIN_LEN,
    _get_levenshtein_cutoff,
)
from app.db.models import University, UniversityAlias, Hotel, OutOfCityUniversity, UniversityParentMap


def _uni(name: str, short_name: str | None = None) -> University:
    return University(id=uuid.uuid4(), name=name, university_short_name=short_name)


def _alias(university_id: uuid.UUID, alias: str) -> UniversityAlias:
    return UniversityAlias(id=uuid.uuid4(), university_id=university_id, alias=alias)


def _parent_alias(parent_university_id: uuid.UUID, alias: str) -> UniversityAlias:
    return UniversityAlias(
        id=uuid.uuid4(),
        parent_university_id=parent_university_id,
        alias=alias,
    )


def _ooc(name: str, short_name: str | None = None, city: str = "Ankara") -> OutOfCityUniversity:
    return OutOfCityUniversity(
        id=uuid.uuid4(),
        name=name,
        short_name=short_name,
        city=city,
    )


def test_alias_normalization_diacritic():
    macaka_id = uuid.uuid4()
    uni = _uni("İstanbul Teknik Üniversitesi - Maçka Kampüsü")
    aliases = [UniversityAlias(id=uuid.uuid4(), university_id=macaka_id, alias="taşkışla")]
    result = match_university("taşkışla", [uni], aliases)
    assert result.confidence == MatchConfidence.ALIAS
    assert result.university_id == macaka_id


def test_alias_normalization_stored_diacritic():
    macaka_id = uuid.uuid4()
    uni = _uni("İstanbul Teknik Üniversitesi - Maçka Kampüsü")
    aliases = [UniversityAlias(id=uuid.uuid4(), university_id=macaka_id, alias="taşkışla")]
    result = match_university("taskisla", [uni], aliases)
    assert result.confidence == MatchConfidence.ALIAS
    assert result.university_id == macaka_id


def test_beykent_ayazaga_diacritic_alias():
    campus_id = uuid.uuid4()
    uni = _uni("Beykent Üniversitesi - Ayazağa Kampüsü")
    aliases = [UniversityAlias(id=uuid.uuid4(), university_id=campus_id, alias="beykent ayazağa")]
    result = match_university("beykent ayazağa", [uni], aliases)
    assert result.confidence == MatchConfidence.ALIAS
    assert result.university_id == campus_id


def test_scan_entities_longest_first():
    itu = _uni("İstanbul Teknik Üniversitesi")
    istanbul = _uni("İstanbul Üniversitesi")
    result = scan_entities_by_ngram(
        "İstanbul Teknik Üniversitesi öğrencisiyim",
        [itu, istanbul],
        [],
    )
    assert result.confidence == MatchConfidence.EXACT
    assert result.university_id == itu.id


def test_should_match_campus_from_longer_message_via_ngram():
    parent_id = uuid.uuid4()
    goztepe_id = uuid.uuid4()
    parent_alias = UniversityAlias(
        id=uuid.uuid4(),
        parent_university_id=parent_id,
        alias="marmara",
    )
    campuses = [
        UniversityParentMap(
            university_id=goztepe_id,
            parent_university_id=parent_id,
            campus_label="Göztepe",
        ),
    ]
    matched = match_campus(
        "Marmara Üniversitesi Göztepe erkek öğrenci",
        parent_id,
        campuses,
        [parent_alias],
    )
    assert matched is not None
    assert matched.university_id == goztepe_id


def test_match_hotel_by_ngram_typo():
    hotel = Hotel(id=uuid.uuid4(), name="Academia Vadi", is_visible=True)
    matched = match_hotel_by_ngram("Academia Vadi yurt", [hotel])
    assert matched is not None
    assert matched.id == hotel.id


def test_word_count_after_normalize():
    assert word_count_after_normalize("  boğaziçi  ") == 1
    assert word_count_after_normalize("istanbul teknik") == 2


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


def test_normalize_strips_punctuation():
    assert normalize("İTÜ,") == "itu"
    assert normalize("a.b,c") == "a b c"


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


# ---------------------------------------------------------------------------
# Dynamic Levenshtein cutoff
# ---------------------------------------------------------------------------

def test_get_levenshtein_cutoff_boundaries():
    assert _get_levenshtein_cutoff("abc") == 0
    assert _get_levenshtein_cutoff("abcd") == 1
    assert _get_levenshtein_cutoff("abcde") == 1
    assert _get_levenshtein_cutoff("abcdef") == 2
    assert _get_levenshtein_cutoff("abcdefg") == 2
    assert _get_levenshtein_cutoff("abcdefgh") == 3


def test_match_out_of_city_exact_name():
    unis = [_ooc("Hacettepe Üniversitesi", short_name="HÜ")]
    matched = match_out_of_city("Hacettepe Üniversitesi", unis)
    assert matched is not None
    assert matched.name == "Hacettepe Üniversitesi"


def test_match_out_of_city_exact_short_name():
    unis = [_ooc("Orta Doğu Teknik Üniversitesi", short_name="ODTÜ")]
    matched = match_out_of_city("ODTÜ", unis)
    assert matched is not None
    assert matched.short_name == "ODTÜ"


def test_match_out_of_city_levenshtein_typo():
    unis = [_ooc("Hacettepe Üniversitesi", short_name="HÜ")]
    matched = match_out_of_city("Hasettepe Universitesi", unis)
    assert matched is not None
    assert matched.name == "Hacettepe Üniversitesi"


def test_match_out_of_city_short_input_no_fuzzy():
    unis = [_ooc("Hacettepe Üniversitesi", short_name="HÜ")]
    assert match_out_of_city("XYZ", unis) is None


def test_match_out_of_city_empty_input():
    unis = [_ooc("Hacettepe Üniversitesi")]
    assert match_out_of_city("", unis) is None
    assert match_out_of_city("   ", unis) is None


def test_match_out_of_city_closest_on_tie():
    unis = [
        _ooc("Anadolu Üniversitesi", city="Eskişehir"),
        _ooc("Anadol Üniversitesi", city="Eskişehir"),
    ]
    matched = match_out_of_city("anadolu", unis)
    assert matched is not None
    assert matched.name == "Anadolu Üniversitesi"


def test_tou_does_not_levenshtein_match_koc():
    koc_id = uuid.uuid4()
    unis = [_uni("Koç Üniversitesi", short_name="KU")]
    result = match_university("TÖÜ", unis, [])
    assert result.confidence == MatchConfidence.NONE, (
        "TÖÜ normalizes to 'tou' (3 chars); must not fuzzy-match Koç short name 'ku'"
    )


def test_short_valid_alias_ku_still_matches():
    koc_id = uuid.uuid4()
    unis = [University(id=koc_id, name="Koç Üniversitesi", university_short_name="KU")]
    aliases = [_alias(koc_id, "ku")]
    result = match_university("ku", unis, aliases)
    assert result.confidence in (MatchConfidence.EXACT, MatchConfidence.ALIAS)
    assert result.university_id == koc_id


def test_length_3_input_no_fuzzy_tier3():
    unis = [_uni("Boğaziçi Üniversitesi")]
    result = match_university("xyz", unis, [])
    assert result.confidence == MatchConfidence.NONE


# ---------------------------------------------------------------------------
# is_near_miss_university()
# ---------------------------------------------------------------------------

def test_should_return_true_when_input_is_one_edit_beyond_cutoff():
    unis = [_uni("Marmara Üniversitesi")]
    # "marmxxyy" is farther than accept cutoff but within NEAR_MISS_BAND of "marmara".
    assert is_near_miss_university("marmxxyy", unis) is True


def test_should_return_false_when_input_is_far_from_every_university():
    unis = [_uni("Boğaziçi Üniversitesi"), _uni("Marmara Üniversitesi")]
    assert is_near_miss_university("yeriniz nerde", unis) is False


def test_should_return_false_when_input_is_too_short():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert is_near_miss_university("bou", unis) is False


def test_should_return_false_when_input_is_an_exact_match():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert is_near_miss_university("Boğaziçi", unis) is False


def test_should_return_false_when_input_would_match_via_levenshtein_tier():
    unis = [_uni("Yıldız Teknik Üniversitesi")]
    # Within accept cutoff — match_university handles this; near-miss must not fire.
    result = match_university("Yıdız Teknik", unis, [])
    assert result.confidence == MatchConfidence.LEVENSHTEIN
    assert is_near_miss_university("Yıdız Teknik", unis) is False


def test_near_miss_constants_are_documented():
    assert NEAR_MISS_BAND == 2
    assert NEAR_MISS_MIN_LEN == 4
    assert ALIAS_FUZZY_MAX_DIST == 1
    assert ALIAS_FUZZY_MIN_LEN == 4


# ---------------------------------------------------------------------------
# is_question_form()
# ---------------------------------------------------------------------------

def test_should_flag_question_when_message_ends_with_question_mark():
    assert is_question_form("konum neresi?") is True


def test_should_flag_question_when_standalone_particle_present():
    assert is_question_form("sadece İstanbul mu") is True


@pytest.mark.parametrize("particle", ["mı", "mi", "mu", "mü"])
def test_should_flag_question_for_each_particle_variant(particle: str):
    assert is_question_form(f"sadece İstanbul {particle}") is True


def test_should_not_flag_plain_university_answer():
    assert is_question_form("İTÜ kız") is False
    assert is_question_form("Marmara Üniversitesi Göztepe") is False


def test_should_not_flag_when_particle_is_substring_not_token():
    assert is_question_form("Muğla Üniversitesi") is False


# ---------------------------------------------------------------------------
# match_university() — alias fuzzy (Tier 3.5)
# ---------------------------------------------------------------------------

def test_should_match_parent_when_input_is_one_edit_from_parent_alias():
    parent_id = uuid.uuid4()
    campus_unis = [
        _uni("Marmara Üniversitesi - Göztepe Kampüsü", "MÜ Göztepe"),
    ]
    aliases = [_parent_alias(parent_id, "marmara")]
    result = match_university("Marmaraa", campus_unis, aliases)
    assert result.confidence == MatchConfidence.ALIAS
    assert result.parent_university_id == parent_id


def test_should_not_alias_fuzzy_match_when_distance_exceeds_one():
    parent_id = uuid.uuid4()
    campus_unis = [_uni("Marmara Üniversitesi - Göztepe Kampüsü")]
    aliases = [_parent_alias(parent_id, "marmara")]
    result = match_university("Marmaraaa", campus_unis, aliases)
    assert result.confidence == MatchConfidence.NONE


def test_should_not_alias_fuzzy_match_short_alias():
    parent_id = uuid.uuid4()
    aliases = [_parent_alias(parent_id, "itu")]
    result = match_university("itr", [], aliases)
    assert result.confidence == MatchConfidence.NONE


def test_should_return_ambiguous_when_two_distinct_aliases_within_one_edit():
    parent_a = uuid.uuid4()
    parent_b = uuid.uuid4()
    aliases = [
        _parent_alias(parent_a, "testa"),
        _parent_alias(parent_b, "testb"),
    ]
    result = match_university("testc", [], aliases)
    assert result.confidence == MatchConfidence.AMBIGUOUS


def test_should_prefer_name_levenshtein_match_over_alias_fuzzy():
    parent_id = uuid.uuid4()
    uni_id = uuid.uuid4()
    unis = [University(id=uni_id, name="Yıldız Teknik Üniversitesi")]
    aliases = [_parent_alias(parent_id, "yildiz")]
    result = match_university("Yıdız Teknik", unis, aliases)
    assert result.confidence == MatchConfidence.LEVENSHTEIN
    assert result.university_id == uni_id
