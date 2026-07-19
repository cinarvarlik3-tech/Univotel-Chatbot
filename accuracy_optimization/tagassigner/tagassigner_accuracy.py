#!/usr/bin/env python3
"""
TagAssigner Accuracy Harness (spec 029).

Two modes:

  snapshot   — DB-touching, read-only. Dumps the objective end-state
               (LLM raw proposal + final written state) for a set of
               conversations into a sample_<round>.json. This is the ONLY
               mode that reads the database.

  calculate  — Pure function over (sample.json, feedback.json). Reconstructs
               gold by exception (final state + human flags), computes every
               metric defined in calculations.md, and writes a report to
               results/<dd-mm-yyyy>_<hh.mm>_<n>_tagassigner-accuracy.md.
               No DB, no network — same inputs give a byte-identical body.

Formulae: accuracy_optimization/tagassigner/calculations.md
Design:    docs/029_tagassigner_accuracy_optimization_spec.md
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
INPUTS_DIR = HERE / "inputs"
RESULTS_DIR = HERE / "results"

# ---------------------------------------------------------------------------
# Frozen label registry (mirrors app/tagassigner/label_resolver.py).
# Embedded literally so `calculate` has ZERO app/DB dependency. The test
# `test_accuracy_harness.py::test_registry_in_sync` asserts these equal the
# live label_resolver sets, catching drift.
# ---------------------------------------------------------------------------

_LIST_1_USABLE = frozenset({
    "pre-sinav", "hazırlık", "1-sinif", "2-sinif", "3-sinif", "4-sinif",
    "universitede", "yerlesti", "yeni-giris", "erasmus",
    "ogrenci", "veli", "ogrenci-degil",
    "kyk-sonuc-bekliyor", "ibb-yurdu-sonuc-bekliyor",
    "universite-yurdu-sonuc-bekliyor", "yatay_geçiş_bekliyor",
    "univotelli", "ilgilenmiyor", "info-check",
    "ziyaret", "ziyaret-etti", "ziyaret-etmedi",
    "hizmet-veremiyoruz",
})
_LIST_3_NEVER_TOUCH = frozenset({
    "google-ads", "google-maps", "meta-ads", "instagram",
    "whatsapp", "netgsm", "sahibinden", "manual",
    "aranacak", "arandi", "arandi-acmadi", "bizi-aradi-konustuk",
})
_HUMAN_TERMINAL = frozenset({"sozlesme-imzalandi", "kayıp", "ziyaret-ama-almayacak"})

INFO_CHECK = "info-check"
IDENTITY = frozenset({"ogrenci", "veli", "ogrenci-degil"})

LLM_OWNED = (_LIST_1_USABLE - {INFO_CHECK}) | {"kapora-alindi"}
ROUTER_OWNED = frozenset({"deal_awaiting", "fiyat-soruyor", INFO_CHECK})
NON_GRADED = _LIST_3_NEVER_TOUCH | _HUMAN_TERMINAL
GRADED = LLM_OWNED | ROUTER_OWNED

ATTRS = ("university", "gender", "oda_tiipi")
UNIVERSITY_CAMPUS_AMBIGUOUS = "bilinmiyor-kampus"

Z = 1.96  # 95%

VALID_KINDS = {"attr_wrong", "label_wrong_applied", "label_missing", "identity_wrong"}
VALID_IDENTITY_TARGETS = IDENTITY | {"none"}


# ---------------------------------------------------------------------------
# Field canonicalization (§0, §3, §4 of calculations.md)
# ---------------------------------------------------------------------------

def _canon(field_name: str, value: Optional[str]) -> str:
    """Canonical comparison token for a field value.

    University distinguishes its two withhold reasons (plain 'bilinmiyor' vs
    'bilinmiyor-kampus') because they are semantically different outcomes.
    Gender/room collapse to a single WITHHELD token.
    """
    v = (value or "").strip()
    low = v.lower()
    if field_name == "university":
        if low in ("", "boş", "bilinmiyor"):
            return "∅none"
        if low == "bilinmiyor-kampus":
            return "∅campus"
        return v  # exact canonical list value
    if field_name == "gender":
        if low == "erkek":
            return "Erkek"
        if low in ("kız", "kiz"):
            return "Kız"
        return "∅"
    if field_name == "oda_tiipi":
        if low in ("", "boş", "bos"):
            return "∅"
        return v
    raise ValueError(f"unknown field {field_name!r}")


def _is_withheld(field_name: str, value: Optional[str]) -> bool:
    return _canon(field_name, value).startswith("∅")


def _concrete(field_name: str, value: Optional[str]) -> bool:
    return not _is_withheld(field_name, value)


def _field_eq(field_name: str, a: Optional[str], b: Optional[str]) -> bool:
    return _canon(field_name, a) == _canon(field_name, b)


# ---------------------------------------------------------------------------
# Wilson score interval (§8)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def p(self) -> Optional[float]:
        return None if self.n == 0 else self.k / self.n

    def wilson(self) -> Optional[tuple[float, float]]:
        if self.n == 0:
            return None
        n = self.n
        phat = self.k / n
        denom = 1 + Z * Z / n
        center = (phat + Z * Z / (2 * n)) / denom
        half = (Z / denom) * math.sqrt(phat * (1 - phat) / n + Z * Z / (4 * n * n))
        return (max(0.0, center - half), min(1.0, center + half))

    def render(self) -> str:
        if self.n == 0:
            return "n/a (n=0)"
        lo, hi = self.wilson()  # type: ignore[misc]
        return f"{self.p * 100:.1f}% [{lo * 100:.1f}–{hi * 100:.1f}] (n={self.k}/{self.n})"


# ---------------------------------------------------------------------------
# Parsed inputs
# ---------------------------------------------------------------------------

@dataclass
class ConvSnapshot:
    cw_id: int
    lead_name: str
    llm: dict          # {labels, university, ogrenci_cinsiyet, oda_tiipi, university_mention}
    final: dict        # {labels, university, gender, oda_tiipi}


@dataclass
class Flag:
    cw_id: int
    kind: str
    target: Optional[str]
    correct_value: Optional[str]
    stateable: Optional[bool]
    layer: Optional[str]
    note: str


@dataclass
class GoldConv:
    cw_id: int
    lead_name: str
    llm: dict
    final: dict
    gold_labels: set
    gold_attrs: dict          # field -> gold value
    stateable_override: dict  # field -> bool


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Loading & validation (§4.3)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationError(f"file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValidationError(f"malformed JSON in {path}: {e}")


def load_sample(path: Path) -> tuple[str, list[ConvSnapshot]]:
    data = _load_json(path)
    round_id = data.get("round_id")
    if not isinstance(round_id, str) or not round_id:
        raise ValidationError("sample: missing/invalid 'round_id'")
    convs: list[ConvSnapshot] = []
    seen: set[int] = set()
    for i, row in enumerate(data.get("conversations", [])):
        cw = row.get("cw_id")
        if not isinstance(cw, int):
            raise ValidationError(f"sample.conversations[{i}]: missing int 'cw_id'")
        if cw in seen:
            raise ValidationError(f"sample: duplicate cw_id {cw}")
        seen.add(cw)
        llm = row.get("llm_raw") or {}
        final = row.get("final") or {}
        for key, src in (("labels", llm), ("labels", final)):
            if not isinstance(src.get("labels", []), list):
                raise ValidationError(f"sample cw={cw}: '{key}' must be a list")
        convs.append(ConvSnapshot(
            cw_id=cw,
            lead_name=str(row.get("lead_name", "")),
            llm={
                "labels": [str(x) for x in llm.get("labels", [])],
                "university": llm.get("university", "bilinmiyor"),
                "gender": llm.get("ogrenci_cinsiyet", "bilinmiyor"),
                "oda_tiipi": llm.get("oda_tiipi", "boş"),
                "university_mention": llm.get("university_mention"),
            },
            final={
                "labels": [str(x) for x in final.get("labels", [])],
                "university": final.get("university", "bilinmiyor"),
                "gender": final.get("gender", "Bilinmiyor"),
                "oda_tiipi": final.get("oda_tiipi", "boş"),
            },
        ))
    if not convs:
        raise ValidationError("sample: no conversations")
    return round_id, convs


def load_feedback(path: Path) -> tuple[str, list[Flag]]:
    data = _load_json(path)
    round_id = data.get("round_id")
    if not isinstance(round_id, str) or not round_id:
        raise ValidationError("feedback: missing/invalid 'round_id'")
    flags: list[Flag] = []
    for i, row in enumerate(data.get("flags", [])):
        cw = row.get("cw_id")
        kind = row.get("kind")
        if not isinstance(cw, int):
            raise ValidationError(f"feedback.flags[{i}]: missing int 'cw_id'")
        if kind not in VALID_KINDS:
            raise ValidationError(f"feedback.flags[{i}] cw={cw}: unknown kind {kind!r}")
        flags.append(Flag(
            cw_id=cw,
            kind=kind,
            target=row.get("target"),
            correct_value=row.get("correct_value"),
            stateable=row.get("stateable"),
            layer=row.get("layer"),
            note=str(row.get("note", "")),
        ))
    return round_id, flags


def _validate_flags(flags: list[Flag], by_cw: dict[int, ConvSnapshot]) -> None:
    errs: list[str] = []
    for f in flags:
        if f.cw_id not in by_cw:
            errs.append(f"flag cw={f.cw_id}: not in sample")
            continue
        if f.kind == "attr_wrong":
            if f.target not in ATTRS:
                errs.append(f"cw={f.cw_id}: attr_wrong bad target {f.target!r}")
            if f.correct_value is None:
                errs.append(f"cw={f.cw_id}: attr_wrong needs correct_value")
            elif f.target == "gender" and _canon("gender", f.correct_value) == "∅" \
                    and (f.correct_value or "").strip().lower() not in ("bilinmiyor",):
                errs.append(f"cw={f.cw_id}: gender correct_value {f.correct_value!r} invalid")
        elif f.kind in ("label_wrong_applied", "label_missing"):
            if f.target not in GRADED:
                errs.append(f"cw={f.cw_id}: {f.kind} target {f.target!r} not a graded label")
        elif f.kind == "identity_wrong":
            if f.correct_value not in VALID_IDENTITY_TARGETS:
                errs.append(f"cw={f.cw_id}: identity_wrong bad correct_value {f.correct_value!r}")
    if errs:
        raise ValidationError("input validation failed:\n  - " + "\n  - ".join(errs))


# ---------------------------------------------------------------------------
# Gold reconstruction (§2)
# ---------------------------------------------------------------------------

def build_gold(convs: list[ConvSnapshot], flags: list[Flag]) -> list[GoldConv]:
    by_cw = {c.cw_id: c for c in convs}
    _validate_flags(flags, by_cw)

    flags_by_cw: dict[int, list[Flag]] = {}
    for f in flags:
        flags_by_cw.setdefault(f.cw_id, []).append(f)

    out: list[GoldConv] = []
    for c in convs:
        gold_labels = set(c.final["labels"])
        gold_attrs = {f: c.final[f] for f in ATTRS}
        stateable_override: dict[str, bool] = {}

        for fl in flags_by_cw.get(c.cw_id, []):
            if fl.kind == "attr_wrong":
                gold_attrs[fl.target] = fl.correct_value
                if fl.stateable is not None:
                    stateable_override[fl.target] = fl.stateable
            elif fl.kind == "label_wrong_applied":
                gold_labels.discard(fl.target)
            elif fl.kind == "label_missing":
                gold_labels.add(fl.target)
            elif fl.kind == "identity_wrong":
                gold_labels -= IDENTITY
                if fl.correct_value != "none":
                    gold_labels.add(fl.correct_value)

        out.append(GoldConv(
            cw_id=c.cw_id, lead_name=c.lead_name, llm=c.llm, final=c.final,
            gold_labels=gold_labels, gold_attrs=gold_attrs,
            stateable_override=stateable_override,
        ))
    return out


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _must_call(g: GoldConv, f: str) -> bool:
    if f in g.stateable_override:
        return g.stateable_override[f]
    return _concrete(f, g.gold_attrs[f])


def _attr_layer_value(g: GoldConv, f: str, layer: str) -> str:
    return g.llm[f] if layer == "llm" else g.final[f]


def attribute_metrics(golds: list[GoldConv], f: str, layer: str) -> dict:
    must = [g for g in golds if _must_call(g, f)]
    a1 = Rate(sum(_concrete(f, _attr_layer_value(g, f, layer)) for g in must), len(must))

    decided = [g for g in golds if _concrete(f, _attr_layer_value(g, f, layer))]
    a2 = Rate(sum(_field_eq(f, _attr_layer_value(g, f, layer), g.gold_attrs[f]) for g in decided),
              len(decided))

    a3 = Rate(sum(_field_eq(f, _attr_layer_value(g, f, layer), g.gold_attrs[f]) for g in golds),
              len(golds))

    withheld = [g for g in golds if _is_withheld(f, _attr_layer_value(g, f, layer))]
    a4 = Rate(sum(_is_withheld(f, g.gold_attrs[f]) for g in withheld), len(withheld))

    return {"A1": a1, "A2": a2, "A3": a3, "A4": a4}


def attribution_counts(golds: list[GoldConv], f: str) -> dict:
    """A5 — deterministic layer attribution over (llm, fin, gold)."""
    tags = {"both_correct": 0, "router_rescued": 0, "router_broke": 0, "llm_error": 0}
    for g in golds:
        llm_ok = _field_eq(f, g.llm[f], g.gold_attrs[f])
        fin_ok = _field_eq(f, g.final[f], g.gold_attrs[f])
        if fin_ok:
            tags["both_correct"] += 1
            if not llm_ok:
                tags["router_rescued"] += 1
        elif llm_ok:
            tags["router_broke"] += 1
        else:
            tags["llm_error"] += 1
    return tags


def identity_metrics(golds: list[GoldConv]) -> dict:
    def called(g):
        s = IDENTITY & set(g.final["labels"])
        return next(iter(s)) if s else "none"

    def goldid(g):
        s = IDENTITY & g.gold_labels
        return next(iter(s)) if s else "none"

    det = [g for g in golds if goldid(g) != "none"]
    b1 = Rate(sum(called(g) != "none" for g in det), len(det))
    cset = [g for g in golds if called(g) != "none"]
    b2 = Rate(sum(called(g) == goldid(g) for g in cset), len(cset))
    b3 = Rate(sum(called(g) == goldid(g) for g in det), len(det))

    order = ["ogrenci", "veli", "ogrenci-degil", "none"]
    matrix = {gi: {ca: 0 for ca in order} for gi in order}
    for g in golds:
        matrix[goldid(g)][called(g)] += 1

    return {"B1": b1, "B2": b2, "B3": b3, "matrix": matrix, "order": order}


def label_confusion(golds: list[GoldConv], bucket: frozenset) -> dict:
    per = {}
    for lbl in sorted(bucket):
        tp = fp = fn = 0
        for g in golds:
            pred = lbl in set(g.final["labels"])
            truth = lbl in g.gold_labels
            if pred and truth:
                tp += 1
            elif pred and not truth:
                fp += 1
            elif not pred and truth:
                fn += 1
        if tp or fp or fn:
            per[lbl] = {"tp": tp, "fp": fp, "fn": fn}
    sum_tp = sum(v["tp"] for v in per.values())
    sum_fp = sum(v["fp"] for v in per.values())
    sum_fn = sum(v["fn"] for v in per.values())
    return {"per": per, "sum_tp": sum_tp, "sum_fp": sum_fp, "sum_fn": sum_fn}


def label_attribution(golds: list[GoldConv], bucket: frozenset) -> dict:
    """Per-label-decision layer attribution, same rule as attributes."""
    tags = {"both_correct": 0, "router_rescued": 0, "router_broke": 0, "llm_error": 0}
    router_owned = bucket == ROUTER_OWNED
    for g in golds:
        for lbl in bucket:
            truth = lbl in g.gold_labels
            fin_pred = lbl in set(g.final["labels"])
            fin_ok = fin_pred == truth
            if router_owned:
                # LLM never proposes these; any error is Router's.
                if fin_ok:
                    tags["both_correct"] += 1
                else:
                    tags["router_broke"] += 1
                continue
            llm_pred = lbl in set(g.llm["labels"])
            llm_ok = llm_pred == truth
            if fin_ok:
                tags["both_correct"] += 1
                if not llm_ok:
                    tags["router_rescued"] += 1
            elif llm_ok:
                tags["router_broke"] += 1
            else:
                tags["llm_error"] += 1
    return tags


def preservation_violations(golds: list[GoldConv]) -> list[tuple[int, str]]:
    out = []
    for g in golds:
        fin = set(g.final["labels"])
        for lbl in NON_GRADED:
            if (lbl in fin) != (lbl in g.gold_labels):
                out.append((g.cw_id, lbl))
    return out


def run_correctness(golds: list[GoldConv]) -> Rate:
    ok = 0
    for g in golds:
        attrs_ok = all(_field_eq(f, g.final[f], g.gold_attrs[f]) for f in ATTRS)
        fin = set(g.final["labels"])
        labels_ok = all((lbl in fin) == (lbl in g.gold_labels) for lbl in GRADED)
        if attrs_ok and labels_ok:
            ok += 1
    return Rate(ok, len(golds))


def _micro_f1(conf: dict) -> Optional[float]:
    tp, fp, fn = conf["sum_tp"], conf["sum_fp"], conf["sum_fn"]
    if tp + fp == 0 or tp + fn == 0:
        return None
    p = tp / (tp + fp)
    r = tp / (tp + fn)
    return None if p + r == 0 else 2 * p * r / (p + r)


# ---------------------------------------------------------------------------
# Report rendering (§8.4)
# ---------------------------------------------------------------------------

def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render_report(round_id: str, golds: list[GoldConv]) -> str:
    n = len(golds)
    L = []
    now = datetime.now(timezone.utc)
    L.append("# TagAssigner Accuracy Report")
    L.append("")
    L.append(f"- **Round:** `{round_id}`")
    L.append(f"- **Sample size (n):** {n}")
    L.append(f"- **Generated:** {now.isoformat(timespec='seconds')}")
    L.append(f"- **Conversations:** {', '.join(f'{g.cw_id}({g.lead_name})' for g in golds)}")
    L.append("")
    L.append("> ⚠ **Recall caveat:** ground truth is by exception (unflagged = correct). "
             "Missing-label recall (C3, identity B3) is an **observed upper bound on accuracy** "
             "— humans notice wrong labels far more reliably than absent ones. Every rate shows a "
             "Wilson 95% CI; treat wide intervals as inconclusive.")
    L.append("")

    # Headline
    d3 = run_correctness(golds)
    llm_conf = label_confusion(golds, LLM_OWNED)
    router_conf = label_confusion(golds, ROUTER_OWNED)
    attr_a3 = {f: attribute_metrics(golds, f, "fin")["A3"] for f in ATTRS}
    d1_vals = [attr_a3[f].p for f in ATTRS if attr_a3[f].p is not None]
    d1 = sum(d1_vals) / len(d1_vals) if d1_vals else None

    L.append("## Headline")
    L.append("")
    L.append(f"- **Run correctness (D3, all fields exact):** {d3.render()}")
    L.append(f"- **General attribute correctness (D1, mean A3):** {_pct(d1)}")
    L.append(f"- **General label correctness (D2):** LLM-owned micro-F1 "
             f"{_pct(_micro_f1(llm_conf))} · Router-owned micro-F1 {_pct(_micro_f1(router_conf))}")
    L.append("")

    # Attribute sections
    layer_rescued = 0
    layer_broke = 0
    layer_llm = 0
    for f in ("university", "gender"):
        L.append(f"## {f.capitalize()}")
        L.append("")
        L.append("| Metric | LLM layer | Final (Router) layer |")
        L.append("|---|---|---|")
        m_llm = attribute_metrics(golds, f, "llm")
        m_fin = attribute_metrics(golds, f, "fin")
        L.append(f"| A1 Decision rate (coverage) | {m_llm['A1'].render()} | {m_fin['A1'].render()} |")
        L.append(f"| A2 Correct-given-decision | {m_llm['A2'].render()} | {m_fin['A2'].render()} |")
        L.append(f"| A3 Correct-write (headline) | {m_llm['A3'].render()} | {m_fin['A3'].render()} |")
        L.append(f"| A4 Withhold-correctness | {m_llm['A4'].render()} | {m_fin['A4'].render()} |")
        L.append("")
        att = attribution_counts(golds, f)
        L.append(f"- **A5 Layer delta:** rescued {att['router_rescued']} · "
                 f"broke {att['router_broke']} · llm_error {att['llm_error']} · "
                 f"both_correct {att['both_correct']}"
                 + ("  ⚠ **Router regression**" if att["router_broke"] else ""))
        L.append("")
        layer_rescued += att["router_rescued"]
        layer_broke += att["router_broke"]
        layer_llm += att["llm_error"]

    # Room type (final only)
    L.append("## Room type (oda_tiipi)")
    L.append("")
    m = attribute_metrics(golds, "oda_tiipi", "fin")
    L.append(f"- A1 Decision rate: {m['A1'].render()}")
    L.append(f"- A2 Correct-given-decision: {m['A2'].render()}")
    L.append(f"- A3 Correct-write: {m['A3'].render()}")
    L.append(f"- A4 Withhold-correctness: {m['A4'].render()}")
    L.append("")

    # Identity
    idm = identity_metrics(golds)
    L.append("## Identity (student / parent / neither) — LLM layer")
    L.append("")
    L.append(f"- **B1 Decision rate** (calls made when determinable): {idm['B1'].render()}")
    L.append(f"- **B2 Precision-given-call**: {idm['B2'].render()}")
    L.append(f"- **B3 Recall** (correct call over determinable): {idm['B3'].render()}")
    L.append("")
    L.append("Confusion (rows = gold, cols = called):")
    L.append("")
    order = idm["order"]
    L.append("| gold ↓ / called → | " + " | ".join(order) + " |")
    L.append("|---|" + "|".join(["---"] * len(order)) + "|")
    for gi in order:
        L.append(f"| {gi} | " + " | ".join(str(idm['matrix'][gi][ca]) for ca in order) + " |")
    L.append("")

    # Label confusion
    for name, conf, bucket in (("LLM-owned", llm_conf, LLM_OWNED),
                               ("Router-owned", router_conf, ROUTER_OWNED)):
        L.append(f"## Labels — {name}")
        L.append("")
        c2 = Rate(conf["sum_fp"], conf["sum_tp"] + conf["sum_fp"])
        c3 = Rate(conf["sum_fn"], conf["sum_tp"] + conf["sum_fn"])
        L.append(f"- **C2 Wrong-labels-applied:** {c2.render()}")
        L.append(f"- **C3 Missing-correct-labels:** {c3.render()}  _(observed upper bound)_")
        L.append("")
        if conf["per"]:
            L.append("| Label | TP | FP | FN | Precision | Recall | F1 | share of errors |")
            L.append("|---|---|---|---|---|---|---|---|")
            tot_err = sum(v["fp"] + v["fn"] for v in conf["per"].values()) or 1
            for lbl, v in sorted(conf["per"].items(), key=lambda kv: -(kv[1]["fp"] + kv[1]["fn"])):
                p = v["tp"] / (v["tp"] + v["fp"]) if (v["tp"] + v["fp"]) else None
                r = v["tp"] / (v["tp"] + v["fn"]) if (v["tp"] + v["fn"]) else None
                f1 = (2 * p * r / (p + r)) if (p and r) else None
                share = (v["fp"] + v["fn"]) / tot_err
                L.append(f"| {lbl} | {v['tp']} | {v['fp']} | {v['fn']} | "
                         f"{_pct(p)} | {_pct(r)} | {_pct(f1)} | {share * 100:.0f}% |")
        else:
            L.append("_No decisions with any TP/FP/FN in this bucket._")
        L.append("")

    # Integrity
    viol = preservation_violations(golds)
    L.append("## Preservation integrity (C5)")
    L.append("")
    if viol:
        L.append(f"⚠ **{len(viol)} violation(s)** — carried-through/terminal labels altered:")
        for cw, lbl in viol:
            L.append(f"  - cw {cw}: `{lbl}`")
    else:
        L.append("✅ No violations — all never-touch / terminal labels preserved.")
    L.append("")

    # Layer summary
    L.append("## Layer summary")
    L.append("")
    L.append(f"- Aggregated attribute Router effect: rescued **{layer_rescued}**, "
             f"broke **{layer_broke}**, LLM-origin errors **{layer_llm}**.")
    lab_llm_attr = label_attribution(golds, LLM_OWNED)
    lab_router_attr = label_attribution(golds, ROUTER_OWNED)
    L.append(f"- LLM-owned label decisions: llm_error **{lab_llm_attr['llm_error']}**, "
             f"router_broke **{lab_llm_attr['router_broke']}**, rescued **{lab_llm_attr['router_rescued']}**.")
    L.append(f"- Router-owned label errors (all Router): **{lab_router_attr['router_broke']}**.")
    L.append("")

    # Appendix audit
    L.append("## Appendix — per-conversation audit (llm / final / gold)")
    L.append("")
    L.append("| cw | lead | field | llm | final | gold | ✓ |")
    L.append("|---|---|---|---|---|---|---|")
    for g in golds:
        for f in ATTRS:
            ok = "✓" if _field_eq(f, g.final[f], g.gold_attrs[f]) else "✗"
            L.append(f"| {g.cw_id} | {g.lead_name} | {f} | "
                     f"{g.llm[f]} | {g.final[f]} | {g.gold_attrs[f]} | {ok} |")
        fin_lbls = ",".join(sorted(set(g.final["labels"]) & GRADED)) or "—"
        gold_lbls = ",".join(sorted(g.gold_labels & GRADED)) or "—"
        lok = "✓" if (set(g.final["labels"]) & GRADED) == (g.gold_labels & GRADED) else "✗"
        L.append(f"| {g.cw_id} | {g.lead_name} | labels(graded) | — | {fin_lbls} | {gold_lbls} | {lok} |")
    L.append("")
    L.append(f"_Registry: LLM-owned={len(LLM_OWNED)} labels, Router-owned={len(ROUTER_OWNED)}, "
             f"non-graded={len(NON_GRADED)}. Formulae: calculations.md._")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI — calculate
# ---------------------------------------------------------------------------

def cmd_calculate(args) -> int:
    try:
        s_round, convs = load_sample(Path(args.sample))
        f_round, flags = load_feedback(Path(args.feedback))
        if s_round != f_round:
            raise ValidationError(f"round_id mismatch: sample={s_round!r} feedback={f_round!r}")
        golds = build_gold(convs, flags)
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    body = render_report(s_round, golds)
    if args.emit_stdout_only:
        print(body)
        return 0

    now = datetime.now()
    fname = f"{now.strftime('%d-%m-%Y')}_{now.strftime('%H.%M')}_{len(golds)}_tagassigner-accuracy.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / fname
    out.write_text(body, encoding="utf-8")

    # Headline to stdout
    d3 = run_correctness(golds)
    print(f"Wrote {out}")
    print(f"Run correctness (D3): {d3.render()}")
    return 0


# ---------------------------------------------------------------------------
# CLI — snapshot (the only DB-touching path; imports app.* lazily)
# ---------------------------------------------------------------------------

def cmd_snapshot(args) -> int:
    import asyncio
    import logging

    # Quiet the app's DEBUG HTTP/DB chatter — this is an interactive CLI.
    for noisy in ("httpx", "httpcore", "asyncio", "app.db.client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cw_ids = [int(x) for x in str(args.cw).replace(" ", "").split(",") if x]
    round_id = args.round or datetime.now().strftime("%Y-%m-%d-%H%M")

    async def _run() -> dict:
        from app.db.client import create_pool, close_pool, get_pool
        from app.db import queries
        from app.chatwoot_client import get_labels
        from app.tagassigner.attribute_helpers import gender_enum_to_display

        await create_pool()
        try:
            pool = get_pool()
            conversations = []
            for cw in cw_ids:
                conv_row = await pool.fetchrow(
                    "SELECT * FROM conversations WHERE chatwoot_conversation_id=$1", cw
                )
                if not conv_row:
                    print(f"WARN: cw {cw} not found in conversations — skipping", file=sys.stderr)
                    continue
                conv = dict(conv_row)
                run_row = await pool.fetchrow(
                    """
                    SELECT gemini_result FROM tag_assigner_runs
                    WHERE conversation_id=$1 AND status='success'
                    ORDER BY completed_at DESC LIMIT 1
                    """,
                    conv["id"],
                )
                gr = {}
                if run_row and run_row["gemini_result"]:
                    gr = run_row["gemini_result"]
                    if isinstance(gr, str):
                        gr = json.loads(gr)
                attrs = gr.get("attributes", {}) if isinstance(gr, dict) else {}

                uni_display = "bilinmiyor"
                if conv.get("university_id"):
                    uni_display = await queries.get_chatwoot_list_value_for_university(
                        conv["university_id"]
                    ) or "bilinmiyor"

                # Final LABELS live on Chatwoot, NOT in conversations.labels — the
                # Router writes labels via set_labels() and never mirrors them to
                # the DB column (which stays empty/stale). Attributes ARE
                # DB-authoritative (Router writes conversations + Chatwoot), so
                # those come from the row above.
                final_labels = await get_labels(conv["chatwoot_conversation_id"])
                if final_labels is None:
                    print(f"WARN: cw {cw}: could not fetch Chatwoot labels — using []",
                          file=sys.stderr)
                    final_labels = []

                conversations.append({
                    "cw_id": cw,
                    "lead_name": args_lead_name(args, cw),
                    "llm_raw": {
                        "labels": (gr.get("labels") if isinstance(gr, dict) else []) or [],
                        "university": attrs.get("university", "bilinmiyor"),
                        "ogrenci_cinsiyet": attrs.get("ogrenci_cinsiyet", "bilinmiyor"),
                        "oda_tiipi": attrs.get("oda_tiipi", "boş"),
                        "university_mention": gr.get("university_mention") if isinstance(gr, dict) else None,
                    },
                    "final": {
                        "labels": final_labels,
                        "university": uni_display,
                        "gender": gender_enum_to_display(conv.get("gender")),
                        "oda_tiipi": conv.get("oda_tiipi") or "boş",
                    },
                })
            return {
                "round_id": round_id,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "conversations": conversations,
            }
        finally:
            await close_pool()

    sample = asyncio.run(_run())
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = INPUTS_DIR / f"sample_{round_id}.json"
    out.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(sample['conversations'])} conversations)")
    print("Next: create a feedback file, then run `calculate`. "
          "Blank feedback template:")
    print(f'  {{"round_id": "{round_id}", "flags": [], "converter_notes": []}}')
    return 0


def args_lead_name(args, cw: int) -> str:
    """Lead names aren't stored on `conversations`; the developer may pass a
    cw:name map via --names 'cw=Name,cw=Name'. Falls back to the cw id."""
    if not getattr(args, "names", None):
        return str(cw)
    for pair in args.names.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip().isdigit() and int(k) == cw:
                return v.strip()
    return str(cw)


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="TagAssigner accuracy harness (spec 029)")
    sub = p.add_subparsers(dest="mode", required=True)

    ps = sub.add_parser("snapshot", help="DB → sample_<round>.json (read-only)")
    ps.add_argument("--cw", required=True, help="comma-separated chatwoot conversation ids")
    ps.add_argument("--round", help="round id (default: timestamp)")
    ps.add_argument("--names", help="optional cw=Name,cw=Name map for readable reports")
    ps.set_defaults(func=cmd_snapshot)

    pc = sub.add_parser("calculate", help="(sample, feedback) JSON → results report")
    pc.add_argument("--sample", required=True)
    pc.add_argument("--feedback", required=True)
    pc.add_argument("--emit-stdout-only", action="store_true",
                    help="print report body, do not write a file (for tests/diffs)")
    pc.set_defaults(func=cmd_calculate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
