"""Unit tests for app/tagassigner/label_resolver.py.

All tests are pure (no I/O, no DB, no mocks).
"""
import pytest

from app.tagassigner.label_resolver import (
    LIST_1_USABLE,
    LIST_2_TERMINAL,
    LIST_3_NEVER_TOUCH,
    resolve_labels,
    remove_tag_trigger_label,
    strip_gemini_deal_awaiting,
    strip_llm_fiyat_soruyor,
)


def test_fiyat_soruyor_is_not_list1_router_owned_since_spec_027():
    """fiyat-soruyor moved to full Router ownership (app.tagassigner.fiyat_soruyor)."""
    assert "fiyat-soruyor" not in LIST_1_USABLE


def test_resolve_labels_passes_fiyat_soruyor_through_untouched():
    """resolve_labels no longer manages fiyat-soruyor; compute_fiyat_soruyor does, downstream."""
    result = resolve_labels(["fiyat-soruyor", "ogrenci"], ["ogrenci"])
    assert "fiyat-soruyor" in result  # untouched passthrough, not List-1 removal


def test_strip_llm_fiyat_soruyor_removes_llm_proposal():
    assert strip_llm_fiyat_soruyor(["fiyat-soruyor", "ogrenci"]) == ["ogrenci"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sorted(labels):
    return sorted(labels)


# ---------------------------------------------------------------------------
# List-3 stripping — never-touch labels must be ignored in proposed
# ---------------------------------------------------------------------------

def test_list3_stripped_from_proposed():
    before = []
    proposed = ["ogrenci", "google-ads"]  # google-ads is List-3
    result = resolve_labels(before, proposed)
    assert "google-ads" not in result
    assert "ogrenci" in result


def test_list3_preserved_in_before():
    """Labels in before that are List-3 must not be removed."""
    before = ["google-ads", "ogrenci"]
    proposed = ["ogrenci"]  # google-ads absent from proposed — but it's List-3, must stay
    result = resolve_labels(before, proposed)
    assert "google-ads" in result


def test_list3_untouched_even_if_proposed_adds_it():
    """If Gemini somehow proposes a List-3 label, it is stripped."""
    before = []
    proposed = ["aranacak"]
    result = resolve_labels(before, proposed)
    assert "aranacak" not in result


# ---------------------------------------------------------------------------
# List-2 terminal hard-guard — additions allowed, removals blocked
# ---------------------------------------------------------------------------

def test_terminal_not_removed_from_before():
    before = ["kapora-alindi", "ogrenci"]
    proposed = ["ogrenci"]  # Gemini omits kapora-alindi
    result = resolve_labels(before, proposed)
    assert "kapora-alindi" in result


def test_terminal_added_when_proposed():
    before = ["ogrenci"]
    proposed = ["ogrenci", "sozlesme-imzalandi"]
    result = resolve_labels(before, proposed)
    assert "sozlesme-imzalandi" in result


def test_terminal_absent_from_before_stays_absent_if_not_proposed():
    before = ["ogrenci"]
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    for t in LIST_2_TERMINAL:
        assert t not in result


def test_all_terminals_preserved():
    before = list(LIST_2_TERMINAL) + ["ogrenci"]
    proposed = ["1-sinif"]  # Gemini removes all terminals
    result = resolve_labels(before, proposed)
    for t in LIST_2_TERMINAL:
        assert t in result


# ---------------------------------------------------------------------------
# List-1 merge — Gemini absence = removal, Gemini presence = addition
# ---------------------------------------------------------------------------

def test_list1_label_removed_when_gemini_omits():
    before = ["univotelli", "ogrenci"]
    proposed = ["ogrenci"]  # no univotelli
    result = resolve_labels(before, proposed)
    assert "univotelli" not in result


def test_list1_label_added_when_gemini_proposes():
    before = ["ogrenci"]
    proposed = ["ogrenci", "ziyaret"]
    result = resolve_labels(before, proposed)
    assert "ziyaret" in result


def test_unknown_label_in_before_is_preserved():
    """Labels unknown to any list (e.g., a custom Chatwoot tag) must survive."""
    before = ["custom-crm-tag", "ogrenci"]
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    assert "custom-crm-tag" in result


# ---------------------------------------------------------------------------
# List-4 mutex — academic year (forward progression)
# ---------------------------------------------------------------------------

def test_academic_year_keeps_most_advanced():
    before = []
    proposed = ["1-sinif", "3-sinif", "pre-sinav"]
    result = resolve_labels(before, proposed)
    assert "3-sinif" in result
    assert "1-sinif" not in result
    assert "pre-sinav" not in result


def test_academic_year_single_label_unchanged():
    before = []
    proposed = ["2-sinif", "ogrenci"]
    result = resolve_labels(before, proposed)
    assert "2-sinif" in result


def test_academic_year_universitede_wins():
    before = []
    proposed = ["hazırlık", "universitede"]
    result = resolve_labels(before, proposed)
    assert "universitede" in result
    assert "hazırlık" not in result


# ---------------------------------------------------------------------------
# List-4 mutex — contact identity (one only)
# ---------------------------------------------------------------------------

def test_contact_identity_keeps_existing():
    before = ["veli"]
    proposed = ["veli", "ogrenci"]  # both proposed — before-winner is veli
    result = resolve_labels(before, proposed)
    assert "veli" in result
    assert "ogrenci" not in result


def test_contact_identity_keeps_alpha_when_no_before():
    before = []
    proposed = ["veli", "ogrenci", "ogrenci-degil"]
    result = resolve_labels(before, proposed)
    # Only one must survive — whichever comes first alphabetically
    identity_in_result = [l for l in ["ogrenci", "ogrenci-degil", "veli"] if l in result]
    assert len(identity_in_result) == 1


def test_contact_identity_single_label_passes():
    before = []
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    assert "ogrenci" in result


# ---------------------------------------------------------------------------
# List-4 mutex — visit progression (branching levels)
# ---------------------------------------------------------------------------

def test_visit_drops_lower_level():
    before = []
    proposed = ["ziyaret", "ziyaret-etti"]  # ziyaret is level 0, ziyaret-etti is 1
    result = resolve_labels(before, proposed)
    assert "ziyaret-etti" in result
    assert "ziyaret" not in result


def test_visit_terminal_wins_all():
    before = []
    proposed = ["ziyaret", "ziyaret-etti", "ziyaret-ama-almayacak"]
    result = resolve_labels(before, proposed)
    assert "ziyaret-ama-almayacak" in result
    assert "ziyaret" not in result
    assert "ziyaret-etti" not in result


def test_visit_etti_and_etmedi_tie_prefers_before():
    before = ["ziyaret-etmedi"]
    proposed = ["ziyaret-etti", "ziyaret-etmedi"]
    result = resolve_labels(before, proposed)
    assert "ziyaret-etmedi" in result
    assert "ziyaret-etti" not in result


def test_visit_etti_and_etmedi_tie_no_before_uses_alpha():
    before = []
    proposed = ["ziyaret-etti", "ziyaret-etmedi"]
    result = resolve_labels(before, proposed)
    visit_level1 = [l for l in ["ziyaret-etti", "ziyaret-etmedi"] if l in result]
    assert len(visit_level1) == 1


# ---------------------------------------------------------------------------
# List-4 mutex — enrollment progression
# ---------------------------------------------------------------------------

def test_enrollment_keeps_most_advanced():
    before = []
    proposed = ["yerlesti", "yeni-giris"]
    result = resolve_labels(before, proposed)
    assert "yeni-giris" in result
    assert "yerlesti" not in result


# ---------------------------------------------------------------------------
# List-4 mutex — deal terminal (one only)
# ---------------------------------------------------------------------------

def test_deal_terminal_one_only_prefers_before():
    before = ["kayıp"]
    proposed = ["sozlesme-imzalandi", "kayıp"]
    result = resolve_labels(before, proposed)
    assert "kayıp" in result
    assert "sozlesme-imzalandi" not in result


# ---------------------------------------------------------------------------
# No-op when labels unchanged
# ---------------------------------------------------------------------------

def test_no_change_when_identical():
    before = ["ogrenci", "ziyaret"]
    proposed = ["ogrenci", "ziyaret"]
    result = resolve_labels(before, proposed)
    assert _sorted(result) == _sorted(before)


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------

def test_empty_before_and_proposed():
    result = resolve_labels([], [])
    assert result == []


def test_empty_before_proposed_adds():
    result = resolve_labels([], ["ogrenci"])
    assert "ogrenci" in result


def test_empty_proposed_clears_list1():
    before = ["ogrenci", "univotelli"]
    result = resolve_labels(before, [])
    # List-1 labels removed because Gemini proposed nothing
    assert "ogrenci" not in result
    assert "univotelli" not in result


def test_empty_proposed_preserves_terminal():
    before = ["kapora-alindi", "ogrenci"]
    result = resolve_labels(before, [])
    assert "kapora-alindi" in result


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------

def test_combined_full_pipeline():
    """Simulate a realistic post-visit close with all guards firing."""
    before = [
        "google-ads",        # List-3 — must stay
        "ogrenci",           # List-1 identity
        "kapora-alindi",     # List-2 terminal — must stay even if Gemini drops it
        "ziyaret",           # List-4 visit level 0
    ]
    proposed = [
        "google-ads",        # List-3 — stripped from proposed, but preserved from before
        "veli",              # identity conflict: Gemini proposes both veli AND ogrenci
        "ogrenci",           # both proposed → before-set winner (ogrenci) survives
        "sozlesme-imzalandi",# List-2 addition — allowed
        "ziyaret-etti",      # visit level 1, replaces ziyaret
        "1-sinif",
        "3-sinif",           # mutex — 3-sinif wins
    ]
    result = resolve_labels(before, proposed)

    assert "google-ads" in result         # List-3 preserved from before
    assert "ogrenci" in result            # before wins identity conflict (both were proposed)
    assert "veli" not in result
    assert "kapora-alindi" in result      # terminal hard-guard
    assert "sozlesme-imzalandi" in result # new terminal addition
    assert "ziyaret-etti" in result       # higher level wins
    assert "ziyaret" not in result
    assert "3-sinif" in result
    assert "1-sinif" not in result


# ---------------------------------------------------------------------------
# remove_tag_trigger_label
# ---------------------------------------------------------------------------

def test_remove_tag_trigger_label_present():
    assert "tag" not in remove_tag_trigger_label(["tag", "ogrenci"])


def test_remove_tag_trigger_label_absent():
    assert remove_tag_trigger_label(["ogrenci"]) == ["ogrenci"]


def test_remove_tag_trigger_label_empty():
    assert remove_tag_trigger_label([]) == []


def test_strip_gemini_deal_awaiting():
    assert strip_gemini_deal_awaiting(["ogrenci", "deal_awaiting"]) == ["ogrenci"]


def test_deal_awaiting_preserved_when_gemini_omits():
    before = ["deal_awaiting", "whatsapp"]
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    assert "deal_awaiting" in result
    assert "whatsapp" in result


def test_deal_awaiting_not_added_by_gemini_proposal():
    before = []
    proposed = ["deal_awaiting", "ogrenci"]
    result = resolve_labels(before, proposed)
    assert "deal_awaiting" not in result
    assert "ogrenci" in result


def test_should_allow_hizmet_veremiyoruz_as_assignable_list1_label():
    assert "hizmet-veremiyoruz" in LIST_1_USABLE


def test_should_add_hizmet_veremiyoruz_when_gemini_proposes():
    before = ["ogrenci"]
    proposed = ["ogrenci", "hizmet-veremiyoruz"]
    result = resolve_labels(before, proposed)
    assert "hizmet-veremiyoruz" in result


def test_should_remove_hizmet_veremiyoruz_when_gemini_omits_it():
    before = ["ogrenci", "hizmet-veremiyoruz"]
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    assert "hizmet-veremiyoruz" not in result
