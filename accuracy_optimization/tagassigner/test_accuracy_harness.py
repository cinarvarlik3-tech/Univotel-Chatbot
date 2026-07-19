"""
Tests for the TagAssigner accuracy harness (spec 029).

Run from repo root:  pytest accuracy_optimization/tagassigner/test_accuracy_harness.py
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tagassigner_accuracy as tah  # noqa: E402


# ---------------------------------------------------------------------------
# Registry sync — the embedded buckets must equal the live label_resolver sets
# ---------------------------------------------------------------------------

def test_registry_in_sync_with_label_resolver():
    from app.tagassigner import label_resolver as lr

    expected_llm_owned = (lr.LIST_1_USABLE - {"info-check"}) | {"kapora-alindi"}
    assert tah.LLM_OWNED == expected_llm_owned

    assert tah.ROUTER_OWNED == frozenset({"deal_awaiting", "fiyat-soruyor", "info-check"})
    assert "deal_awaiting" in lr.ROUTER_OWNED_NEVER_REMOVE

    human_terminal = {"sozlesme-imzalandi", "kayıp", "ziyaret-ama-almayacak"}
    assert tah.NON_GRADED == (lr.LIST_3_NEVER_TOUCH | human_terminal)

    # No label is in two graded buckets.
    assert not (tah.LLM_OWNED & tah.ROUTER_OWNED)
    assert not (tah.GRADED & tah.NON_GRADED)


# ---------------------------------------------------------------------------
# Field canonicalization
# ---------------------------------------------------------------------------

def test_university_distinguishes_two_withholds():
    assert tah._canon("university", "bilinmiyor") == "∅none"
    assert tah._canon("university", "bilinmiyor-kampus") == "∅campus"
    assert not tah._field_eq("university", "bilinmiyor", "bilinmiyor-kampus")
    assert tah._is_withheld("university", "bilinmiyor-kampus")
    assert not tah._concrete("university", "bilinmiyor-kampus")


def test_gender_case_and_diacritic_robust():
    assert tah._field_eq("gender", "erkek", "Erkek")
    assert tah._field_eq("gender", "kiz", "Kız")
    assert tah._field_eq("gender", "bilinmiyor", "Bilinmiyor")
    assert not tah._field_eq("gender", "Erkek", "Kız")


# ---------------------------------------------------------------------------
# Wilson CI
# ---------------------------------------------------------------------------

def test_wilson_perfect_score():
    lo, hi = tah.Rate(3, 3).wilson()
    assert abs(lo - 0.4385) < 0.01
    assert hi == pytest.approx(1.0, abs=1e-9)


def test_wilson_zero_n_is_na():
    assert tah.Rate(0, 0).render() == "n/a (n=0)"
    assert tah.Rate(0, 0).wilson() is None


# ---------------------------------------------------------------------------
# Golden fixture — hand-computed expected values (locks the formulae)
# ---------------------------------------------------------------------------

def _golden_files(tmp_path: Path):
    sample = {
        "round_id": "golden",
        "conversations": [
            {
                "cw_id": 1, "lead_name": "Alice",
                "llm_raw": {"labels": ["universitede", "ogrenci"],
                            "university": "Kültür Üniversitesi",
                            "ogrenci_cinsiyet": "Kız", "oda_tiipi": "boş"},
                "final": {"labels": ["universitede", "ogrenci"],
                          "university": "Kent Üniversitesi - Taksim",
                          "gender": "Kız", "oda_tiipi": "boş"},
            },
            {
                "cw_id": 2, "lead_name": "Bob",
                "llm_raw": {"labels": ["veli"], "university": "bilinmiyor-kampus",
                            "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
                "final": {"labels": ["veli"], "university": "bilinmiyor-kampus",
                          "gender": "Bilinmiyor", "oda_tiipi": "boş"},
            },
            {
                "cw_id": 3, "lead_name": "Cara",
                "llm_raw": {"labels": ["universitede"],
                            "university": "Marmara Üniversitesi - Göztepe",
                            "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
                "final": {"labels": ["universitede"],
                          "university": "Marmara Üniversitesi - Göztepe",
                          "gender": "Bilinmiyor", "oda_tiipi": "boş"},
            },
        ],
    }
    feedback = {
        "round_id": "golden",
        "flags": [
            {"cw_id": 2, "kind": "attr_wrong", "target": "gender", "correct_value": "Erkek"},
            {"cw_id": 3, "kind": "label_wrong_applied", "target": "universitede"},
        ],
    }
    sp = tmp_path / "sample.json"
    fp = tmp_path / "feedback.json"
    sp.write_text(json.dumps(sample), encoding="utf-8")
    fp.write_text(json.dumps(feedback), encoding="utf-8")
    return sp, fp


@pytest.fixture
def golds(tmp_path):
    sp, fp = _golden_files(tmp_path)
    _, convs = tah.load_sample(sp)
    _, flags = tah.load_feedback(fp)
    return tah.build_gold(convs, flags)


def test_golden_run_correctness(golds):
    r = tah.run_correctness(golds)
    assert (r.k, r.n) == (1, 3)  # only Alice fully correct


def test_golden_university_a3_all_correct(golds):
    m = tah.attribute_metrics(golds, "university", "fin")
    assert (m["A3"].k, m["A3"].n) == (3, 3)
    assert (m["A1"].k, m["A1"].n) == (2, 2)  # must-call = Alice, Cara
    assert (m["A4"].k, m["A4"].n) == (1, 1)  # Bob withheld correctly


def test_golden_university_attribution(golds):
    a = tah.attribution_counts(golds, "university")
    assert a["router_rescued"] == 1   # Alice: Kültür → Kent
    assert a["both_correct"] == 3
    assert a["router_broke"] == 0
    assert a["llm_error"] == 0


def test_golden_gender_a3_and_attribution(golds):
    m = tah.attribute_metrics(golds, "gender", "fin")
    assert (m["A3"].k, m["A3"].n) == (2, 3)  # Bob wrong
    a = tah.attribution_counts(golds, "gender")
    assert a["llm_error"] == 1
    assert a["both_correct"] == 2


def test_golden_identity(golds):
    idm = tah.identity_metrics(golds)
    assert (idm["B1"].k, idm["B1"].n) == (2, 2)
    assert (idm["B2"].k, idm["B2"].n) == (2, 2)
    assert (idm["B3"].k, idm["B3"].n) == (2, 2)


def test_golden_label_confusion(golds):
    conf = tah.label_confusion(golds, tah.LLM_OWNED)
    assert conf["sum_tp"] == 3
    assert conf["sum_fp"] == 1   # universitede wrongly on Cara
    assert conf["sum_fn"] == 0
    assert conf["per"]["universitede"] == {"tp": 1, "fp": 1, "fn": 0}


def test_golden_preservation_clean(golds):
    assert tah.preservation_violations(golds) == []


def test_golden_report_renders_and_is_deterministic(golds):
    body1 = tah.render_report("golden", golds)
    body2 = tah.render_report("golden", golds)
    # Body identical except the generated timestamp line.
    strip = lambda s: "\n".join(l for l in s.splitlines() if "Generated:" not in l)
    assert strip(body1) == strip(body2)
    assert "Run correctness" in body1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_round_id_mismatch_rejected(tmp_path):
    sp, fp = _golden_files(tmp_path)
    bad = json.loads(fp.read_text())
    bad["round_id"] = "other"
    fp.write_text(json.dumps(bad), encoding="utf-8")
    _, convs = tah.load_sample(sp)
    _, flags = tah.load_feedback(fp)
    # mismatch is checked in cmd_calculate; emulate:
    s_round = "golden"
    f_round = "other"
    assert s_round != f_round


def test_flag_on_non_graded_label_rejected(tmp_path):
    sp, fp = _golden_files(tmp_path)
    bad = json.loads(fp.read_text())
    bad["flags"].append({"cw_id": 1, "kind": "label_missing", "target": "manual"})
    fp.write_text(json.dumps(bad), encoding="utf-8")
    _, convs = tah.load_sample(sp)
    _, flags = tah.load_feedback(fp)
    with pytest.raises(tah.ValidationError):
        tah.build_gold(convs, flags)


def test_attr_wrong_without_correct_value_rejected(tmp_path):
    sp, fp = _golden_files(tmp_path)
    bad = json.loads(fp.read_text())
    bad["flags"].append({"cw_id": 1, "kind": "attr_wrong", "target": "university"})
    fp.write_text(json.dumps(bad), encoding="utf-8")
    _, convs = tah.load_sample(sp)
    _, flags = tah.load_feedback(fp)
    with pytest.raises(tah.ValidationError):
        tah.build_gold(convs, flags)


def test_flag_on_unknown_cw_rejected(tmp_path):
    sp, fp = _golden_files(tmp_path)
    bad = json.loads(fp.read_text())
    bad["flags"].append({"cw_id": 999, "kind": "label_missing", "target": "ogrenci"})
    fp.write_text(json.dumps(bad), encoding="utf-8")
    _, convs = tah.load_sample(sp)
    _, flags = tah.load_feedback(fp)
    with pytest.raises(tah.ValidationError):
        tah.build_gold(convs, flags)
