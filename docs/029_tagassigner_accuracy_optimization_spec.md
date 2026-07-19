# Spec 029 — TagAssigner Accuracy Optimization Harness

**Status:** Ready for implementation — plan only, no code written yet
**Date:** 2026-07-16
**Author decisions:** All design calls in this spec were made under full delegated authority for the `accuracy_optimization/` addition only. Scope is strictly this harness — no changes to `app/`, prompts, or runtime behavior.
**Audience:** Engineer building the harness. Self-contained.

---

## 0. Purpose

Give the developer a **cheap, reliable, reproducible** way to measure TagAssigner accuracy, sliced two ways at once:

1. **By area** — university, gender, identity (student/parent), labels, room type.
2. **By layer** — LLM (proposal) vs Router (deterministic post-processing) vs input/transcript.

For every area/layer the harness answers the developer's two core questions:

- **Coverage ("decision rate")** — *when the system must make a call, how often does it make one?*
- **Correctness-given-decision** — *among the calls it made, how often is it right?*

…plus the headline **overall correct-write rate** (which counts correct *withholds* as correct) and **run correctness** (all-or-nothing per conversation).

The design goal that overrides all others: **the only human input required is a plain-English list of observed errors.** Everything else is machine-derived and reproducible.

---

## 1. The decisions (the calls I made)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Exception-based ground truth.** Unflagged = correct. Gold = observed end-state with flagged errors corrected. | The developer only eyeballs Chatwoot end-states. This is the cheapest ground truth that exists. |
| D2 | **Two-stage input: an objective `sample` snapshot + a subjective `feedback` file.** The converter LLM produces only `feedback`; the objective snapshot is machine-generated. | Keeps the fallible LLM away from objective data. The human/LLM only ever touches the error list. |
| D3 | **Snapshot captures BOTH the LLM raw proposal (`gemini_result`) and the final written state, per field.** | This two-stage capture is the *sole enabler* of layer attribution — without it, Router vs LLM errors are indistinguishable (spec 028.1 conversation, problem #3). |
| D4 | **Layer attribution is derived deterministically** from (LLM-raw, final-written, gold), not annotated by the human. | Humans see only end-states; layer blame is a mechanical function of the three values. |
| D5 | **Correct withholds count as correct** in write-accuracy, and are tracked as a distinct outcome (not as "made a call"). | `bilinmiyor-kampus`, `bilinmiyor`, and "no identity label" are behaviors the system was built to do. A metric that ignores this rewards hallucination. |
| D6 | **Precision is always paired with recall** for identity and labels. | Exception grading + a withhold-biased prompt makes precision-only numbers misleading. |
| D7 | **Model-owned, Router-owned, and carried-through labels are graded in separate buckets**, from a static registry mirrored from `label_resolver.py`. | An error's layer determines which subsystem to fix; blending them misroutes work. |
| D8 | **Every rate emits n + a Wilson 95% confidence interval; empty denominators render `n/a`, never 0% or 100%.** | Small-n noise must not read as signal. Wilson is stable near 0/1 and needs no dependencies. |
| D9 | **The `calculate` step is a pure function over JSON — no DB, fully deterministic.** The `snapshot` step is the only DB-touching, side-effecting part. | Honors "deterministic calc from provided JSON" while still avoiding hand-transcription of objective data. |
| D10 | **Report filename uses `dd-mm-yyyy` (hyphens), not `dd/mm/yyyy`.** | Slashes are path separators — the requested format is an illegal filename. |
| D11 | **Recall-side metrics carry a standing "observed upper-bound" caveat** in every report. | Humans catch *wrong* labels far more reliably than *missing* ones; missing-label recall is structurally optimistic. |

---

## 2. Folder structure & deliverables

```
accuracy_optimization/
└── tagassigner/
    ├── opt_protocol.md            # instructs the on-duty LLM: human English → feedback.json
    ├── calculations.md            # every metric as math + plain English
    ├── tagassigner_accuracy.py    # the deterministic script (snapshot + calculate modes)
    ├── inputs/                     # sample_*.json + feedback_*.json live here (my addition, D2)
    │   └── .gitkeep
    └── results/                   # script writes report .md files here
        └── .gitkeep
```

The `inputs/` subfolder is my addition (not in the original ask) to keep grading artifacts out of `results/`; it is where both the machine snapshot and the converter's feedback file are stored per grading round.

Report output path:
`accuracy_optimization/tagassigner/results/<dd-mm-yyyy>_<hh.mm>_<n>_tagassigner-accuracy.md`
where `<n>` is the sample size (int).

---

## 3. Ground-truth model (exception-based)

Per grading round:

1. Developer runs a sweep, then reads the graded conversations' **end-states on Chatwoot** and writes a plain-English error list: *lead name + field/label + what's wrong + (if known) the correct value.*
2. The **on-duty LLM** (governed by `opt_protocol.md`) converts that list into `feedback_<round>.json` — **only the flags**, nothing objective.
3. The **script's `snapshot` mode** produces `sample_<round>.json` — the objective end-state + LLM-raw for the exact conversations in scope, pulled from the DB.
4. **Gold** is reconstructed by the `calculate` step: start from each conversation's final written state, apply the flags (fix attributes, remove wrongly-applied labels, add missing labels). Any field/label not flagged is assumed correct as written.

**Consequence, stated plainly in every report:** the metric is the developer's *observed* error rate. It is exact for wrong-value errors and an **upper bound on accuracy** for missing-label errors (D11).

---

## 4. Input JSON schemas

### 4.1 `sample_<round>.json` (machine-generated by `snapshot` mode — objective, never hand-edited)

```json
{
  "round_id": "2026-07-16-a",
  "generated_at": "2026-07-16T16:45:00Z",
  "conversations": [
    {
      "cw_id": 448,
      "lead_name": "Ömer",
      "llm_raw": {
        "labels": ["universitede"],
        "university": "Cerrahpaşa Tıp Fakültesi",
        "ogrenci_cinsiyet": "bilinmiyor",
        "oda_tiipi": "boş",
        "university_mention": null
      },
      "final": {
        "labels": ["universitede"],
        "university": "Cerrahpaşa Tıp Fakültesi",
        "gender": "Bilinmiyor",
        "oda_tiipi": "boş"
      }
    }
  ]
}
```

Field sourcing (all deterministic):
- `llm_raw.*` ← latest `status='success'` `tag_assigner_runs.gemini_result` for the conversation.
- `final.labels` ← `conversations.labels`.
- `final.university` ← `conversations.university_id` → `university_chatwoot_label_map.chatwoot_list_value` (or `"bilinmiyor"` when null; `"bilinmiyor-kampus"` is stored as-is if that's the written display — see §6.3).
- `final.gender` ← `conversations.gender` normalized to `Erkek`/`Kız`/`Bilinmiyor` via `gender_enum_to_display`.
- `final.oda_tiipi` ← `conversations.oda_tiipi` (or `"boş"`).

### 4.2 `feedback_<round>.json` (produced by the converter LLM — subjective, flags only)

```json
{
  "round_id": "2026-07-16-a",
  "flags": [
    {
      "cw_id": 665,
      "lead_name": "Mehmet",
      "kind": "label_wrong_applied",
      "target": "universitede",
      "note": "prospective student — said 'bu yıl üniversiteye gireceğim', not enrolled yet"
    },
    {
      "cw_id": 1164,
      "lead_name": "Hawi",
      "kind": "attr_wrong",
      "target": "gender",
      "correct_value": "Erkek",
      "note": "veli looking for his son → student gender is male"
    }
  ]
}
```

**`kind` enum (the only shapes the converter may emit):**

| `kind` | `target` | `correct_value` | Meaning |
|---|---|---|---|
| `attr_wrong` | `university` \| `gender` \| `oda_tiipi` | required | Written attribute value is wrong; here's the right one. |
| `label_wrong_applied` | a label string | — | This label should NOT be present. |
| `label_missing` | a label string | — | This label SHOULD be present but isn't. |
| `identity_wrong` | — | one of `ogrenci`/`veli`/`ogrenci-degil`/`none` | The identity call is wrong; correct call is `correct_value` (`none` = no identity label). Sugar over label_wrong/label_missing for the mutually-exclusive identity group. |

**Optional annotations** the converter may add when the human states them explicitly (never inferred):
- `"stateable": true|false` on an `attr_wrong` flag — overrides the default stateability derivation (§6.3) for edge cases (e.g. lead named a uni but system correctly could-not-know campus).

Anything the converter is unsure about → it must **omit the flag and note the ambiguity in a `converter_notes` array**, never guess (see `opt_protocol.md`, §9).

### 4.3 Schema validation (the "specific ruled format")

`calculate` mode hard-validates before computing and aborts with a line-item error list on any of:
- `round_id` mismatch between sample and feedback.
- A flag referencing a `cw_id` not in the sample.
- Unknown `kind`, unknown `target` label (not in the static registry §5), unknown attribute name.
- `attr_wrong` without `correct_value`; `correct_value` not a legal value for that field.
- `label_missing`/`label_wrong_applied` targeting a carried-through or never-touch label (those are not gradeable — §5).

Validation failure ⇒ non-zero exit, no report written. Determinism requires a clean, complete input.

---

## 5. Static label registry (mirrored from `label_resolver.py`, frozen in the script)

The script embeds a registry so grading is layer-aware. It must be kept in sync with `app/tagassigner/label_resolver.py` (the spec notes this as a maintenance coupling; a unit test asserts equality — §8.5).

| Bucket | Members | Graded? | Layer |
|---|---|---|---|
| **LLM-owned** | `LIST_1_USABLE` minus `info-check`, plus `kapora-alindi` (LLM may add) | **Yes** | LLM |
| **Router-owned** | `deal_awaiting`, `fiyat-soruyor`, `info-check` | **Yes (separate matrix)** | Router |
| **Human-terminal** | `sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak` | No (preservation-check only) | — |
| **Carried-through** | `LIST_3_NEVER_TOUCH` (CRM source/channel + sales-action) | No (preservation-check only) | — |

Identity sub-group (`ogrenci`/`veli`/`ogrenci-degil`) is LLM-owned but gets its own dedicated metric block (§7.B).

---

## 6. Gold reconstruction & layer attribution (deterministic)

### 6.1 Gold reconstruction (per conversation)

```
gold.labels   = set(final.labels)
                 − {t for label_wrong_applied flags}
                 ∪ {t for label_missing flags}
                 (identity_wrong resolves to the appropriate remove+add on the identity group)
gold.<attr>   = correct_value    if an attr_wrong flag targets <attr>
              = final.<attr>     otherwise
```

### 6.2 Layer attribution for a wrong field (the core mechanic)

Given `llm`, `final`, `gold` for an attribute (analogously for a single label using the LLM's proposed set vs final set):

| llm == gold? | final == gold? | Attribution | Outcome tag |
|---|---|---|---|
| — | ✅ | none | `correct` |
| ✅ | ❌ | **Router regression** | `router_broke` |
| ❌ | ❌ | **LLM error** (Router did not rescue) | `llm_error` |
| ❌ | ✅ | none (Router rescued) | `correct` + `router_rescued` counter |

For **Router-owned labels** the LLM never proposes them (stripped), so any error is unconditionally `router_error`.
For **input/transcript layer**: not machine-derivable from these three values alone. It is surfaced only when the human explicitly says "the transcript was missing X" — captured as an optional `layer:"input"` note on a flag and reported in a small separate "input-data flags" list, never mixed into LLM/Router rates.

### 6.3 Stateability & withhold semantics (per attribute)

Default derivation from gold (no annotation needed in the common case):

| Field | "Must make a call" (stateable, expects concrete value) | "Correct withhold" (stateable-but-ambiguous) | "Not stateable" |
|---|---|---|---|
| university | gold is a concrete list value | gold == `bilinmiyor-kampus` | gold == `bilinmiyor` |
| gender | gold ∈ {`Erkek`,`Kız`} | — | gold == `Bilinmiyor` |
| oda_tiipi | gold is a concrete room type | — | gold == `boş` |

- **Decision rate** denominator = `must-make-a-call` count. Numerator = system produced *any* concrete value.
- **Correct withhold** cases are excluded from the decision-rate denominator (they should NOT make a call) and included in correct-write accuracy when the system did withhold correctly.
- Optional `stateable` flag overrides these defaults for edge cases.

---

## 7. Metric catalog (the must-haves)

Each metric names its **denominator (D)** and **numerator (N)**; `calculations.md` restates each as formal notation. All rates carry n + Wilson 95% CI.

### A. Attribute metrics — university, gender, oda_tiipi (each computed at BOTH LLM and Final layers)

- **A1 Decision rate** — D: must-make-a-call conversations. N: system produced a concrete value. *(coverage)*
- **A2 Correctness-given-decision** — D: conversations where system produced a concrete value. N: value == gold. *(precision)*
- **A3 Correct-write rate (headline)** — D: all gradeable conversations for the field. N: final value == gold, **including correct withholds**. *(overall accuracy)*
- **A4 Withhold-correctness** — D: conversations where system withheld. N: withholding was correct. *(over-withholding guard)*
- **A5 Layer delta** — counts of `router_rescued`, `router_broke`, `llm_error`, `both_correct` (from §6.2). *(is the Router helping or hurting this field?)*

University and gender get the full A1–A5. Room type gets A1–A4 (Router does not override it, so A5 is trivially "LLM==Final").

### B. Identity metric — student/parent/neither (LLM layer)

- **B1 Decision rate** — D: conversations where identity is determinable (gold has an identity label). N: system applied *some* identity label. *(coverage — "how often does it make the call")*
- **B2 Precision-given-call** — D: conversations where system applied an identity label. N: it applied the *correct* one. *(the developer's exact definition)*
- **B3 Recall** — D: determinable conversations. N: system applied the correct identity label. *(the missing half)*
- **B4 Confusion breakdown** — 3×3 (+none) matrix of gold vs. called identity, to see *which* confusions dominate (e.g. veli→none).

### C. Label metrics — confusion matrix per bucket (LLM-owned; Router-owned separately)

From per-label TP/FP/FN over all (conversation × label) decisions in each bucket:
- **C1 Per-label precision / recall / F1** (and micro + macro roll-ups).
- **C2 Wrong-labels-applied rate** = ΣFP / Σapplied. *(precision complement)*
- **C3 Missing-correct-labels rate** = ΣFN / Σshould-be-present. *(recall complement — carries the D11 upper-bound caveat)*
- **C4 Error distribution by label** = share of (FP+FN) attributable to each label — e.g. "of all label errors, X% are `deal_awaiting`, Y% are `universitede`." Router-owned and LLM-owned reported separately so the developer sees which layer to fix.
- **C5 Preservation integrity** — count of conversations where a human-terminal or carried-through label was dropped/added by the system (should always be 0; any nonzero is a hard bug flag, not a rate).

### D. Roll-ups

- **D1 General attribute correctness** = mean of A3 across university/gender/oda_tiipi (equal-weighted; report also shows per-field so weighting is transparent).
- **D2 General label correctness** = micro-F1 over LLM-owned label decisions (primary), Router-owned micro-F1 reported alongside (not blended).
- **D3 General run correctness (headline KPI)** = fraction of conversations where **all graded fields** (3 attributes + all LLM-owned labels + all Router-owned labels) match gold. All-or-nothing.

---

## 8. The script — `tagassigner_accuracy.py`

### 8.1 Modes

```
python accuracy_optimization/tagassigner/tagassigner_accuracy.py snapshot \
    --cw 448,665,1164,... [--round 2026-07-16-a]
    # → writes inputs/sample_<round>.json from the DB (latest successful run per cw_id)

python accuracy_optimization/tagassigner/tagassigner_accuracy.py calculate \
    --sample inputs/sample_<round>.json \
    --feedback inputs/feedback_<round>.json
    # → validates, computes, writes results/<dd-mm-yyyy>_<hh.mm>_<n>_tagassigner-accuracy.md
    # → prints the headline block to stdout
```

- `snapshot` is the **only** DB-touching mode. It reuses `app.db` (`create_pool` / existing `queries`), read-only. It resolves `university_id → list value` and normalizes gender exactly as the runtime does, so `sample.json` reflects true end-state.
- `calculate` is a **pure function** of the two JSON files. No DB, no network, no clock except the output filename/header timestamp. Same inputs ⇒ byte-identical report body.

### 8.2 Determinism

- Sort every collection (conversations by cw_id, labels alphabetically, metrics in a fixed catalog order) before rendering.
- The only non-deterministic content is the timestamp in the filename and the report's "generated_at" header line; the metric body is fully determined by inputs. A `--emit-stdout-only` flag (my addition) prints the body without writing a file, for diffing in tests.

### 8.3 Confidence intervals

Wilson score interval at 95% (z=1.96), computed in pure Python. `0/0 ⇒ "n/a (n=0)"`. Every rate renders as `NN.N% [lo–hi] (n=…)`.

### 8.4 Report layout (`results/*.md`)

1. **Header** — round id, sample size n, generated_at, provider(s) if present, the standing D11 caveat.
2. **Headline** — D3 run correctness, D1 attribute, D2 label (both buckets).
3. **Per-area sections** — University, Gender, Identity, Room type, each with its A/B block and layer split, plus a one-line "biggest error mode" call-out.
4. **Label confusion** — C1–C4 tables, LLM-owned then Router-owned; C5 integrity line.
5. **Layer summary** — aggregated `router_rescued` / `router_broke` / `llm_error` across attributes and labels: "the Router net-helped university N times, net-hurt M."
6. **Appendix** — per-conversation gold vs final vs llm diff table (the audit trail; makes every number traceable to a conversation).

### 8.5 Tests (`accuracy_optimization/tagassigner/` ships with its own tests)

- Registry-sync test: the script's embedded label buckets equal the live `label_resolver` sets (fails if `label_resolver.py` changes and the harness wasn't updated).
- Golden-fixture test: a hand-built sample+feedback pair with known expected rates → asserts exact computed values (locks determinism and the formulae in `calculations.md`).
- CI-math test: Wilson bounds for known (k,n) pairs.
- Validation test: each malformed-input class (§4.3) aborts with the right error.

---

## 9. `opt_protocol.md` — contents

A protocol document addressed to the on-duty LLM. It must state:

1. **Role** — "You convert the developer's plain-English error list into `feedback_<round>.json`. You do not judge correctness, compute metrics, or touch objective data."
2. **The exception rule** — "Everything the developer did not flag is assumed correct. Never invent flags for issues they didn't raise."
3. **Start from the snapshot** — "The objective end-state lives in `sample_<round>.json`. Read it to resolve lead names → cw_ids and to know the current written value you are correcting. Never restate objective values into the feedback file."
4. **The four `kind` shapes** (§4.2) and exactly when to use each, with worked examples drawn from real cases (Mehmet → `label_wrong_applied: universitede`; Hawi → `attr_wrong: gender = Erkek`; a missed veli → `identity_wrong: correct_value=veli`).
5. **Ambiguity discipline** — "If you cannot confidently map an English complaint to one `kind`/`target`, do NOT guess. Emit nothing for it and record it verbatim in `converter_notes[]` for the developer to resolve."
6. **What you must never do** — never mark something correct that was flagged; never add stateability/ layer annotations the developer didn't state; never grade unflagged conversations.
7. **Output contract** — exact JSON shape, `round_id` must match the sample, one flag per distinct error.
8. **Layer note** — "You attribute nothing to a layer. Layer blame is computed by the script. Only pass a `layer:"input"` note if the developer explicitly says the transcript/data was missing."

---

## 10. `calculations.md` — contents

For **every** metric in §7, three things:
1. **Plain-English definition** — what question it answers, one sentence.
2. **Formal formula** — set-builder / fraction notation with the exact denominator and numerator, referencing the §6.3 stateability definitions and §6.2 attribution table.
3. **Withhold/edge handling** — how correct withholds, `n/a`, and mutually-exclusive groups are treated.

Plus a preamble section defining the symbols (`llm`, `final`, `gold`, the buckets, TP/FP/FN over (conversation × label)) and the Wilson CI formula, so the doc is self-contained and auditable against the script.

---

## 11. Reliability caveats baked into every report

- **Recall is an observed upper bound** (D11) — printed in the header and next to every recall/missing-label number.
- **Small-n honesty** — Wilson CIs on everything; `n/a` for empty strata; the report never prints a bare percentage.
- **Layer attribution assumes the snapshot is same-run** — `snapshot` must be taken before any re-sweep of the graded conversations; the report header records `generated_at` and the latest run's `completed_at` per conversation so drift is detectable.
- **Registry drift** — the report footer prints the `label_resolver` version/hash the run was graded against.

---

## 12. Out of scope / non-goals

- No changes to `app/`, prompts, migrations, or runtime behavior (read-only harness).
- No automated *grading* (deciding correctness) — the human + converter own that; the script only computes.
- No sampling/stratification logic — which conversations to grade is the developer's call (they pass `--cw`). (A future extension could stratify; not here.)
- No cross-run trend tracking/dashboards — each run emits one standalone report. (Reports are named/sorted to make manual trend-reading easy; automated trending is a later spec.)
- No provider A/B automation — the developer runs sweeps per provider and grades each; the harness just labels the report with whatever provider the snapshot recorded.

---

## 13. Build order & file manifest

1. `accuracy_optimization/tagassigner/calculations.md` — lock the formulae first (they are the contract the script implements).
2. `accuracy_optimization/tagassigner/tagassigner_accuracy.py` — `calculate` (pure) first, then `snapshot` (DB).
3. Tests (§8.5) alongside the script.
4. `accuracy_optimization/tagassigner/opt_protocol.md` — the converter protocol.
5. `inputs/.gitkeep`, `results/.gitkeep`.

**Definition of done:** golden-fixture test passes with rates matching a hand-computed expectation; `snapshot` reproduces the known cw448/665/1164 end-states from the live DB; a full `snapshot → (hand feedback) → calculate` dry run on the last sweep produces a readable report in `results/`.

---

*End of spec.*
