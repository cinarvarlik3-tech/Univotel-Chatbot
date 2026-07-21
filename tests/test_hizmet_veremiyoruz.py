"""
Unit tests for app/tagassigner/hizmet_veremiyoruz.py
(TAGASSIGNER_ACCURACY_FIXES_PLAN.md A2, amendments 1/2/3/6/9/10).
"""
import uuid

import pytest

from app.db.models import OutOfCityUniversity, University, UniversityParentMap
from app.tagassigner.hizmet_veremiyoruz import (
    HIZMET_VEREMIYORUZ_LABEL,
    build_out_of_city_index,
    compute_hizmet_veremiyoruz,
    scan_out_of_city,
    strip_llm_hizmet_veremiyoruz,
)
from app.tagassigner.university_canonicalizer import _build_universe

# İstanbul side: two campuses under DIFFERENT parents sharing the locality fragment
# "anadolu hisari" — mirrors the real Boğaziçi/Marmara Anadolu Hisarı collision.
BOGAZICI_ANADOLU_ID = uuid.uuid4()
MARMARA_ANADOLU_ID = uuid.uuid4()
BOGAZICI_PARENT_ID = uuid.uuid4()
MARMARA_PARENT_ID = uuid.uuid4()

# A second locality-sharing pair — "tip fakultesi" — shared by two DIFFERENT parents,
# used to prove locality masking is token-scoped, not text-scoped.
IU_TIP_ID = uuid.uuid4()
MARMARA_TIP_ID = uuid.uuid4()
IU_TIP_PARENT_ID = uuid.uuid4()
MARMARA_TIP_PARENT_ID = uuid.uuid4()


def _universe():
    universities = [
        University(
            id=BOGAZICI_ANADOLU_ID,
            name="Boğaziçi Üniversitesi - Anadolu Hisarı Kampüsü",
            university_short_name="BOUN",
        ),
        University(
            id=MARMARA_ANADOLU_ID,
            name="Marmara Üniversitesi - Anadolu Hisarı Kampüsü",
            university_short_name="MÜ",
        ),
        University(
            id=IU_TIP_ID,
            name="İstanbul Üniversitesi Tıp Fakültesi",
            university_short_name=None,
        ),
        University(
            id=MARMARA_TIP_ID,
            name="Marmara Üniversitesi Tıp Fakültesi",
            university_short_name=None,
        ),
    ]
    parent_map = [
        UniversityParentMap(
            university_id=BOGAZICI_ANADOLU_ID,
            parent_university_id=BOGAZICI_PARENT_ID,
            campus_label="Anadolu Hisarı Kampüsü",
        ),
        UniversityParentMap(
            university_id=MARMARA_ANADOLU_ID,
            parent_university_id=MARMARA_PARENT_ID,
            campus_label="Anadolu Hisarı Kampüsü",
        ),
        UniversityParentMap(
            university_id=IU_TIP_ID,
            parent_university_id=IU_TIP_PARENT_ID,
            campus_label="Tıp Fakültesi",
        ),
        UniversityParentMap(
            university_id=MARMARA_TIP_ID,
            parent_university_id=MARMARA_TIP_PARENT_ID,
            campus_label="Tıp Fakültesi",
        ),
    ]
    return _build_universe(universities, [], parent_map)


def _ooc() -> list[OutOfCityUniversity]:
    return [
        OutOfCityUniversity(id=uuid.uuid4(), name="Anadolu Üniversitesi", short_name="AÜ", city="Eskişehir"),
        OutOfCityUniversity(id=uuid.uuid4(), name="Hacettepe Üniversitesi", short_name="HÜ", city="Ankara"),
        OutOfCityUniversity(
            id=uuid.uuid4(), name="Eskişehir Osmangazi Üniversitesi", short_name="ESOGÜ", city="Eskişehir"
        ),
        OutOfCityUniversity(
            id=uuid.uuid4(), name="İzmir Tınaztepe Üniversitesi", short_name="İTÜNİ", city="İzmir"
        ),
        OutOfCityUniversity(id=uuid.uuid4(), name="Orta Doğu Teknik Üniversitesi", short_name="ODTÜ", city="Ankara"),
    ]


# ---------------------------------------------------------------------------
# strip_llm_hizmet_veremiyoruz
# ---------------------------------------------------------------------------

def test_strip_llm_hizmet_veremiyoruz():
    assert strip_llm_hizmet_veremiyoruz(["ogrenci", HIZMET_VEREMIYORUZ_LABEL]) == ["ogrenci"]


# ---------------------------------------------------------------------------
# scan_out_of_city — locality masking (amendment 6/10) is TOKEN-scoped
# ---------------------------------------------------------------------------

def test_locality_masks_bare_anadolu_hisari():
    """A bare 'Anadolu Hisarı' mention (no university named) must NOT resolve to the
    out-of-city Anadolu Üniversitesi — it's a shared İstanbul campus locality."""
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())
    assert scan_out_of_city("Anadolu Hisarında kalıyorum", _ooc(), index) is None


def test_anadolu_universitesi_still_resolves_out_of_city():
    """The locality mask must not cost the real out-of-city Anadolu Üniversitesi lead —
    only the bare campus-locality reading is suppressed."""
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())

    hit = scan_out_of_city("Anadolu Üniversitesi", _ooc(), index)
    assert hit is not None and hit.name == "Anadolu Üniversitesi"

    hit2 = scan_out_of_city("Anadolu üniversitesinde okuyorum", _ooc(), index)
    assert hit2 is not None and hit2.name == "Anadolu Üniversitesi"


def test_hacettepe_tip_fakultesi_still_resolves_out_of_city():
    """Token-scoped masking: 'tıp fakültesi' is ALSO a shared İstanbul locality fragment
    in this fixture, but it must only mask those two tokens — 'hacettepe' itself is
    untouched and must still resolve."""
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())
    hit = scan_out_of_city("Hacettepe Tıp Fakültesi", _ooc(), index)
    assert hit is not None and hit.name == "Hacettepe Üniversitesi"


def test_short_2gram_collapse_does_not_fuzzy_match():
    """'biruni universitesi' collapses to the single token 'biruni' once normalize()
    strips the trailing suffix word — must NOT fuzzy-match İzmir Tınaztepe's short_name
    'İTÜNİ' at Levenshtein distance 2 (real false positive found during design)."""
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())
    assert scan_out_of_city("biruni universitesi", _ooc(), index) is None


def test_odtu_short_name_resolves_via_1gram_exact():
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())
    hit = scan_out_of_city("ODTÜ de okuyorum", _ooc(), index)
    assert hit is not None and hit.name == "Orta Doğu Teknik Üniversitesi"


def test_short_common_word_never_matches_via_1gram():
    """'bu' exact-matches Bingöl's short_name 'BÜ' at length 2 — must be blocked by the
    length floor (condition b) even though it's an EXACT match (condition a alone is
    insufficient, per amendment 1)."""
    universe = _universe()
    ooc = _ooc() + [OutOfCityUniversity(id=uuid.uuid4(), name="Bingöl Üniversitesi", short_name="BÜ", city="Bingöl")]
    index = build_out_of_city_index(universe, ooc)
    assert scan_out_of_city("değil mi bu keten suites ile", ooc, index) is None


def test_eskisehir_osmangazi_two_gram_fuzzy_resolves():
    """cw652 shape: real acceptance case from TAGASSIGNER_ACCURACY_FIXES_PLAN.md."""
    universe = _universe()
    index = build_out_of_city_index(universe, _ooc())
    hit = scan_out_of_city(
        "Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum. Üniversitem: "
        "eskişehir Osmangazi Üniversitesi",
        _ooc(),
        index,
    )
    assert hit is not None and hit.name == "Eskişehir Osmangazi Üniversitesi"


# ---------------------------------------------------------------------------
# compute_hizmet_veremiyoruz — full add/remove decision
# ---------------------------------------------------------------------------

def test_compute_in_city_via_conv_university_id_strips_prior_label():
    """Router-authoritative (amendment 3): a human-added label on a conversation with a
    persisted in-city university_id is removed, regardless of the inbound phrase."""
    universe = _universe()
    result = compute_hizmet_veremiyoruz(
        "some ambiguous text", universe, _ooc(), uuid.uuid4(), [HIZMET_VEREMIYORUZ_LABEL]
    )
    assert HIZMET_VEREMIYORUZ_LABEL not in result


def test_compute_in_city_via_campus_canonicalize_suppresses():
    """İbrahim-shape (cw1359): an in-city CAMPUS resolution suppresses the label even
    with no persisted conv.university_id yet (blocked-merge survival, amendment 9)."""
    universe = _universe()
    result = compute_hizmet_veremiyoruz("Boğaziçi Anadolu Hisarı", universe, _ooc(), None, [])
    assert HIZMET_VEREMIYORUZ_LABEL not in result


def test_compute_out_of_city_applies():
    universe = _universe()
    result = compute_hizmet_veremiyoruz(
        "Eskişehir Osmangazi Üniversitesi", universe, _ooc(), None, ["ogrenci"]
    )
    assert HIZMET_VEREMIYORUZ_LABEL in result
    assert "ogrenci" in result


def test_compute_ambiguous_no_match_does_not_apply():
    """A failed/ambiguous lookup alone is not grounds for the label."""
    universe = _universe()
    result = compute_hizmet_veremiyoruz("merhaba nasılsınız", universe, _ooc(), None, [])
    assert HIZMET_VEREMIYORUZ_LABEL not in result


def test_compute_none_inbound_phrase_does_not_apply():
    universe = _universe()
    result = compute_hizmet_veremiyoruz(None, universe, _ooc(), None, [])
    assert HIZMET_VEREMIYORUZ_LABEL not in result


def test_compute_preserves_other_labels():
    universe = _universe()
    result = compute_hizmet_veremiyoruz(
        "Eskişehir Osmangazi Üniversitesi", universe, _ooc(), None, ["ogrenci", "universitede"]
    )
    assert set(result) == {"ogrenci", "universitede", HIZMET_VEREMIYORUZ_LABEL}
