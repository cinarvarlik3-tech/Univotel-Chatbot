"""
Unit tests for app/tagassigner/university_canonicalizer.py (spec 027, Mode C).

Fixture universe deliberately mirrors the shapes found in the live DB during
the spec-026/027 investigation: a bare parent alias ("istanbul" -> İÜ parent,
ambiguous with 2 campuses), single-campus parents resolved via short-name
n-gram matching (Atlas, Kültür), and a near-name pair (Kent vs Kültür) that
only token-containment disambiguates.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import University, UniversityAlias, UniversityParentMap
from app.tagassigner.university_canonicalizer import (
    CanonConfidence,
    canonicalize,
    get_university_universe,
    reset_universe_cache,
    resolve_university_override,
    token_containment,
    _build_universe,
)
from app.tagassigner.attribute_helpers import UNIVERSITY_CAMPUS_AMBIGUOUS

# ---------------------------------------------------------------------------
# Fixture universe
# ---------------------------------------------------------------------------

ATLAS_ID = uuid.uuid4()
KENT_ID = uuid.uuid4()
KULTUR_ID = uuid.uuid4()
CAPA_ID = uuid.uuid4()
CERRAHPASA_ID = uuid.uuid4()
BEYKENT_A_ID = uuid.uuid4()  # campus_label "Ayazağa"
BEYKENT_B_ID = uuid.uuid4()  # campus_label "Taksim"
SINGLE_PARENT_CAMPUS_ID = uuid.uuid4()

IU_PARENT_ID = uuid.uuid4()
BEYKENT_PARENT_ID = uuid.uuid4()
SINGLE_PARENT_ID = uuid.uuid4()
ATLAS_PARENT_ID = uuid.uuid4()
KENT_PARENT_ID = uuid.uuid4()
KULTUR_PARENT_ID = uuid.uuid4()


def _universities() -> list[University]:
    return [
        University(id=ATLAS_ID, name="Atlas Üniversitesi - Hamidiye Kampüsü", university_short_name="ATLAS"),
        University(id=KENT_ID, name="İstanbul Kent Üniversitesi Taksim Kampüsü", university_short_name="İKÜ"),
        University(id=KULTUR_ID, name="İstanbul Kültür Üniversitesi - Ataköy", university_short_name="KÜLTÜR"),
        University(id=CAPA_ID, name="İstanbul Üniversitesi İÜ - Çapa Tıp Fakültesi", university_short_name="ÇAPA"),
        University(id=CERRAHPASA_ID, name="İstanbul Üniversitesi İÜ - Cerrahpaşa Tıp Fakültesi", university_short_name="CERRAHPAŞA"),
        University(id=BEYKENT_A_ID, name="Beykent Üniversitesi - Kampüs A", university_short_name=None),
        University(id=BEYKENT_B_ID, name="Beykent Üniversitesi - Kampüs B", university_short_name=None),
        University(id=SINGLE_PARENT_CAMPUS_ID, name="Tek Kampüslü Üniversitesi - Ana Kampüs", university_short_name=None),
    ]


def _aliases() -> list[UniversityAlias]:
    return [
        UniversityAlias(id=uuid.uuid4(), alias="istanbul", university_id=None, parent_university_id=IU_PARENT_ID),
        UniversityAlias(id=uuid.uuid4(), alias="beykent", university_id=None, parent_university_id=BEYKENT_PARENT_ID),
        UniversityAlias(id=uuid.uuid4(), alias="single parent", university_id=None, parent_university_id=SINGLE_PARENT_ID),
    ]


def _parent_map() -> list[UniversityParentMap]:
    return [
        UniversityParentMap(university_id=ATLAS_ID, parent_university_id=ATLAS_PARENT_ID, campus_label="Atlas Üniversitesi - Hamidiye Kampüsü"),
        UniversityParentMap(university_id=KENT_ID, parent_university_id=KENT_PARENT_ID, campus_label="İstanbul Kent Üniversitesi Taksim Kampüsü"),
        UniversityParentMap(university_id=KULTUR_ID, parent_university_id=KULTUR_PARENT_ID, campus_label="İstanbul Kültür Üniversitesi - Ataköy"),
        UniversityParentMap(university_id=CAPA_ID, parent_university_id=IU_PARENT_ID, campus_label="Çapa Tıp Fakültesi"),
        UniversityParentMap(university_id=CERRAHPASA_ID, parent_university_id=IU_PARENT_ID, campus_label="Cerrahpaşa Tıp Fakültesi"),
        UniversityParentMap(university_id=BEYKENT_A_ID, parent_university_id=BEYKENT_PARENT_ID, campus_label="Ayazağa"),
        UniversityParentMap(university_id=BEYKENT_B_ID, parent_university_id=BEYKENT_PARENT_ID, campus_label="Taksim"),
        UniversityParentMap(university_id=SINGLE_PARENT_CAMPUS_ID, parent_university_id=SINGLE_PARENT_ID, campus_label="Tek Kampüslü Üniversitesi - Ana Kampüs"),
    ]


def _label_map() -> list[tuple[uuid.UUID, str]]:
    """(university_id, chatwoot_list_value) pairs, mirroring queries.get_university_chatwoot_label_map."""
    return [
        (ATLAS_ID, "Atlas Üniversitesi"),
        (KENT_ID, "Kent Üniversitesi - Taksim"),
        (KULTUR_ID, "Kültür Üniversitesi"),
        (CAPA_ID, "Çapa Tıp Fakültesi"),
        (CERRAHPASA_ID, "Cerrahpaşa Tıp Fakültesi"),
        (BEYKENT_A_ID, "Beykent Üniversitesi - Ayazağa"),
        (BEYKENT_B_ID, "Beykent Üniversitesi - Taksim"),
        (SINGLE_PARENT_CAMPUS_ID, "Tek Kampüslü Üniversitesi"),
    ]


@pytest.fixture
def universe():
    return _build_universe(_universities(), _aliases(), _parent_map())


# ---------------------------------------------------------------------------
# token_containment
# ---------------------------------------------------------------------------

def test_token_containment_resolves_near_name_confusion():
    """C2 regression: 'İstanbul kent üniversitesi' must resolve to Kent, not Kültür."""
    unis = _universities()
    result = token_containment("İstanbul kent üniversitesi", unis)
    assert result is not None
    assert result.id == KENT_ID


def test_token_containment_returns_none_on_bare_district():
    unis = _universities()
    assert token_containment("kadıköy", unis) is None
    assert token_containment("cevizlibağ", unis) is None
    assert token_containment("hamidiye", unis) is None


def test_token_containment_returns_none_on_faculty_only_phrase():
    unis = _universities()
    assert token_containment("tıp fakültesi", unis) is None


def test_token_containment_returns_none_on_no_significant_tokens():
    """Phrase reduces to zero tokens once faculty/structural stopwords are dropped."""
    unis = _universities()
    assert token_containment("fakültesi kampüsü", unis) is None


def test_token_containment_returns_none_when_ambiguous_across_many_universities():
    """A bare institution-type word ('üniversitesi') matches many -> ambiguous, not unique."""
    unis = _universities()
    assert token_containment("üniversitesi", unis) is None


def test_token_containment_does_not_confuse_beykent_substring_with_kent():
    """'kent' must not match inside 'beykent' — token equality, not substring."""
    unis = _universities()
    result = token_containment("beykent kampüs a", unis)
    assert result is not None
    assert result.id == BEYKENT_A_ID  # not KENT_ID


# ---------------------------------------------------------------------------
# canonicalize — precedence tiers
# ---------------------------------------------------------------------------

def test_c1_atlas_faculty_shorthand_resolves_via_ngram(universe):
    """C1 regression: 'Atlas tıp fakültesi' must resolve to Atlas, not bilinmiyor-kampus."""
    result = canonicalize("Atlas tıp fakültesi", universe)
    assert result.confidence == CanonConfidence.CAMPUS
    assert result.university_id == ATLAS_ID


def test_c2_kent_resolves_via_token_containment_tier(universe):
    result = canonicalize("İstanbul kent üniversitesi", universe)
    assert result.confidence == CanonConfidence.CAMPUS
    assert result.university_id == KENT_ID


def test_kultur_control_still_resolves_correctly(universe):
    """Kültür itself must still resolve correctly — the fix must not break the positive case."""
    result = canonicalize("kültür üniversitesi", universe)
    assert result.confidence == CanonConfidence.CAMPUS
    assert result.university_id == KULTUR_ID


def test_bare_parent_alias_with_ambiguous_campuses_yields_parent_only(universe):
    """Bare 'istanbul' -> İÜ parent with 2 campuses, neither resolvable -> bilinmiyor-kampus."""
    result = canonicalize("istanbul", universe)
    assert result.confidence == CanonConfidence.PARENT_ONLY
    assert result.university_id is None


def test_bare_parent_alias_with_single_campus_auto_resolves(universe):
    result = canonicalize("single parent", universe)
    assert result.confidence == CanonConfidence.CAMPUS
    assert result.university_id == SINGLE_PARENT_CAMPUS_ID


def test_parent_alias_plus_match_campus_resolves_specific_campus(universe):
    """Tier-3 inner path: parent alias hit, then match_campus disambiguates via campus_label."""
    result = canonicalize("beykent ayazağa", universe)
    assert result.confidence == CanonConfidence.CAMPUS
    assert result.university_id == BEYKENT_A_ID


def test_district_guard_returns_none(universe):
    for phrase in ("kadıköy", "cevizlibağ", "hamidiye"):
        result = canonicalize(phrase, universe)
        assert result.confidence == CanonConfidence.NONE, f"{phrase!r} should not resolve"
        assert result.university_id is None


def test_empty_phrase_returns_none(universe):
    for phrase in ("", "   ", None):
        result = canonicalize(phrase, universe)  # type: ignore[arg-type]
        assert result.confidence == CanonConfidence.NONE


def test_faculty_only_phrase_returns_none(universe):
    result = canonicalize("tıp fakültesi", universe)
    assert result.confidence == CanonConfidence.NONE


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_universe_cache_avoids_repeated_db_calls():
    reset_universe_cache()
    with patch(
        "app.db.queries.get_all_universities", new=AsyncMock(return_value=_universities())
    ) as mock_unis, patch(
        "app.db.queries.get_all_university_aliases", new=AsyncMock(return_value=_aliases())
    ) as mock_aliases, patch(
        "app.db.queries.get_all_university_parent_map", new=AsyncMock(return_value=_parent_map())
    ) as mock_parents:
        first = await get_university_universe()
        second = await get_university_universe()

        assert first is second  # same cached object, no reload
        mock_unis.assert_called_once()
        mock_aliases.assert_called_once()
        mock_parents.assert_called_once()
    reset_universe_cache()


@pytest.mark.asyncio
async def test_universe_cache_force_refresh_reloads():
    reset_universe_cache()
    with patch(
        "app.db.queries.get_all_universities", new=AsyncMock(return_value=_universities())
    ) as mock_unis, patch(
        "app.db.queries.get_all_university_aliases", new=AsyncMock(return_value=_aliases())
    ), patch(
        "app.db.queries.get_all_university_parent_map", new=AsyncMock(return_value=_parent_map())
    ):
        await get_university_universe()
        await get_university_universe(force_refresh=True)
        assert mock_unis.call_count == 2
    reset_universe_cache()


# ---------------------------------------------------------------------------
# resolve_university_override — the pure option-3 decision (code-review fixes)
# ---------------------------------------------------------------------------

def test_override_campus_confidence_replaces_wrong_belt_guess(universe):
    """C2 end-to-end: LLM belt wrongly guessed Kültür; mention correctly resolves to Kent."""
    result = resolve_university_override(
        proposed_uni="Kültür Üniversitesi",
        mention="İstanbul kent üniversitesi",
        label_map=_label_map(),
        universe=universe,
    )
    assert result == "Kent Üniversitesi - Taksim"


def test_override_parent_only_does_not_downgrade_confident_belt(universe):
    """
    Regression: a stale/ambiguous mention must NOT force bilinmiyor-kampus
    when the belt (LLM's own attributes.university) already resolves to a
    specific, valid campus.
    """
    result = resolve_university_override(
        proposed_uni="Atlas Üniversitesi",  # belt: specific, valid, resolvable
        mention="istanbul",  # mention: bare parent alias -> PARENT_ONLY
        label_map=_label_map(),
        universe=universe,
    )
    assert result == "Atlas Üniversitesi"  # unchanged — belt wins


def test_override_parent_only_forces_ambiguous_when_belt_also_unresolved(universe):
    result = resolve_university_override(
        proposed_uni="bilinmiyor",  # belt: nothing specific
        mention="istanbul",  # mention: ambiguous parent (2 campuses)
        label_map=_label_map(),
        universe=universe,
    )
    assert result == UNIVERSITY_CAMPUS_AMBIGUOUS


def test_override_falls_back_to_belt_text_when_mention_is_sentinel(universe):
    """
    Regression: when university_mention is an explicit sentinel ("bilinmiyor"),
    the override must still canonicalize off the belt's own text instead of
    skipping Mode C entirely — otherwise a hallucinated belt guess would never
    get double-checked.
    """
    result = resolve_university_override(
        proposed_uni="Atlas tıp fakültesi",  # belt text itself is canonicalizable
        mention="bilinmiyor",
        label_map=_label_map(),
        universe=universe,
    )
    assert result == "Atlas Üniversitesi"


def test_override_falls_back_to_belt_text_when_mention_is_absent(universe):
    result = resolve_university_override(
        proposed_uni="Atlas tıp fakültesi",
        mention=None,
        label_map=_label_map(),
        universe=universe,
    )
    assert result == "Atlas Üniversitesi"


def test_override_returns_belt_unchanged_when_no_signal_resolves(universe):
    result = resolve_university_override(
        proposed_uni="bilinmiyor",
        mention="kadıköy",  # district guard — no confident resolution
        label_map=_label_map(),
        universe=universe,
    )
    assert result == "bilinmiyor"


def test_override_ignores_missing_label_map_entry_and_falls_back_to_belt(universe):
    """If canonicalize resolves a campus with no Chatwoot label mapping, don't crash — fall back."""
    result = resolve_university_override(
        proposed_uni="bilinmiyor",
        mention="Atlas tıp fakültesi",
        label_map=[],  # no mapping for ATLAS_ID
        universe=universe,
    )
    assert result == "bilinmiyor"
