# 030 — TagAssigner Helper Mode, Write Gate & Human-Override Ledger

**Status:** Spec — ready to implement. Self-contained for a newly-onboarded engineer/LLM.
**Date:** 2026-07-22.
**Origin:** The 197-lead accuracy run
([results](../accuracy_optimization/tagassigner/results/22-07-2026_18.27_197_tagassigner-accuracy.md))
and its root-cause analysis ([problem_explanations_3.md](problem_explanations_3.md)).
**Supersedes in part:** `TAGASSIGNER_ACCURACY_FIXES_PLAN.md` Commit B (see §6 — de-scoped).

> **⚠ READ THIS FIRST — reminder the implementing AI must surface to the user.**
> Before/while implementing this spec, **remind the user that they still need to design a query &
> command language for TagAssigner** — something that can express operations like *"assign label X
> to all leads with qualities A, B, C"* or *"assign attribute Y to the following leads: (…)"*.
> **Do not design, detail, or plan that language in this spec or in implementation.** The user has
> explicitly deferred it to post-launch and will figure it out themselves. Your only obligation is
> to **remind them it is outstanding.**

---

## 1. The decision

TagAssigner is **no longer a source of truth. It is a helper.** A human always reviews it and may
overturn it. Three consequences drive this entire spec:

1. **Narrow the blast radius.** TagAssigner may only write a small allowlist of labels and
   attributes — the ones the accuracy run showed are trustworthy. Everything else is suppressed at
   the Router.
2. **The human is always right.** TagAssigner must **never** overturn a human assignment. Only a
   human may remove a human-set label.
3. **Learn from every correction.** Every human override is recorded in a new table for later
   analysis.

Plus: fix the measured accuracy bugs, **but only for the fields that survive the allowlist** (§6).

### Why these fields (evidence)

| Field | Measured (n=197) | Verdict |
|---|---|---|
| gender | A2 98.7% · A3 99.5% | keep |
| university | A2 **89.3%** (floor ~86%) | keep — but it is the least accurate survivor; helper-only |
| oda_tiipi | 100% (but **effectively unmeasured** — tertiary field, not scrutinised) | keep, low confidence |
| deal_awaiting | precision 100% (12/12) · recall 75% | keep — presence trustworthy, absence is not |
| hizmet-veremiyoruz | precision 100% (13/13) · recall 81% | keep — same asymmetry |
| universitede / univotelli / academic ladder | 100% (0 FP, 0 FN) | keep |
| **identity (ogrenci/veli/ogrenci-degil)** | **B2 precision 65%** | **suppress** |
| **ilgilenmiyor, kapora-alindi** | kapora leaked to 2 leads (Sude 1169, Aman 78) | **suppress** |

---

## 2. Part A — The Router write gate (allowlist)

### A1. Label allowlist

Add to `app/tagassigner/label_resolver.py`:

```python
# Labels TagAssigner is permitted to ADD or REMOVE. Everything else is read-only to the bot.
TAGASSIGNER_WRITABLE_LABELS: frozenset[str] = frozenset([...])
```

**FINAL — user-confirmed 2026-07-22. This list is closed; do not add to it without the user.**

```python
TAGASSIGNER_WRITABLE_LABELS = frozenset([
    "deal_awaiting", "hizmet-veremiyoruz", "univotelli", "info-check",
    "pre-sinav", "hazırlık", "1-sinif", "2-sinif", "3-sinif", "4-sinif", "universitede",
])
```

(the last seven are `_ACADEMIC_YEAR_ORDER` — the "hazırlık, 1.sınıf etc." ladder; `universitede` is
its top rung.)

**OUT — the bot may never apply these** (it must still leave existing ones untouched, §A3):

`ogrenci`, `veli`, `ogrenci-degil`, `ilgilenmiyor`, `kapora-alindi`,
`yerlesti`, `yeni-giris`, `erasmus`, `fiyat-soruyor`,
`kyk-sonuc-bekliyor`, `ibb-yurdu-sonuc-bekliyor`, `universite-yurdu-sonuc-bekliyor`,
`yatay_geçiş_bekliyor`, `ziyaret`, `ziyaret-etti`, `ziyaret-etmedi`,
plus all of `LIST_3_NEVER_TOUCH` / `LIST_2_TERMINAL` (already never-touch).

`info-check` is IN — it is the bot's only channel for "human, please verify this", which is the
whole point of helper mode.

`ai` (`AI_PROCESSED_LABEL`) is an **operational marker, not a taxonomy label** — exempt from the
gate, still stamped on every conversation TagAssigner touches.

**Two consequences of this list the implementer must not trip over:**

1. **`fiyat-soruyor` is now OUT but is still computed.** `compute_fiyat_soruyor` runs in the Router
   and its result will be discarded by the gate. Leave the computation in place (it is harmless and
   cheap, and re-enabling is then a one-word change) but do **not** be surprised that it never
   reaches Chatwoot. Same for `strip_llm_fiyat_soruyor`.
2. **Only ONE mutex group still matters for bot writes.** With identity, the `ziyaret` family, and
   `yerlesti`/`yeni-giris` all suppressed, `_ACADEMIC_YEAR_ORDER` is the only mutex group the bot
   can still act on. `_CONTACT_IDENTITY`, `_VISIT_LEVELS`, `_ENROLLMENT_ORDER` and `_DEAL_TERMINAL`
   become bot-irrelevant — but keep them, because they must still not damage **human-set** labels
   (§B2 mutex hazard).

### A2. Attribute allowlist

`app/config.py` already declares `TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES = ["university",
"ogrenci_cinsiyet", "oda_tiipi"]` — exactly the three to keep. **But it is currently only used to
build the Gemini payload (`payload_builder.py`) and by `sweep_clean` — it is NOT enforced at the
write path.** The gate is implicit (only `merge_attributes` and `reconcile_chatwoot_attributes`
produce patch keys, and they only produce those three).

**Do:** make it explicit. Immediately before `push_chatwoot_attribute_patches`, filter
`all_patches` to `TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES` and log-and-drop anything else. A one-line
assertion today; a real guard the first time someone adds a fourth attribute.

### A3. ⚠ CRITICAL INVARIANT — "suppress" means *don't apply*, **never** *delete*

The gate must **never remove a non-allowlisted label that is already on the conversation.** If a
human (or a previous model version) put `ogrenci` on a lead, the gate must leave it there
untouched. A naive implementation ("filter the final label set down to the allowlist") would
**wipe every human label on every run** — the exact opposite of §3.

Formally, for a non-allowlisted label `ℓ`: `ℓ ∈ final ⟺ ℓ ∈ before`. The bot neither adds nor
removes it.

### A4. Placement — one choke point

Apply the gate as the **last transformation before the write**, in
`apply_tagassigner_result` ([app/tagassigner/router.py](../app/tagassigner/router.py)) immediately
before `final_labels = sorted(set(final_labels) | {AI_PROCESSED_LABEL})` and
`_write_labels_with_retry`. A single choke point means no future code path can bypass it. Do
**not** scatter allowlist checks through `resolve_labels`, `compute_*`, or the strip chain — those
stay as they are; the gate is the backstop that makes them safe.

---

## 3. Part B — TagAssigner must never overturn a human

### B0. Current state (verified in code)

- **Attributes: already compliant.** `conversations.university_set_by / gender_set_by /
  oda_tiipi_set_by` carry provenance; the webhook sets them to `'human'` on a human edit
  ([app/webhooks/chatwoot.py:666-724](../app/webhooks/chatwoot.py#L666-L724)), and
  `merge_attributes` blocks with `reason="human_set"`
  ([attribute_merger.py:162](../app/tagassigner/attribute_merger.py#L162), `:207`, `:254`).
  ✅ No change needed beyond verification tests.

- **Labels: NOT compliant — this is the core defect.** There is **no label provenance anywhere.**
  `resolve_labels` treats Gemini's silence as an explicit removal for *any* `LIST_1_USABLE` label,
  no matter who set it ([label_resolver.py:111-116](../app/tagassigner/label_resolver.py#L111-L116)):

  ```python
  # Remove List-1 labels from 'before' that Gemini did NOT propose
  for label in LIST_1_USABLE:
      if label in final and label not in proposed_set:
          final.discard(label)
  ```

  A human adds `universitede`; the next run's Gemini doesn't mention it; TagAssigner deletes it.

- **`hizmet-veremiyoruz` actively documents the violating behaviour.** Its module docstring says a
  *human-added* `hizmet-veremiyoruz` on an in-city conversation **"WILL be removed on the next run.
  This is intended."** ([hizmet_veremiyoruz.py:15-18](../app/tagassigner/hizmet_veremiyoruz.py#L15-L18)).
  Under this spec that is **no longer intended** — see B3.

- `deal_awaiting` is already add-only ✅. `LIST_2_TERMINAL` and `LIST_3_NEVER_TOUCH` are already
  protected from removal ✅.

### B1. Label provenance: record what the bot itself wrote

Add to `conversations` (migration):

```sql
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS tagassigner_last_labels     text[],
  ADD COLUMN IF NOT EXISTS tagassigner_last_labels_at  timestamptz,
  ADD COLUMN IF NOT EXISTS tagassigner_last_run_id     uuid REFERENCES tag_assigner_runs(run_id);
```

Written by the Router **immediately after a successful label write**, storing the exact set it just
pushed to Chatwoot. This single field powers all three requirements: never-overturn, do-not-re-add,
and the override ledger (§4). It must be written in the same logical step as the Chatwoot write so
it can never drift; if the Chatwoot write fails, do not update it.

**Bootstrap / null case:** when `tagassigner_last_labels IS NULL` (bot has never written, or
pre-migration rows), treat **every** existing label as foreign/human-owned — i.e. remove nothing.
Fail safe toward the human.

### B2. New `resolve_labels` semantics

Derive three sets at run start (`before` = live Chatwoot labels, `bot_last` =
`tagassigner_last_labels`):

```
human_owned  = before − bot_last          # bot didn't put these here → IMMUTABLE
bot_owned    = before ∩ bot_last          # only these may be removed
human_removed = bot_last − before         # bot wrote it, human deleted it
```

Rules:

1. **`human_owned` labels always pass through untouched** — never removed, regardless of Gemini,
   mutex, or any `compute_*`/`strip_*` step.
2. **Removal is permitted only for `bot_owned ∩ TAGASSIGNER_WRITABLE_LABELS`.** Gemini's silence
   is an explicit removal *only* for labels the bot itself applied.
3. **Additions** = `proposed ∩ TAGASSIGNER_WRITABLE_LABELS`.
4. Non-allowlisted labels: pass-through (A3 invariant).

**⚠ Mutex hazard (easy to miss).** `_enforce_mutex` can currently delete a human label as
collateral: a human sets `2-sinif`, Gemini proposes `3-sinif`, `_apply_ordered_mutex` keeps the
most advanced and drops the human's. **Mutex resolution may only ever drop bot-owned labels.** If
the winning label would displace a `human_owned` one, the bot must **yield** — keep the human's
label, do not add its own — and (if `info-check` is allowlisted) raise `info-check` so a human
adjudicates. Same rule for `_apply_one_only_mutex` and `_apply_visit_mutex`.

### B3. `hizmet-veremiyoruz` behaviour flip

`compute_hizmet_veremiyoruz` currently unconditionally discards the label then re-adds it from
geography, which silently deletes a human's. Change: it may only remove the label when the label is
**bot-owned**. Update the module docstring — the "Router-authoritative, will remove a human's
label" paragraph must be rewritten to state the opposite. Same audit for
`strip_gemini_info_check` / `apply_info_check` and `compute_fiyat_soruyor`: verify none of them can
strip a human-added instance of their own label.

### B4. Sticky suppression (`human_removed`) — DECIDED

**User-confirmed 2026-07-22: the bot may NOT re-add a label a human removed. Permanent, no TTL.**

Implement as a sticky suppression per `(conversation, label)`: once a label appears in
`human_removed`, TagAssigner may never add it to that conversation again. Only a human may put it
back.

Storage: a `tagassigner_suppressed_labels text[]` column on `conversations` (accumulate — union on
each detection), or an equivalent row set. It must survive `tagassigner_last_labels` being
overwritten, so it cannot be derived on the fly — it has to be persisted separately at the moment
the removal is detected (both detection paths in §4 must write it).

Ordering inside the gate: apply suppression **after** additions are computed, so a suppressed label
is stripped even if Gemini re-proposes it and even if a `compute_*` step re-derives it (this is what
makes it stick for `hizmet-veremiyoruz` and `deal_awaiting`, whose Router computations would
otherwise re-add it every run).

> Note the interaction with `deal_awaiting`, which is documented as "add-only, never removed here":
> add-only must now also mean "not re-added if a human removed it."

---

## 4. Part C — The human-override ledger

**Goal:** capture every situation in which a human overturned TagAssigner, for later analysis.

### C1. Schema

```sql
CREATE TABLE IF NOT EXISTS tagassigner_overrides (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id           uuid NOT NULL REFERENCES conversations(id),
    chatwoot_conversation_id  int4 NOT NULL,

    field_kind                text NOT NULL CHECK (field_kind IN ('label','attribute')),
    field_name                text NOT NULL,   -- 'universitede' | 'university' | 'ogrenci_cinsiyet' …

    action                    text NOT NULL CHECK (action IN ('added','removed','changed')),
    bot_value                 text,            -- attribute: the value; label: 'present'/'absent'
    human_value               text,

    bot_run_id                uuid REFERENCES tag_assigner_runs(run_id),
    bot_written_at            timestamptz,
    detected_at               timestamptz NOT NULL DEFAULT now(),
    detected_via              text NOT NULL CHECK (detected_via IN ('webhook','run_reconcile')),

    chatwoot_agent_id         int4,
    chatwoot_agent_name       text,
    context                   jsonb            -- free-form: transcript len, gemini snapshot ref, etc.
);

CREATE INDEX IF NOT EXISTS idx_ta_overrides_conv   ON tagassigner_overrides (conversation_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_ta_overrides_field  ON tagassigner_overrides (field_kind, field_name, detected_at DESC);
```

`bot_run_id` is the join key back to `tag_assigner_runs.gemini_result` — so any later analysis can
recover exactly what the model proposed and why it was wrong. **This is the point of the table:**
it is the training/evaluation corpus that grade-by-exception cannot give us (see §7).

One row **per field**, not per event — a human changing two attributes in one edit produces two
rows.

### C2. Detection path 1 — webhook (primary, real-time)

`_process_conversation_updated` ([app/webhooks/chatwoot.py:599](../app/webhooks/chatwoot.py#L599))
already fires on human edits and already filters out bot-authored updates via `_is_bot_authored` /
`record_self_write`. It also already has the **pre-update DB row** in hand (`conversation`) before
it writes — which is exactly the "bot value" needed for the diff.

**Do:** in that handler, before `sync_conversation_labels_and_attributes`, diff:
- **labels:** incoming `labels` vs `tagassigner_last_labels` → emit `added` / `removed` rows for
  any delta.
- **attributes:** incoming `university` / `ogrenci_cinsiyet` / `oda_tiipi` vs the pre-update
  `conversation` values, but **only when the prior `*_set_by` was `'tagAssigner'`** (a human
  editing a field the bot never set is not an override — it is just data entry).

Capture agent attribution from the payload when present (the module already notes the payload may
omit the acting agent — leave the columns null in that case; do not block on it).

### C3. Detection path 2 — run-start reconciliation (backstop)

The Router already reads live Chatwoot labels at run start (`current_labels`). Diff them against
`tagassigner_last_labels` there too, and log any delta with `detected_via='run_reconcile'`. This
catches everything the webhook missed — webhook downtime, bulk edits, direct API changes — and
costs nothing extra because the read already happens.

This is also the *same* diff that B2 needs, so compute it once and use it for both.

### C4. Dedupe

Both paths can observe the same override. Dedupe on
`(conversation_id, field_kind, field_name, bot_value, human_value)` within a short window (e.g. 10
minutes); prefer keeping the `webhook` row (it carries agent attribution). A partial unique index or
an explicit pre-insert check is fine — do not rely on a global unique constraint, because the same
field can legitimately be overridden again later.

---

## 5. Part D — Ordering

Within `apply_tagassigner_result`, the final sequence becomes:

```
strip chain → resolve_labels(provenance-aware, B2)
            → university override → merge_attributes → apply_info_check
            → compute_fiyat_soruyor → compute_hizmet_veremiyoruz (B3) → apply_deal_awaiting
            → ⟶ WRITE GATE (A1/A3/A4) ⟵     ← new, single choke point
            → + ai marker
            → write labels to Chatwoot
            → persist tagassigner_last_labels (B1)   ← only on write success
            → filter attribute patches to allowlist (A2) → write attributes
```

---

## 6. Part E — Accuracy fixes, restricted to the surviving fields

Only the bugs affecting **allowlisted** fields are in scope. Each was reproduced at the source
during the run-3 analysis; see [problem_explanations_3.md](problem_explanations_3.md) for evidence.

### University (kept — and the weakest survivor at ~89%)

| # | Fix | Root cause / evidence | Affected leads |
|---|---|---|---|
| U1 | Delete the bare `güney kampüs` / `güney yerleşkesi` aliases (migration 027) and add them to `DISTRICT_STOPLIST` | "güney kampüs" is generic (Bahçeşehir/Medeniyet/Medipol all use it) but is aliased to Boğaziçi Ana Kampüs. Same bug class as the `beyoğlu` regression fixed in 028 | Merve 1446, Öykü 267 |
| U2 | Strip our **own property/branch names** from the text before university extraction; add university-colliding districts (`maltepe`, `seyrantepe`, `ataşehir`) to `DISTRICT_STOPLIST`. A district may only disambiguate a **campus** once a parent is matched — never select the university | The canonicalizer scans the widget-injected branch name the lead pasted ("Academic House **Maltepe**") and housing districts ("Maltepe'den") | Eyşan 909, Şevval 1227, Döner 1044, Doruk 12 |
| U3 | Add bare `istanbul` (and `istanbul merkez`) to `DISTRICT_STOPLIST` | A lone city token selects İÜ or İstanbul Aydın; "İstanbul'da kalmak" was read as the university | Filiz 183, Murat 1288, HasretCan 380 |
| U4 | Enforce **exact-match only (no Levenshtein) for aliases ≤ 4 chars**; audit + purge short aliases (`iou`→Okan, `isik`/`ışık`→Işık) via `docs/alias_collision_check.py` | Short aliases fuzzy-collide with unrelated tokens. Furkan was correct in earlier runs → **regression** | Furkan 1168, Enda 575, Hazel 1167 |
| U5 | Add missing campus aliases (`beşiktaş` → Bahçeşehir Çırağan; `cerrahpaşa` / `iü cerrahpaşa` → İstanbul Üniversitesi Cerrahpaşa). **And**: when the deterministic scan yields only `PARENT_ONLY`, keep the LLM's campus if it is a valid campus of that same parent instead of withholding | The authoritative deterministic mention overrides and discards a correct LLM campus | Nihan 1119, Sami 772 |
| U6 | Add curated default campuses (extend the migration-029 `parent_university_default_campus` map) — **values below, user-confirmed** | User-confirmed 2026-07-22 | Can 1269, Hazel 1167, Aysun 1272, Bahar 940, Nihan 1119, Sami 772 |
| **U7** | **Reconcile `university_chatwoot_label_map` with Chatwoot's live dropdown** — see the blocker below. **Do U7 before U6**, or U6 cannot be implemented | 26 mapped values do not exist in Chatwoot; 21 Chatwoot values are unmapped | systemic |

#### U6 — confirmed default campuses

| Parent | Default campus | Chatwoot list value | Status |
|---|---|---|---|
| İstanbul Teknik Üniversitesi (`b77ff96a-…`) | Ayazağa (`a17cc4c1-…`, internally "İTÜ - Maslak Kampüsü") | `İTÜ - Ayazağa` | ✅ exists in both Chatwoot and the map — implementable as-is |
| Bahçeşehir Üniversitesi (`0724edec-…`) | Çırağan / Beşiktaş | **`Bahçeşehir Üniversitesi`** (plain) | ⚠ **blocked** — exists in Chatwoot, **missing from `university_chatwoot_label_map`**. Needs a mapping row first (see U7) |
| İstanbul Üniversitesi Cerrahpaşa | single value | `İstanbul Üniversitesi Cerrahpaşa` | ✅ exists in both |

#### U7 — ⚠ NEW BLOCKER: the label map has drifted from Chatwoot

Verified live against Chatwoot's `custom_attribute_definitions` API: the `university` dropdown has
**84** values; `university_chatwoot_label_map` has **89**. They are not the same set.

**26 values are in our map but NOT in Chatwoot** — TagAssigner can write a value the dropdown does
not contain. Includes several this system actively produces:
`Bahçeşehir Üniversitesi - Çırağan`, `Bahçeşehir Üniversitesi - Kuzey`,
`Medeniyet Üniversitesi - Ünalan/Göztepe`, `Topkapı Üniversitesi - Kazlıçeşme`,
`Cerrahpaşa Tıp Fakültesi`, `İTÜ - Tuzla`, `Marmara Üniversitesi - Acıbadem`,
`Haliç Üniversitesi - Ana Kampüs/5. Levent`, `Gedik Üniversitesi - Harbiye`, …

**21 values are in Chatwoot but unmapped** — a human can select them, but the bot can never resolve
or reproduce them: `Bahçeşehir Üniversitesi`, `Medipol Üniversitesi - Güney`,
`Medeniyet Üniversitesi - Güney`, `Medeniyet Üniversitesi - Kuzey`,
`Kent Üniversitesi - Kağıthane`, `MSGSÜ - Bomonti`, `Topkapı Üniversitesi - Fatih`, …

**Why this matters beyond U6:**

- **It silently corrupts writes.** `resolve_university_list_value` resolves against the map, so an
  unmapped human selection looks like `validation_failed`; and a mapped-but-nonexistent value can
  be pushed into a Chatwoot list field that has no such option.
- **It invalidates part of the run-3 grading.** Several gold values used in
  [problem_explanations_3.md](problem_explanations_3.md) are strings Chatwoot cannot store —
  Öykü 267 should be `Medeniyet Üniversitesi - Güney` (not `- Ünalan/Göztepe`), Enda 575 should be
  `Kent Üniversitesi - Kağıthane` (not `- Taksim`), Nihan 1119 should be `Bahçeşehir Üniversitesi`
  (not `- Çırağan`). The **error counts are unchanged** (those writes were wrong either way), but
  the gold strings were unwritable.
- **It reverses one run-3 conclusion.** Ayşe Özkan Darıcı (1283) was dismissed as "not an error —
  only one Medipol campus exists." That was based on our map. **Chatwoot does have
  `Medipol Üniversitesi - Güney`**, so the lead's stated Güney campus *was* expressible and writing
  `- Kuzey` **was** a real error, caused by the missing mapping. University A3 for run 3 is
  therefore 182/197 ≈ **92.4%**, not 92.9%.

**Do:** dump both sets, reconcile row-by-row with the user (some map rows may be legitimately
retired campuses; some Chatwoot options may need adding to the map), then add a **startup/CI
assertion** that the two sets match so this can never drift again silently.

### Gender (kept)

| # | Fix | Root cause | Affected |
|---|---|---|---|
| G1 | In `inbound_gender_signal`, reject **interrogative** frames before accepting a gender token — "kız/erkek öğrenci **için mi**", "**sadece** … için mi", trailing "mı/mi/mu/mü?" | "Sadece kız öğrenciler için mi?" is a question about *our dorm's policy*, not a gender statement; written as `Kız` | Nergis 1107 |

### deal_awaiting (kept)

| # | Fix | Root cause | Affected |
|---|---|---|---|
| D1 | Add **İstanbul Üniversitesi Cerrahpaşa** to `deal_awaiting_universities`; audit the list for other out-of-service İstanbul institutions | Verified live: İÜC is `on_deal_await=False` while *Cerrahpaşa Tıp* is `True`. Not serviceable, so it should fire | Jule 856, Nuriye 850, Mübeccel 372 |
| D2 | When the university is withheld as **ambiguous** but *every* candidate is a deal_awaiting university, apply the label | `apply_deal_awaiting` no-ops on `university_id IS NULL`, so ambiguous "Cerrahpaşa" can never reach it | "..." 1016 |
| D3 | **`hotel_accessible_universities` cleanup** (data, separate pass) | Over-wide rows falsely mark İstanbul Aydın and Okan Tuzla serviceable, suppressing deal_awaiting. Excluded from the accuracy numbers by policy, but real | GÖKÇE 1045, Alpay 1379, Kemal 710 |

### hizmet-veremiyoruz (kept)

| # | Fix | Root cause | Affected |
|---|---|---|---|
| H1 | Give `compute_hizmet_veremiyoruz` an **out-of-İstanbul city/province gazetteer**; apply the label when the phrase names a non-İstanbul city/district, not only a non-İstanbul *university*. Keep the in-city short-circuit so "Kadıköy" never trips it | The scan matches `out_of_city_universities` **names** only. "Ankara" worked by luck (matched "Ankara Bilim Üniversitesi"); "İzmir"/"Bornova"/"Çorum" match nothing | Duygu 1426, Nihan 992, Erdem 593 |
| H2 | Must no longer remove a **human-set** instance (see B3) | Conflicts with §3 | — |

### oda_tiipi (kept)

No code fix. It scored 100% but was **effectively unmeasured** — a tertiary field the hand review
did not scrutinise. **Do not treat 100% as evidence.** Add it explicitly to the gold-set checklist
(§7).

### universitede / univotelli / academic ladder (kept)

No fixes — 0 FP / 0 FN across 197. One open taxonomy question, low priority: `universitede` was
applied to a *prospective* student (Gülhan 899, whose child had not yet placed). Decide later
whether `universitede` describes the housed student's enrollment or the conversation topic.

### ⛔ De-scoped by the allowlist (do NOT build)

- **`TAGASSIGNER_ACCURACY_FIXES_PLAN.md` Commit B ("Prove Otherwise" identity veto + `ilgilenmiyor`
  engagement veto)** — identity and `ilgilenmiyor` are now suppressed at the gate, so the entire
  experimental branch is unnecessary. This removes the single largest piece of planned work.
- **`strip_llm_kapora_alindi`** — the allowlist already blocks `kapora-alindi`. No dedicated strip
  needed.

Keep both documented as de-scoped-not-abandoned: if identity is ever re-enabled, Commit B is its
prerequisite.

---

## 7. Part F — Validation & acceptance

**Unit tests (new/extended):**

- **Gate:** a non-allowlisted label already present is **preserved** (A3) — the single most
  important test. A non-allowlisted label proposed by Gemini is **dropped**. `ai` survives.
- **Never-overturn:** human-added `universitede` survives a run where Gemini omits it. Human-added
  `hizmet-veremiyoruz` survives an in-city resolution (B3). Bot-added label absent from Gemini is
  removed. Null `tagassigner_last_labels` ⇒ nothing removed (bootstrap).
- **Mutex yield:** human `2-sinif` + Gemini `3-sinif` ⇒ human's `2-sinif` kept, `3-sinif` not
  added.
- **Attributes:** `*_set_by='human'` still blocks (regression guard); `all_patches` filtered to the
  three allowlisted keys.
- **Ledger:** webhook diff emits one row per changed field; run-reconcile emits for the same
  change; dedupe keeps one (prefers `webhook`).
- **U1–U6 / G1 / D1–D2 / H1:** per-conversation acceptance on the real flagged conversations, the
  way run-3 reproduced them (load the live universe, run the canonicalizer/compute on the stored
  transcript).

**Full suite** (`venv/bin/python3 -m pytest tests/ -q`) must stay green. Run
`docs/alias_collision_check.py` after U1/U4 → 0 hard failures.

**Measurement caveat that must not be forgotten.** All run-3 numbers are graded *by exception*
(unflagged = correct), so they are **upper bounds** — the bias is one-directional and can only
flatter. Realistic floors: university A2 ~86%, A3 ~87%, run-correctness ~72–74%. To get a number
defensible outside the team, build a **~50-conversation fully hand-labeled gold set** graded
independently (not by exception). The `tagassigner_overrides` ledger (§4) is the other half of
this: it is real-world ground truth that accumulates automatically.

---

## 8. Part G — Build order

0. **U7 first** — reconcile `university_chatwoot_label_map` against Chatwoot (§6). It blocks U6 and
   is a standalone correctness bug. Add the CI assertion so it cannot drift again.
1. **Migration:** `tagassigner_overrides` table + `conversations.tagassigner_last_labels{,_at,_run_id}`
   + `conversations.tagassigner_suppressed_labels` (§B4).
2. **B1** — persist `tagassigner_last_labels` on successful write (no behaviour change yet).
3. **B2/B3/B4** — provenance-aware `resolve_labels` + mutex yield + `hizmet-veremiyoruz` flip +
   sticky suppression.
4. **A1–A4** — the write gate (the label list is now closed; no confirmation needed).
5. **C2/C3/C4** — the override ledger, both detection paths (they also write the suppression set).
6. **D fixes** — U1–U6, G1, D1–D2, H1 (H2 lands with B3). D3 is a separate data pass.
7. Full suite green; per-conversation acceptance table passes.
8. Re-run the accuracy harness on a fresh cohort to confirm no regression.

**Sequencing note:** land §3 (never-overturn) **before** §2 (the gate). If the gate ships first
against the current `resolve_labels`, a bug in the gate can still delete human labels. Provenance
first, then narrowing.

---

## 9. Decisions — status

**RESOLVED (user, 2026-07-22) — no longer blocking:**

1. ✅ **Allowlist** (§A1): `info-check` **IN**; `yerlesti`/`yeni-giris`, `erasmus`, and
   `fiyat-soruyor` **OUT**; the four `*-sonuc-bekliyor` and the `ziyaret` family remain **OUT**.
   The list in §A1 is now closed.
2. ✅ **Sticky suppression** (§B4): the bot may **never** re-add a label a human removed.
   Permanent, no TTL.
3. ✅ **U6 default campuses:** İTÜ → `İTÜ - Ayazağa`; Bahçeşehir → plain
   `Bahçeşehir Üniversitesi` (the Çırağan/Beşiktaş campus); İÜC → its single value.

**STILL OPEN — blocking:**

4. ⚠ **U7 map reconciliation** (§6). 26 mapped values don't exist in Chatwoot and 21 Chatwoot
   values are unmapped. **This blocks U6's Bahçeşehir default** (the plain value has no mapping
   row) and is a live correctness bug on its own. Needs a row-by-row pass with the user to decide,
   for each mismatch, whether to add the mapping or retire the map row.

**STANDING REMINDER:**

5. 🔔 **(§0)** Tell the user the **query & command language** for TagAssigner is still outstanding
   and awaits their post-launch design. Do not design it.
