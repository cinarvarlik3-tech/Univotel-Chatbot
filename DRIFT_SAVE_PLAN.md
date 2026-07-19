# DRIFT_SAVE_PLAN.md — TagAssigner Label & Attribute Drift Mitigation

**Status:** Plan only — **do NOT implement yet.** Ready to hand to any implementer.
**Author context:** Produced from the July 2026 drift investigation. Companion docs:
[docs/problem_explanations_1.md](docs/problem_explanations_1.md) (accuracy run + root causes),
and the accuracy harness at [accuracy_optimization/tagassigner/](accuracy_optimization/tagassigner/).

---

> ## ⚠️ TOP NOTE — consider the add/remove (delta) output rewrite too
>
> This plan deliberately **avoids** rewriting the LLM's output contract from
> "full-state snapshot" to "add/remove delta." That rewrite (**"Suite C"**, sketched in
> §8) is the only option that fixes the *root* conflation behind label drift — the LLM's
> silence currently means both "no opinion" **and** "remove this label." Suites A + B
> below are cheaper mitigations that do **not** touch the LLM contract.
>
> **We may still want Suite C.** If, after shipping A + B, spurious-add accumulation or
> label churn is still unacceptable, revisit the delta rewrite. Keep it on the roadmap.
> Its cost and trade-offs are documented in §8 so the decision can be made later without
> re-deriving it.

---

## 1. TL;DR — what this plan does

TagAssigner re-classifies a conversation's **entire** label set and attribute snapshot on
every run. Because the LLM is **non-deterministic even at temperature 0** (measured — see
§3), re-runs silently change already-correct data. This plan stops that in two suites:

- **Suite A (attributes):** lock university / gender (and possibly identity) once written,
  gated by write-confidence so first-run mistakes stay correctable. Humans always override.
- **Suite B (labels):** (B1) stop treating "LLM didn't re-mention a label" as "remove it";
  (B2) stop re-running conversations that haven't materially changed; (B3) add a separate,
  conservative, low-frequency **removal/GC pass** to clear labels that B1 would otherwise
  let accumulate forever.

Neither suite requires changing the LLM's prompt output format. Suite C (§8) would.

---

## 2. Background — why drift happens (for an implementer new to this)

- **Labels:** [app/tagassigner/label_resolver.py](app/tagassigner/label_resolver.py) →
  `resolve_labels(before, proposed)`. Step 4 of that function removes any LIST_1 label that
  is in `before` but absent from the LLM's `proposed` set — i.e. **absence = explicit
  removal.** A correct label the LLM simply forgets to re-emit on a later run is silently
  dropped. This is the core label-drift mechanism.
- **Attributes:** [app/tagassigner/attribute_merger.py](app/tagassigner/attribute_merger.py)
  → `merge_attributes()`. `university` and `gender` currently allow **bot-to-bot changes**
  (a later run can overwrite an earlier correct value with a worse guess). `oda_tiipi` is the
  exception — it already blocks bot changes once concrete (`reason="already_set"`). That
  `oda_tiipi` block is the **reference pattern** Suite A generalizes.
- **Re-run frequency:** the nightly batch
  ([app/tagassigner/batch_client.py](app/tagassigner/batch_client.py) →
  `submit_nightly_batch`, eligibility in
  [app/db/queries.py](app/db/queries.py) → `get_conversations_eligible_for_nightly_batch`)
  re-classifies any already-tagged conversation with `messages_since_last_run >= 1`, using
  **full history**. One trivial new inbound message triggers a full re-roll. The per-day
  `auto_run_count` cap **resets nightly**, so it is not a lifetime throttle.
- **What does NOT drift (important):** the Router strips the LLM's `info-check`,
  `fiyat-soruyor`, and `deal_awaiting` and recomputes them **deterministically**
  ([app/tagassigner/router.py](app/tagassigner/router.py), `strip_*` calls + `apply_info_check`
  / `compute_fiyat_soruyor`). These do not drift. **Determinism works where applied** — the
  design principle behind Suite B's removal pass and the adjacent yerlesti fix (§9).

## 3. Evidence base (measured, so the implementer trusts the design)

- Provider/model: `openai` / `gpt-5.4-mini` (a **reasoning** model), `temperature=0.0`.
  `tagassigner_auto_runs` is currently **False** (drift engine off today; this plan is for
  when it is turned on).
- Live re-run test (12 conversations × 3 identical runs): **~17–33% produced different
  output**, in both labels and attributes, at temp 0. Drift is **bidirectional** (re-runs
  both fix and break).
- A non-reasoning model (**gpt-4.1**, temp 0) drifted **~17% as well** — OpenAI is not
  deterministic at temp 0 (MoE routing / batching). **Conclusion: the merge-layer fix is
  mandatory regardless of model.** Model choice (gpt-4.1 is ~5–8× faster, accuracy-neutral,
  more systematic errors) is a **separate** speed/debuggability decision, not a drift fix.

## 4. Current-state facts an implementer must not break

- Human edits set `*_set_by = 'human'` (via `sync_conversation_labels_and_attributes` on the
  Chatwoot webhook). Bot writes set `set_by = 'tagAssigner'` (default in
  `apply_tagassigner_attribute_updates`) or `'infoGatherer'`. **Human-set values must remain
  untouchable by the bot** — this guard already exists; preserve it.
- Labels live on **Chatwoot** (fetched live via `get_labels`), not the
  `conversations.labels` DB column (which is a stale mirror). Grading/reads must use the live
  Chatwoot set, as the Router already does.
- Router-owned labels (`info-check`, `fiyat-soruyor`, `deal_awaiting`) and never-touch labels
  (`LIST_3_NEVER_TOUCH`, human-terminal) must keep their current handling.

---

## 5. OPEN DECISIONS — resolve with a human before/while implementing

Defaults are given; the implementer should confirm, not assume.

| # | Decision | Default recommendation |
|---|---|---|
| D1 | **Gender lock gate:** lock unconditionally once set, or only when there was an explicit gender answer in the transcript? | Lock once set (simplest); gender is rarely wrong when stated. Revisit if false-locks appear. |
| D2 | **Identity (`ogrenci`/`veli`/`ogrenci-degil`):** lock like an attribute once set, or keep it mutex-replaceable by a later run? | Keep mutex-replaceable (identity is legitimately clarified late), but see Suite B — B1 already prevents *silent* identity drops. |
| D3 | **B2 "settled" definition + lifetime re-run cap:** what freezes a conversation? | Freeze on any human-terminal label (`sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak`); add a lifetime re-run cap (e.g. 8). |
| D4 | **Removal/GC pass frequency + trigger.** | Weekly sweep, or on-demand; NOT every run. |
| D5 | **Lock-flag persistence mechanism** (Suite A): new boolean columns vs. encode in `set_by`. | New nullable boolean columns (`university_locked`, `gender_locked`) via migration — cleanest; `set_by` overloading is the no-migration fallback. |
| D6 | **Window the nightly batch input?** Full-history re-classification is a drift amplifier. | Out of scope here, but strongly consider windowing already-tagged re-runs (see §9). |

---

## 6. SUITE A — Attribute lock (university, gender, [identity])

**Goal:** once the bot writes a concrete attribute value, the bot cannot *change* it to a
different concrete value; it can still *fill a blank*; a human still overrides everything;
and **only high-confidence writes are locked** (low-confidence writes stay correctable).

### A1 — base lock (extend the existing `oda_tiipi` pattern)

**File:** [app/tagassigner/attribute_merger.py](app/tagassigner/attribute_merger.py)

`_merge_oda_tiipi` already contains the pattern to copy:

```python
if current is not None and proposed is not None and current != proposed:
    result.blocked_mismatches.append(BlockedMismatch(
        field="oda_tiipi", current=current, proposed=proposed_raw, reason="already_set"))
    return
```

Add the equivalent block to `_merge_university` and `_merge_gender`: if the current stored
value is concrete (use `normalize_attribute_value` to treat sentinels as empty), the proposed
value is concrete, and they differ, **block the change** with `reason="already_set"` — unless
overridden by A2's confidence gate below. (The existing `set_by == "human"` block stays and
runs first.)

After A1 alone, all three attributes are lock-once against bot changes. This is the floor.

### A2 — confidence-gated lock (chosen approach; the "2")

Only *lock* a value that was written at **high confidence**. Persist a per-field `locked`
flag (see D5). At merge/write time:

- **University confidence signal (free):** the deterministic canonicalizer in
  [app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py)
  returns `CanonConfidence.CAMPUS | PARENT_ONLY | NONE` from `canonicalize()`, but
  `resolve_university_override()` currently **collapses it to a string**. **Plumbing change:**
  make `resolve_university_override` also return the `CanonConfidence` (e.g. return a small
  dataclass `(value: str, confidence: CanonConfidence)`), and thread it from
  [app/tagassigner/router.py](app/tagassigner/router.py) (the block that calls
  `resolve_university_override` then `merge_attributes`) into `merge_attributes` /
  `_merge_university`.
  - Write **locked = True** only when confidence is `CAMPUS` (value grounded in the lead's own
    words).
  - When the value came from the LLM belt only (canon `NONE`) → write **locked = False**
    (tentative, still updatable by a later run). This is exactly the cw 900 flicker case that
    should stay correctable rather than freeze a shaky guess.
- **Gender confidence signal:** no canonicalizer. Per D1, default is lock unconditionally once
  set (`locked = True`), or gate on "explicit gender answer present" (a signal the Router
  knows from the transcript and would pass into `merge_attributes`).

**Lock check becomes:** block a bot-to-bot change only when the current value's persisted
`locked` flag is True. If `locked` is False, allow the update (and re-evaluate the flag from
the new write's confidence).

**Persistence (D5):** add nullable `university_locked` / `gender_locked` booleans to
`conversations` via migration, written in
[app/db/queries.py](app/db/queries.py) → `apply_tagassigner_attribute_updates` alongside the
existing `set_by` companions. (No-migration fallback: encode via a `set_by` sentinel like
`"tagAssigner_tentative"`.)

**Identity (D2):** if locking identity, treat the identity mutex group like an attribute in
`resolve_labels` (block bot change once an identity label is set). Default is to leave it
mutex-replaceable and rely on Suite B/B1 to prevent silent drops.

### A — tests
Extend [tests/](tests/) attribute-merger tests: (a) blank→concrete still writes; (b)
concrete→different-concrete blocked when locked; (c) allowed when tentative; (d) human-set
still blocks bot; (e) university CAMPUS write sets locked, belt-only write sets tentative.

### A — acceptance
Re-running an unchanged conversation never changes a locked attribute. cw 900-type belt-only
university values remain updatable. cw 869-type gender/room churn stops.

---

## 7. SUITE B — Label drift

### B1 — additive merge with mutex replacement (stop silent drops)

**File:** [app/tagassigner/label_resolver.py](app/tagassigner/label_resolver.py) →
`resolve_labels()`, **Step 4 removal loop** (the loop that discards LIST_1 labels in `before`
not present in `proposed`).

**Change the removal rule:** a `before` label is removed **only** when the proposal contains a
**different member of the same mutex group** (a genuine transition). A `before` label that is
**not** in any mutex group is **never** auto-removed by absence (add-only / sticky). Mutex
groups already exist in the module: `_ACADEMIC_YEAR_ORDER`, `_ENROLLMENT_ORDER`,
`_VISIT_LEVELS`, `_CONTACT_IDENTITY`, `_DEAL_TERMINAL`.

Concretely: build a map `label -> mutex_group`. In Step 4, for each `before` LIST_1 label
absent from `proposed`, discard it **iff** `proposed` contains another member of its mutex
group; otherwise keep it. Leave Steps 1–3 (List-3 strip, terminal hard-guard, mutex
enforcement) unchanged.

**Effect:** legitimate transitions (`2-sinif→3-sinif`, `ogrenci→veli`) still work; silent
drops of correct standalone labels (`univotelli`, `universitede`, `yeni-giris`, …) stop.
**Known cost:** spurious *adds* now persist — that is what B3 cleans up, and B2 bounds.

**Tests:** [tests/test_label_resolver.py](tests/test_label_resolver.py) — add cases for:
absent non-mutex label is kept; mutex sibling replacement still swaps; absent mutex label with
no sibling proposed is kept.

### B2 — re-run policy (bound cumulative drift and B1's accumulation)

**File:** [app/db/queries.py](app/db/queries.py) →
`get_conversations_eligible_for_nightly_batch` (and consider
`get_conversations_eligible_for_tagging`).

**Change the already-tagged branch** so a conversation is NOT re-classified merely because
`messages_since_last_run >= 1`. Require **substantive** new content and/or apply a **lifetime
re-run cap**, and **freeze settled conversations** (D3: e.g. any human-terminal label present).
Intent is "don't re-run when nothing material changed" — NOT "run less across the board";
genuinely new content should still trigger a run so missing labels are added promptly.

**Tests:** eligibility-query tests — settled conversation excluded; conversation over the cap
excluded; conversation with substantive new content still included.

### B3 — removal / GC pass (clear what B1 lets accumulate)

**New component.** A separate, **conservative, low-frequency** LLM pass that verifies the
*currently-applied* labels against the transcript and removes unsupported ones. Verification
is more stable than generation, so this drifts far less than the main add pass.

- **New prompt:** `system_prompts/tagassigner_label_gc_prompt.md` — input: current labels +
  transcript; output: JSON list of labels **to remove** (only). Instruct it to remove **only
  on clear contradiction / absence of support**, high bar, and to **never** touch: human-set
  labels, `LIST_2_TERMINAL`, `LIST_3_NEVER_TOUCH`, Router-owned labels, or mutex labels it
  cannot confidently rule out.
- **New module:** e.g. `app/tagassigner/label_gc.py` — build payload (reuse
  [app/tagassigner/payload_builder.py](app/tagassigner/payload_builder.py) patterns), call the
  LLM (reuse [app/tagassigner/llm_client.py](app/tagassigner/llm_client.py) /
  [app/llm/factory.py](app/llm/factory.py)), parse removals, apply via `set_labels` with the
  same safety filters `resolve_labels` uses.
- **Scheduling:** a new low-frequency sweep (mirror the loops in
  [app/tagassigner/trigger.py](app/tagassigner/trigger.py)); frequency per D4. **Not** every
  run. Guard behind a **settings kill-switch** (e.g. `TAGASSIGNER_LABEL_GC_ENABLED`).
- **Guard against oscillation:** only consider labels that have persisted ≥1 prior run, and/or
  only remove labels the main add pass would not immediately re-add. Conservative bar is the
  primary defense.

**Tests:** new — GC removes an unsupported label; never removes human-set/terminal/never-touch/
Router-owned; disabled by kill-switch; empty transcript → no removals.

---

## 8. SUITE C (NOT in this plan) — add/remove delta output — keep on roadmap

**What:** change the LLM output contract from "full label snapshot" to explicit
`add: [...]`, `remove: [...]` lists; the Router applies the delta. Silence = "no opinion"
(never "remove"). Fixes the root conflation; eliminates B1's accumulation and B3's
oscillation; makes each run's intent auditable.

**Cost (why it's deferred):** new LLM output contract → prompt rewrite
([system_prompts/tagassigner_prompt.md](system_prompts/tagassigner_prompt.md)), new parser
([app/tagassigner/payload_builder.py](app/tagassigner/payload_builder.py) `parse_tag_result`),
new merge semantics, and **full re-validation of every conversation type and prompt example.**
Also both live and batch paths.

**New problems it introduces:** converts passive drops into **active** removals (a noisy model
can now delete correct labels on purpose); tighter coupling to an accurate current-label
baseline; higher per-call format-error surface. So it is "most correct architecturally" but
not strictly safer on removals.

**Revisit trigger:** ship A + B, measure with the accuracy harness; if accumulation/churn
remains unacceptable, do Suite C.

---

## 9. Adjacent fixes — NOT part of this plan, but related (don't lose them)

Tracked in [docs/problem_explanations_1.md](docs/problem_explanations_1.md); listed here so
they aren't forgotten:

- **`yerlesti` → deterministic Router gate.** It has a crisp, checkable gate (explicit
  "yerleş-" keyword in an inbound message **AND** message date in July 20–30) that the LLM
  demonstrably ignores (applied 3/3 to a lead only *awaiting* results). Move it into the
  Router-computed tier alongside `info-check`/`fiyat-soruyor`. **Accuracy fix, not drift.**
- **Taxonomy gap:** no label exists for "took the exam, awaiting results/placement" (between
  `pre-sinav` and `yerlesti`). Decide whether to add one — the missing bucket is what pushes
  the model to misapply `yerlesti`/`yeni-giris`.
- **`veli` over-application:** LLM applies `veli` to leads with explicit self-enrollment
  statements. Prompt-tighten with negative examples.
- **University alias collisions** (`bilgi`→İstanbul Bilgi, `bir`→Biruni, etc.) and best-match
  scan — a separate university-accuracy workstream in problem_explanations_1.md.

## 10. Suggested build order

1. **B1** (label_resolver, pure function + tests) — highest value, lowest risk.
2. **A1** (attribute lock, extend oda_tiipi pattern + tests).
3. **B2** (eligibility query + tests) — bounds accumulation before it can grow.
4. **A2** (confidence gate: canonicalizer confidence plumbing + lock-flag persistence + tests).
5. **B3** (removal/GC pass — new module, prompt, sweep, kill-switch, tests) — last, since it
   depends on B1/B2 being in place and needs the most testing.
6. Re-measure with the accuracy harness; decide on Suite C and the §9 adjacent fixes.

## 11. Global acceptance criteria

- Re-running an unchanged conversation N times produces **no change** to locked attributes and
  **no silent label drops** (validate by re-running the §3 experiment; drift on
  locked/sticky fields → 0).
- No regression in the accuracy harness headline
  ([accuracy_optimization/tagassigner/](accuracy_optimization/tagassigner/)).
- Human-set values and never-touch/terminal/Router-owned labels are never altered by any new
  code path (preservation-integrity check stays clean).
- Every new behavior is behind a test; the GC pass is behind a kill-switch.
