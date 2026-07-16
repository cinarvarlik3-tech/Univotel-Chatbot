"""Unit tests for app/tagassigner/university_resolver.py."""
import uuid

from app.tagassigner.university_resolver import resolve_university_list_value

_UID_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_UID_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_UID_C = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

_CANONICAL = "Boğaziçi Üniversitesi"
_BEYKENT = "Beykent Üniversitesi - Ayazağa"


def _map(*pairs: tuple[uuid.UUID, str]) -> list[tuple[uuid.UUID, str]]:
    return list(pairs)


def test_should_match_exact_when_string_is_canonical():
    result = resolve_university_list_value(_CANONICAL, _map((_UID_A, _CANONICAL)))
    assert result.university_id == _UID_A
    assert result.matched_list_value == _CANONICAL
    assert result.method == "exact"


def test_should_match_when_only_diacritics_or_spacing_differ():
    proposed = "Bogazici Universitesi"
    result = resolve_university_list_value(proposed, _map((_UID_A, _CANONICAL)))
    assert result.university_id == _UID_A
    assert result.matched_list_value == _CANONICAL
    assert result.method == "normalized"


def test_should_match_when_single_edit_typo_and_unique():
    proposed = "Beykent Üniversitesi - Byazağa"
    result = resolve_university_list_value(proposed, _map((_UID_C, _BEYKENT)))
    assert result.university_id == _UID_C
    assert result.matched_list_value == _BEYKENT
    assert result.method == "levenshtein"


def test_should_return_none_when_two_candidates_tie_at_distance_one():
    label_map = _map(
        (_UID_A, "Xabc Üniversitesi"),
        (_UID_B, "Yabc Üniversitesi"),
    )
    result = resolve_university_list_value("Zabc Üniversitesi", label_map)
    assert result.university_id is None
    assert result.method == "ambiguous"


def test_should_return_none_when_no_candidate_within_distance_one():
    result = resolve_university_list_value(
        "Completely Unknown University",
        _map((_UID_A, _CANONICAL)),
    )
    assert result.university_id is None
    assert result.method == "none"


def test_should_return_none_when_proposed_is_bilinmiyor_sentinel():
    result = resolve_university_list_value("bilinmiyor", _map((_UID_A, _CANONICAL)))
    assert result.university_id is None
    assert result.method == "none"

    result = resolve_university_list_value("bilinmiyor-kampus", _map((_UID_A, _CANONICAL)))
    assert result.university_id is None
    assert result.method == "none"

    result = resolve_university_list_value("boş", _map((_UID_A, _CANONICAL)))
    assert result.university_id is None
    assert result.method == "none"

    result = resolve_university_list_value("   ", _map((_UID_A, _CANONICAL)))
    assert result.university_id is None
    assert result.method == "none"


def test_should_return_none_when_proposed_is_invented_university_string():
    result = resolve_university_list_value(
        "İstanbul Kültür Üniversitesi - Ataköy",
        _map((_UID_A, "Kültür Üniversitesi")),
    )
    assert result.university_id is None
    assert result.method == "none"


_CAPA_TIP = "Çapa Tıp Fakültesi"
_CAPA_UID = uuid.UUID("082e55c7-bc59-43dd-8235-c172d4275bb2")
_DOU_DUDULLU = "Doğuş Üniversitesi Dudullu"
_DOU_UID = uuid.UUID("5e053f91-8419-47e6-8ac2-d0ae7466ced4")


def test_should_resolve_capa_tip_fakultesi_exact():
    result = resolve_university_list_value(_CAPA_TIP, _map((_CAPA_UID, _CAPA_TIP)))
    assert result.university_id == _CAPA_UID
    assert result.matched_list_value == _CAPA_TIP
    assert result.method == "exact"


def test_should_resolve_dou_dudullu_with_normalized_spacing():
    proposed = "Dogus Universitesi Dudullu"
    result = resolve_university_list_value(proposed, _map((_DOU_UID, _DOU_DUDULLU)))
    assert result.university_id == _DOU_UID
    assert result.matched_list_value == _DOU_DUDULLU
    assert result.method == "normalized"
