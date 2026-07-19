# TagAssigner Accuracy — Calculation Reference

This document is the **formula contract** for `tagassigner_accuracy.py`. Every metric
the script prints is defined here, in both plain English and formal notation. If the
script and this document ever disagree, that is a bug in one of them — the golden-fixture
test (`test_accuracy_harness.py`) exists to keep them in lock-step.

Spec of record: `docs/029_tagassigner_accuracy_optimization_spec.md`.

---

## 0. Symbols & data model

Each graded conversation `c` contributes three views of each field:

| Symbol | Meaning | Source |
|---|---|---|
| `llm(c, f)` | the LLM's raw proposal for field `f` | `sample.json → conversations[].llm_raw` (from `tag_assigner_runs.gemini_result`) |
| `fin(c, f)` | the final written value for field `f` | `sample.json → conversations[].final` (from `conversations` table) |
| `gold(c, f)` | the correct value for field `f` | `fin(c, f)` mutated by `feedback.json` flags (§2) |

Fields:
- Attributes: `university`, `gender`, `oda_tiipi`.
- Labels: the multiset is treated as a set of independent binary decisions, one per
  `(conversation, label)` pair, within a **bucket** (§1).

**Withhold sentinels** (a field is "withheld" when its value is one of these):

| Field | Withhold sentinels |
|---|---|
| university | `bilinmiyor`, `bilinmiyor-kampus`, `boş`, `""` |
| gender | `Bilinmiyor`, `bilinmiyor`, `""` |
| oda_tiipi | `boş`, `""` |

`concrete(v)` ≔ `v` is not a withhold sentinel for its field.

---

## 1. Label buckets (frozen registry, mirrored from `label_resolver.py`)

| Bucket `B` | Members | Graded | Layer |
|---|---|---|---|
| `LLM_OWNED` | `LIST_1_USABLE − {info-check} ∪ {kapora-alindi}` | yes | LLM |
| `ROUTER_OWNED` | `{deal_awaiting, fiyat-soruyor, info-check}` | yes | Router |
| `NON_GRADED` | `LIST_3_NEVER_TOUCH ∪ {sozlesme-imzalandi, kayıp, ziyaret-ama-almayacak}` | no (integrity only) | — |

`IDENTITY ≔ {ogrenci, veli, ogrenci-degil}` ⊂ `LLM_OWNED` gets its own block (§5).

Only labels in a graded bucket enter the confusion matrices. A `feedback` flag targeting a
`NON_GRADED` label is a validation error.

---

## 2. Gold reconstruction

For each conversation `c`, starting from `fin(c)`:

**Attributes.** For each `attr_wrong` flag `(c, f, v)`:
```
gold(c, f) = v
```
For every unflagged attribute: `gold(c, f) = fin(c, f)`.

**Labels.** Let `A = set(fin(c).labels)`. Apply flags:
```
gold(c).labels = ( A  −  { ℓ : label_wrong_applied(c, ℓ) }
                      −  { the removed member for identity_wrong }        )
                 ∪  { ℓ : label_missing(c, ℓ) }
                 ∪  { the added member for identity_wrong }
```
`identity_wrong(c, correct)` desugars to: remove whichever identity label is in `A`
(if any) and, if `correct ≠ none`, add `correct`.

Unflagged ⇒ assumed correct (the exception rule).

---

## 3. Stateability (per attribute, per conversation)

Derived from `gold`, unless a flag carries an explicit `stateable` override.

| Class | Condition on `gold(c, f)` | Meaning |
|---|---|---|
| `MUST_CALL(c,f)` | `concrete(gold(c,f))` | system is expected to produce a concrete value |
| `WITHHOLD_OK(c,f)` | `f = university ∧ gold = bilinmiyor-kampus` | institution known, campus correctly withheld |
| `NOT_STATEABLE(c,f)` | otherwise (gold is a withhold sentinel) | nothing to state; withholding is correct |

`GRADEABLE(f) ≔ MUST_CALL ∪ WITHHOLD_OK ∪ NOT_STATEABLE` = all graded conversations for `f`
(every conversation in the sample is gradeable for every attribute).

---

## 4. Attribute metrics (computed at layer `L ∈ {llm, fin}`; write `val_L = llm(c,f)` or `fin(c,f)`)

Let `S = MUST_CALL(·, f)` (the "must make a call" set).

**A1 — Decision rate (coverage).**
> Of the conversations where the system must produce a value, how often did it produce one?
```
A1(f, L) = |{ c ∈ S : concrete(val_L(c,f)) }|  /  |S|
```

**A2 — Correctness-given-decision (precision).**
> Of the conversations where the system produced a value, how often was it right?
```
Dset = { c ∈ GRADEABLE(f) : concrete(val_L(c,f)) }
A2(f, L) = |{ c ∈ Dset : val_L(c,f) = gold(c,f) }|  /  |Dset|
```

**A3 — Correct-write rate (headline; final layer is the reported one).**
> Over all gradeable conversations, how often is the written value exactly right —
> counting a correct withhold as correct?
```
A3(f, L) = |{ c ∈ GRADEABLE(f) : val_L(c,f) = gold(c,f) }|  /  |GRADEABLE(f)|
```
(Equality uses the field's canonical form; both `val` and `gold` are already canonical
list values / display strings / sentinels, so this is exact string equality.)

**A4 — Withhold-correctness (over-withholding guard).**
> When the system withheld, how often was withholding the correct thing to do?
```
Wset = { c ∈ GRADEABLE(f) : ¬concrete(val_L(c,f)) }
A4(f, L) = |{ c ∈ Wset : ¬concrete(gold(c,f)) }|  /  |Wset|
```
For university, a withheld `bilinmiyor-kampus` is correct iff `gold` is also
`bilinmiyor-kampus` **or** any withhold (the campus was genuinely undeterminable). The
script compares withhold-*class* membership, not exact sentinel, for A4.

**A5 — Layer delta (attribution counts, university & gender).**
Per conversation in `GRADEABLE(f)`, classify with `llm(c,f)`, `fin(c,f)`, `gold(c,f)`:

| llm=gold | fin=gold | tag |
|---|---|---|
| — | ✓ | `both_correct` (and `router_rescued` if llm≠gold) |
| ✓ | ✗ | `router_broke` |
| ✗ | ✗ | `llm_error` |

A5 reports the four counts. `router_rescued` and `router_broke` are the net-Router-effect
signal; `router_broke > 0` is a regression alarm.

Room type reports A1–A4 at the final layer only (Router does not override it).

---

## 5. Identity metric (LLM layer)

Let `called(c) = the identity label in fin(c).labels` (or `none`);
`goldid(c) = the identity label in gold(c).labels` (or `none`).
`Det = { c : goldid(c) ≠ none }` (identity determinable).

**B1 — Decision rate.** `|{ c ∈ Det : called(c) ≠ none }| / |Det|`
**B2 — Precision-given-call.** `Cset = { c : called(c) ≠ none }`; `|{ c ∈ Cset : called(c) = goldid(c) }| / |Cset|`
**B3 — Recall.** `|{ c ∈ Det : called(c) = goldid(c) }| / |Det|`
**B4 — Confusion matrix.** 4×4 counts over `goldid × called` (`ogrenci, veli, ogrenci-degil, none`).

---

## 6. Label confusion matrix (per graded bucket `B`)

Over every `(c, ℓ)` with `ℓ ∈ B`, using `fin(c).labels` (predicted) vs `gold(c).labels`:

```
TP(ℓ) = |{ c : ℓ ∈ fin(c) ∧ ℓ ∈ gold(c) }|
FP(ℓ) = |{ c : ℓ ∈ fin(c) ∧ ℓ ∉ gold(c) }|
FN(ℓ) = |{ c : ℓ ∉ fin(c) ∧ ℓ ∈ gold(c) }|
```

**C1 — per-label & roll-ups.**
```
precision(ℓ) = TP / (TP + FP)          recall(ℓ) = TP / (TP + FN)
F1(ℓ)        = 2·P·R / (P + R)
micro_P(B)   = ΣTP / (ΣTP + ΣFP)   (macro = mean of per-label, over labels with support)
```
**C2 — Wrong-labels-applied rate** = `ΣFP / (ΣTP + ΣFP)` (= 1 − micro precision).
**C3 — Missing-correct-labels rate** = `ΣFN / (ΣTP + ΣFN)` (= 1 − micro recall).
  ⚠ Upper-bound: under exception grading, `FN` only counts labels the human *noticed*
  were missing. Report C3 as "observed ≥ true" — it understates missing-label error.
**C4 — Error distribution by label** = for each `ℓ`, `(FP(ℓ)+FN(ℓ)) / Σ_ℓ(FP+FN)` within `B`.
  Reported separately for `LLM_OWNED` and `ROUTER_OWNED` so error → layer is unambiguous.

**C5 — Preservation integrity (NON_GRADED bucket).**
```
violations = |{ (c, ℓ) : ℓ ∈ NON_GRADED ∧ (ℓ ∈ fin(c)) ≠ (ℓ ∈ gold(c)) }|
```
A count, not a rate. Must be 0; any nonzero is a hard bug flag.

---

## 7. Roll-ups

**D1 — General attribute correctness** = mean over `f ∈ {university, gender, oda_tiipi}` of `A3(f, fin)` (equal-weighted; per-field values also shown).

**D2 — General label correctness** = `micro_F1(LLM_OWNED)` (primary), with `micro_F1(ROUTER_OWNED)` shown alongside — never blended.
```
micro_F1(B) = 2·micro_P(B)·micro_R(B) / (micro_P(B) + micro_R(B))
```

**D3 — General run correctness (headline).**
> Fraction of conversations where every graded field is exactly right.
```
correct_run(c) ⟺ ( ∀ f ∈ attrs: fin(c,f) = gold(c,f) )
                ∧ ( ∀ ℓ ∈ (LLM_OWNED ∪ ROUTER_OWNED): (ℓ∈fin(c)) = (ℓ∈gold(c)) )
D3 = |{ c : correct_run(c) }| / |all conversations|
```

---

## 8. Confidence interval (Wilson score, 95%, z = 1.96)

For `k` successes in `n` trials, `p̂ = k/n`:
```
center = (p̂ + z²/2n) / (1 + z²/n)
half   = ( z / (1 + z²/n) ) · √( p̂(1−p̂)/n + z²/4n² )
CI     = [center − half, center + half]   (clamped to [0, 1])
```
`n = 0 ⇒ render "n/a (n=0)"` — never a bare 0% or 100%. Every rate in every report is
rendered as `NN.N% [lo–hi] (n=k/N)`.

---

## 9. What is deliberately NOT computed here

- Input/transcript-layer error *rates* — not derivable from `(llm, fin, gold)`. Surfaced
  only as a verbatim list when the developer explicitly flags a data-gap (`layer:"input"`).
- True (vs observed) missing-label recall — impossible under exception grading; C3 is the
  honest observable proxy, labeled as an upper bound on accuracy.
- Any cross-run trend — each report is standalone.
