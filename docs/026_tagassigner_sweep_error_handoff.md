# Spec 026 — TagAssigner Sweep Error Handoff (Runs 1–3)

**Status:** Investigation complete — ready for engineering fix  
**Date:** 2026-07-15  
**Audience:** Engineer picking up TagAssigner accuracy work  
**Scope:** Residual errors from the last three CRM-import sweep batches (~11 conversations per batch). Business grading identified **5 erroneous conversations** across recent runs; all map to **three recurring failure modes**.

---

## 0. Executive summary

TagAssigner accuracy improved materially after Spec 024 (full-context backfill) and the 2026-07-14 prompt/DB fixes (Çapa mapping, single-campus list tags, faculty carve-out, `fiyat-soruyor` sequencing). Across the latest batches, **~6/11 conversations per run were fully correct**. The remaining errors are **not random** — they cluster into:

| Failure mode | Who controls it | Error count (flagged leads) | Fix lever |
|---|---|---|---|
| **`deal_awaiting` on already-serviced leads** | Router (deterministic) | 2 (Döner, Elif) | Router logic and/or `deal_awaiting_universities` table audit |
| **`fiyat-soruyor` false apply or failed removal** | Gemini (prompt) | 3 (Büşra, Ben Kısaca, Muhammet) | Prompt hardening + optional Router post-check |
| **University mis-inference** | Gemini (prompt) + list context | 2 (Ben Kısaca, Muhammet) | Prompt aliases, faculty carve-out gaps, tag-stripping |

**Key insight:** Fixing only the prompt will **not** resolve `deal_awaiting` errors. Fixing only the `deal_awaiting_universities` table will **not** resolve widget-opener `fiyat-soruyor` false positives. The three modes require **separate fixes**.

---

## 1. System context (read this first)

### 1.1 TagAssigner pipeline

```
DB messages + Chatwoot labels/attributes
  → payload_builder (inject university list + transcript)
  → LLM (Gemini) → JSON { labels, attributes }
  → Router:
       strip_gemini_deal_awaiting / strip_gemini_info_check
       resolve_labels (taxonomy enforcement)
       resolve_university_list_value (exact → normalized → LD1)
       merge_attributes
       apply_info_check
       apply_deal_awaiting          ← deterministic, NOT LLM
       write labels + attributes to Chatwoot
```

**Governing principle:** Gemini proposes; Router validates. See `docs/023_tagassigner_university_gender_matching_spec.md`, `docs/024_tagassigner_context_sync_persona_spec.md`, `docs/021_deal_awaiting_and_sweeps_spec.md`.

### 1.2 What changed recently (2026-07-14)

| Change | Files | Intent |
|---|---|---|
| Çapa Tıp dedicated Chatwoot value | `migrations/025_capa_tip_chatwoot_mapping.sql` | Sibel-style "Çapa tıp" → `Çapa Tıp Fakültesi` |
| Runtime list enrichment | `app/tagassigner/university_list_context.py` | Inject `[tek kampüs]`, `[tıp fakültesi]`, abbrev appendix |
| Prompt faculty carve-out, fiyat sequencing, gender-only guard | `system_prompts/tagassigner_prompt.md` | Hatice / eylul / Sibel class from prior batch |

These fixes addressed the **prior batch's** top errors but introduced a **new side effect** (see §5.4) and did not touch `deal_awaiting` Router logic.

### 1.3 Test workflow used for grading

```bash
./scripts/tag sweepclean --confirm
./scripts/tag importConvo --10    # random CRM conversations → chatbot DB
./scripts/tag sweep --10          # requires uvicorn running for queue drain
```

- Conversations imported from CRM (`CRM_DATABASE_URL`) with full message history.
- TagAssigner reads local `messages` table (backfill from Chatwoot when `read_full_history=true`).
- Results stored in `tag_assigner_runs.gemini_result` (raw LLM output) + Router writes to Chatwoot/DB.

### 1.4 Latest batch conversation map (CRM names → CW IDs)

| CW ID | CRM lead name | Flagged? |
|---|---|---|
| 83 | Muhammet Can Üzümcü | Yes |
| 207 | Elif | Yes |
| 577 | Артур Primus Group | No |
| 586 | Büşra | Yes |
| 702 | Arzu | No (side-effect bug — see §5.4) |
| 808 | Ben Kısaca S.D. | Yes |
| 811 | Berat Çaka | No |
| 833 | Serap Yurtsever | No |
| 1044 | Döner Demirci | Yes |
| 1190 | Selin | No |
| 1209 | Toka | No |

Run timestamp cluster: **2026-07-14 ~18:55–18:59 UTC** (all successful).

---

## 2. Error taxonomy

### 2.1 Mode A — `deal_awaiting` on serviceable leads

**Symptom:** Chatwoot conversation gets `deal_awaiting` label even though sales already pitched a specific property with pricing materials.

**Controller:** Router only — `app/tagassigner/deal_awaiting.py` → `apply_deal_awaiting()`.

**Trigger condition:** `conv.university_id` ∈ `deal_awaiting_universities` (36 rows as of 2026-07-15).

**NOT controlled by:** Gemini prompt (label is stripped from LLM output in `label_resolver.strip_gemini_deal_awaiting`).

**Semantic intent (Spec 017):** `deal_awaiting` = Istanbul school on ops list where **deal/inventory is expected soon but RecEngine returned NOT_FOUND**. Spec explicitly says **FOUND always wins** — if inventory exists, no label.

**Why TagAssigner diverges:** Spec 021 added TagAssigner as a **safety net** for conversations where RecEngine callback never fired. The safety net checks **only university table membership**, not whether:
- A human already pitched a hotel/yurt in the transcript
- `ilgili_otel` is set
- RecEngine would have returned FOUND today

### 2.2 Mode B — `fiyat-soruyor` errors

Two sub-types:

| Sub-type | Description | Example leads |
|---|---|---|
| **B1 — False apply** | Label added when lead never explicitly asked price | Büşra (widget bilgi opener), Ben Kısaca (Meta bilgi opener) |
| **B2 — Failed removal** | Label kept after bot delivered prices (typed TL or Drive pricing block) | Büşra, Muhammet (end state) |

**Controller:** Gemini via `system_prompts/tagassigner_prompt.md` § `fiyat-soruyor`.

**Current prompt rules (already present):**
- Explicit price tokens required (`fiyat`, `ücret`, `ne kadar`, etc.)
- Opener exclusion for generic `"bilgi alabilir miyim"`
- Sequence rule: bilgi opener → later `"fiyat ne"` = apply at price turn
- Removal when typed TL **or** `"Detaylar ve fiyat bilgisi:"` + Drive link in same bot message

**Why errors persist:** Widget/Meta product openers use phrases the model still conflates with price intent. Removal rule is stated but **not reliably applied** when pricing appears mid-conversation.

### 2.3 Mode C — University mis-inference

Two sub-types:

| Sub-type | Description | Example leads |
|---|---|---|
| **C1 — Faculty shorthand on single-campus parent** | `"Atlas tıp fakültesi"` → `bilinmiyor-kampus` instead of `Atlas Üniversitesi` | Ben Kısaca |
| **C2 — Phonetic / near-name confusion** | `"İstanbul kent üniversitesi"` → `Kültür Üniversitesi` instead of `Kent Üniversitesi - Taksim` | Muhammet |

**Controller:** Gemini proposal → `resolve_university_list_value()` in Router.

**Note:** Mode C2 is **not** resolver fuzziness — Levenshtein between normalized `"istanbul kent"` and `"kultur"` is **11**. The LLM chose the wrong list string outright.

---

## 3. Per-lead case studies

### 3.1 Döner Demirci — CW 1044 — `deal_awaiting` (Mode A)

**Business judgment:** Lead is serviceable; `deal_awaiting` should **not** be present.

#### Transcript (abbreviated)

| Turn | Speaker | Content |
|---|---|---|
| 1 | Lead | `Merhaba! … bilgi alabilir miyim?fiyat bilgisi alabilir miyim` |
| 2 | Bot | `hangi bölgedeki otellerimiz ile ilgileniyordunuz?` |
| 3 | Lead | `Marmara Maltepe kampüsü` |
| 4 | Bot | `Erkek öğrenci için miydi` |
| 5 | Lead | `Kız öğrenci` |
| 6 | Bot | **Academic House Maltepe** full pitch + `Detaylar ve fiyat bilgisi:` + Drive link |
| 7 | Lead | `Teşekkür ederim` |

#### TagAssigner output (`gemini_result`)

```json
{
  "labels": ["fiyat-soruyor", "universitede"],
  "attributes": {
    "university": "Marmara Üniversitesi - Maltepe",
    "ogrenci_cinsiyet": "Kız",
    "oda_tiipi": "boş"
  }
}
```

#### DB state after run

- `university_id` = `e992ca13-9397-46d0-82f1-5a32ad168850` (Marmara Maltepe) — **correct**
- Router then added `deal_awaiting` because this ID is on `deal_awaiting_universities`

#### Analysis

| Field | Expected (business) | Got | Verdict |
|---|---|---|---|
| `university` | Marmara Maltepe | Marmara Maltepe | ✓ |
| `ogrenci_cinsiyet` | Kız | Kız | ✓ |
| `fiyat-soruyor` | Debatable — opener has explicit `"fiyat bilgisi alabilir miyim"` | Applied | Arguably ✓ at opener; should **remove** after bot pricing block |
| `deal_awaiting` | **No** — property already pitched | **Added by Router** | ✗ |

**Root cause:** Marmara Maltepe remains on the 36-row deal list despite live inventory (Academic House Maltepe). TagAssigner has no transcript-aware suppression.

---

### 3.2 Elif — CW 207 — `deal_awaiting` (Mode A)

**Business judgment:** Lead is serviceable; `deal_awaiting` incorrectly applied (reported as recurring issue).

#### Transcript (abbreviated)

| Turn | Speaker | Content |
|---|---|---|
| 1 | Lead | Widget: `…bilgi alabilir miyim? Üniversitem:` |
| 2 | Lead | `Sağlık bilimleri Üniversitesi` |
| 3 | Bot | `Kadıköy'de sadece kızlara özel bir lokasyonumuz bulunuyor` |
| 4 | Lead | `Fiyat bilgisi alabilir miyim` |
| 5 | Bot | `tabii ki de iletiyorum` + attachments (null content rows) |
| 6+ | Lead | `1 ay sonra mezun olacağım`, location questions, map link from bot |

#### TagAssigner output

```json
{
  "labels": ["4-sinif", "24h_window_warning", "fiyat-soruyor"],
  "attributes": {
    "university": "Sağlık Bilimleri Üniversitesi",
    "ogrenci_cinsiyet": "bilinmiyor",
    "oda_tiipi": "boş"
  }
}
```

#### DB state

- `university_id` = `46f88dba-6f77-409a-aeea-9a97bcc4ba3f` (Sağlık Bilimleri Selimiye) — **correct**
- On `deal_awaiting_universities` → Router adds label

#### Analysis

| Field | Verdict |
|---|---|
| `university` | ✓ |
| `fiyat-soruyor` | ✓ (explicit `"Fiyat bilgisi alabilir miyim"`) |
| `4-sinif` | Review — lead said graduating in 1 month, not explicitly 4th year (possible LLM overreach; not in flagged error set) |
| `deal_awaiting` | ✗ — bot already offered Kadıköy girls location |

**Root cause:** Same as Döner — table membership without servicing context. Sağlık Bilimleri on deal list despite active sales engagement.

---

### 3.3 Büşra — CW 586 — `fiyat-soruyor` (Mode B1 + B2)

**Business judgment:** `fiyat-soruyor` added prematurely.

#### Transcript (abbreviated)

| Turn | Speaker | Content |
|---|---|---|
| 1 | Lead | Widget opener: `Academia Residence - 1+1 … bilgi alabilir miyim? Detayları öğrenebilir miyim? Üniversitem: Haliç Üniversitesi` |
| 2 | Bot | Academia Residence full pitch + **`Detaylar ve fiyat bilgisi:`** + Drive |
| 3 | Bot | GK Regency Suites pitch + **`Detaylar ve fiyat bilgisi:`** + Drive |

**Lead never asks about price.**

#### TagAssigner output

```json
{
  "labels": ["universitede", "fiyat-soruyor"],
  "attributes": {
    "university": "Haliç Üniversitesi - Ana Kampüs/5. Levent",
    "oda_tiipi": "1+1",
    "ogrenci_cinsiyet": "bilinmiyor"
  }
}
```

#### Analysis

| Issue | Type | Detail |
|---|---|---|
| `fiyat-soruyor` applied | B1 | Widget `"bilgi alabilir miyim"` / `"Detayları öğrenebilir miyim"` ≠ price ask |
| `fiyat-soruyor` not removed | B2 | Bot sent pricing block **twice** — final snapshot should omit label |
| `university` | ✓ | Haliç from widget — reasonable |
| `oda_tiipi` | ✓ | 1+1 from widget product name |

**Root cause:** Prompt opener exclusion covers generic Meta template but **not product-specific widget text** containing `"Detayları öğrenebilir miyim"`. Model still conflates `"bilgi"`/`"detay"` with price. End-state removal checklist not enforced.

---

### 3.4 Ben Kısaca S.D. — CW 808 — university + `fiyat-soruyor` (Mode C1 + B1)

#### Transcript (abbreviated)

| Turn | Speaker | Content |
|---|---|---|
| 1 | Lead | `Merhaba! … daha faza bilgi alabilir miyim?` |
| 2 | Bot | `hangi üniversite ve hangi kampüsteydiniz` |
| 3 | Lead | **`Atlas tıp fakültesi`** |
| 4 | Lead | Widget: `Academia Residence … bilgi alabilir miyim?` (empty Üniversitem) |
| 5 | Bot | Academia pitch + **`Detaylar ve fiyat bilgisi:`** + Drive |

**Lead never asks about price.**

#### TagAssigner output

```json
{
  "labels": ["fiyat-soruyor"],
  "attributes": {
    "university": "bilinmiyor-kampus",
    "oda_tiipi": "2 Kişilik",
    "ogrenci_cinsiyet": "bilinmiyor"
  }
}
```

#### DB facts for Atlas

| Field | Value |
|---|---|
| University row | `Atlas Üniversitesi - Hamidiye Kampüsü` |
| Chatwoot list value | `Atlas Üniversitesi` |
| Parent campus count | **1** (single campus) |
| Short name | `ATLAS` |
| DB alias | `atlas` → university_id |
| `[tıp fakültesi]` tag in injected list | **No** (not a dedicated faculty list entry) |

#### Analysis

| Issue | Expected | Got |
|---|---|---|
| `university` | `Atlas Üniversitesi` via `{parent} tıp` + `[tek kampüs]` carve-out | `bilinmiyor-kampus` |
| `fiyat-soruyor` | No — bilgi openers only | Applied |
| `oda_tiipi` | 2 Kişilik from widget | ✓ |

**Root cause C1:** Faculty guard (`"tıp fakültesi"` → `bilinmiyor-kampus`) **outranks** single-campus faculty carve-out for Atlas. Atlas is not tagged `[tıp fakültesi]` because the list value is generic `Atlas Üniversitesi`, not a faculty-specific string.

**Root cause B1:** Same widget bilgi false positive as Büşra.

---

### 3.5 Muhammet Can Üzümcü — CW 83 — university + `fiyat-soruyor` (Mode C2 + B1/B2)

#### Transcript (abbreviated)

| Turn | Speaker | Content |
|---|---|---|
| 1 | Lead | Widget: `GK Regency … bilgi alabilir miyim? Detayları öğrenebilir miyim? Üniversitem:` |
| 2 | Lead | **`İstanbul kent üniversitesi`** |
| 3 | Bot | `Merhabalar efendim` |
| … | … | scheduling gap |
| N | Lead | **`Önemli değil fiyatı öğrenebilir miyim`** |
| N+1 | Bot | **`15000 TL den başlıyor`** |

#### TagAssigner output

```json
{
  "labels": ["fiyat-soruyor", "universitede"],
  "attributes": {
    "university": "Kültür Üniversitesi",
    "oda_tiipi": "Tek Kişilik",
    "ogrenci_cinsiyet": "bilinmiyor"
  }
}
```

#### DB state after run

- `university_id` = `d176db14-61b9-407b-b4dd-f7f3ad423399` (**İstanbul Kültür Üniversitesi - Ataköy**) — **wrong**
- Was **not** pre-populated before run (not a stale-value echo)

#### DB facts for Kent vs Kültür

| | Kent | Kültür |
|---|---|---|
| List value | `Kent Üniversitesi - Taksim` | `Kültür Üniversitesi` |
| Short name | `İKÜ` | `KÜLTÜR` |
| Aliases | **None** for "kent" | None |
| Levenshtein(normalize) vs "istanbul kent" | — | **11** (resolver would not auto-correct) |

#### Analysis

| Issue | Expected | Got |
|---|---|---|
| `university` | `Kent Üniversitesi - Taksim` | `Kültür Üniversitesi` |
| `fiyat-soruyor` | Apply only after explicit price ask; **remove** after `15000 TL` | Kept in final snapshot |
| `oda_tiipi` | Tek Kişilik from widget | ✓ |

**Root cause C2:** LLM phonetic confusion — lead said **"kent"**, model picked **"Kültür"**. No `"kent üniversitesi"` alias in `university_aliases` or abbrev appendix (`İKÜ` does not match spoken "kent").

**Root cause B:** Opener widget bilgi may have primed label; explicit price ask later makes intermediate apply defensible; **failure to remove** after typed TL is the clear end-state bug.

---

## 4. Why these errors keep persisting

### 4.1 Architectural mismatch — `deal_awaiting`

| Layer | Behavior | Gap |
|---|---|---|
| **RecEngine (Spec 017)** | Label only on NOT_FOUND + on deal list; FOUND wins | Correct at runtime |
| **TagAssigner (Spec 021)** | Label whenever university on deal list, regardless of transcript | **Too broad for sweep/backfill** |
| **Ops table** | 36 universities marked deal-awaiting | **Stale** for schools now actively serviced (Marmara Maltepe, Sağlık Bilimleri) |

TagAssigner was designed as a **safety net for missing labels**, not as a **re-evaluator of deal status**. Sweeps over historical CRM conversations hit leads humans already served → false positives accumulate.

**Persistence driver:** Every sweep re-applies the same table check. Prompt changes cannot fix this.

### 4.2 Prompt-only limits — `fiyat-soruyor`

| Attempt | Result |
|---|---|
| Tightened "explicit price only" | Helped eylul-class openers in theory; widget product templates still slip through |
| Opener exclusion for `"bilgi alabilir miyim"` | Covers generic Meta template; **not** `"Detayları öğrenebilir miyim"` or product-specific widget blocks |
| Sequence rule (bilgi → later fiyat) | Model applies at wrong turn or ignores removal |
| Removal rule (TL typed / Drive block) | **Stated but weakly enforced** at final checklist |

**Persistence driver:** Turkish leads routinely open with `"bilgi alabilir miyim"` / `"Detayları öğrenebilir miyim"`. Sales bot **always** responds with pricing Drive blocks. Model must both **reject** openers and **strip** label at end — two hard LLM discipline tasks in one pass.

### 4.3 Incomplete university context — faculty + aliases

| Attempt | Result |
|---|---|
| `[tek kampüs]` / `[tıp fakültesi]` list tags | Helps Hatice/Yeni Yüzyıl/Çapa class; **Atlas tıp** still hits faculty guard |
| Abbrev appendix from `university_short_name` | Injects `ATLAS → Atlas Üniversitesi` but not `"atlas tıp"`; doesn't help `"Atlas tıp fakültesi"` phrasing |
| Faculty carve-out in prompt | Competes with stronger `bilinmiyor-kampus` rule |
| Kent/Kültür | No disambiguation; **İKÜ** short name useless when lead says full word "kent" |

**Persistence driver:** TagAssigner **does not** use InfoGatherer's `university_aliases` table at resolution time — only the LLM list + narrow Router resolver. Alias gaps = recurring misses.

### 4.4 Implementation side effect — list tag leakage (CW 702, Arzu)

Not flagged by business but **will cause future university misses:**

```json
"university": "Piri Reis Üniversitesi  [tek kampüs]"
```

LLM **copied inline metadata tags** from injected list into the attribute value. Router resolver rejects → **no university write**.

**Source:** `format_university_list_section()` appends tags on same line as list value (`app/tagassigner/university_list_context.py` L87–94).

**Persistence driver:** Any model that mimics list formatting will fail resolution until tags are stripped (Router) or moved off-list-value lines (payload).

---

## 5. Related code map

| Concern | Primary files |
|---|---|
| `deal_awaiting` apply | `app/tagassigner/deal_awaiting.py`, `app/tagassigner/router.py` (~L256) |
| `deal_awaiting` strip/preserve | `app/tagassigner/label_resolver.py` |
| Deal list membership | `deal_awaiting_universities` table, `queries.is_deal_awaiting_university()` |
| Semantic spec | `docs/017_deal_awaiting_recengine_spec.md`, `docs/021_deal_awaiting_and_sweeps_spec.md` |
| `fiyat-soruyor` rules | `system_prompts/tagassigner_prompt.md` L234–251 |
| University list injection | `app/tagassigner/university_list_context.py`, `app/tagassigner/payload_builder.py` |
| University resolution | `app/tagassigner/university_resolver.py` |
| Aliases (InfoGatherer only today) | `university_aliases` table, `app/layers/matching.py` |
| Raw LLM output audit | `tag_assigner_runs.gemini_result` |

---

## 6. Recommended fix directions (for implementer)

**Do not treat these as a single prompt edit.** Prioritize by mode.

### 6.1 Mode A — `deal_awaiting` (P0)

**Option A — Data (fastest):** Audit `deal_awaiting_universities`. Remove universities now actively serviced (at minimum Marmara Maltepe, Sağlık Bilimleri if ops confirms).

**Option B — Router guard (durable):** In `apply_deal_awaiting()`, skip when transcript shows bot serviced the lead, e.g.:
- Outbound message contains property name pattern + `Detaylar ve fiyat bilgisi:` + Drive link, OR
- `conv.ilgili_otel` is set (human or prior pipeline)

**Option C — Hybrid:** Table for true pending deals; Router guard for sweep backfill.

**Tests:** Extend `tests/test_deal_awaiting.py` with "serviced transcript → no label" cases.

### 6.2 Mode B — `fiyat-soruyor` (P1)

**Prompt:**
- Add negative examples for **product widget** openers: `"Detayları öğrenebilir miyim"`, `"Academia Residence … bilgi alabilir miyim"`.
- Strengthen **final checklist item**: "If bot typed TL amounts OR sent pricing Drive block, omit `fiyat-soruyor` even if lead asked earlier."

**Optional Router post-check (deterministic):**
- After LLM, scan transcript: if bot messages contain `\d+\s*TL` or pricing Drive template → strip `fiyat-soruyor` from resolved labels before Chatwoot write.

**Regression CW IDs:** 586, 808, 83.

### 6.3 Mode C — University (P1)

**Ben Kısaca / Atlas:**
- Prompt: extend faculty carve-out — `"Atlas tıp"` / `"atlas tıp fakültesi"` → `Atlas Üniversitesi` when `[tek kampüs]`.
- DB: add `university_aliases` row `atlas tıp` → Atlas university_id (InfoGatherer parity).
- Consider tagging logic: treat `"…tıp fakültesi"` lead text + single-campus match as sufficient.

**Muhammet / Kent:**
- Prompt: explicit disambiguation — **"kent" ≠ "Kültür"**; `"İstanbul kent"` / `"kent üniversitesi"` → `Kent Üniversitesi - Taksim`.
- DB: aliases `kent üniversitesi`, `istanbul kent üniversitesi` → Kent university_id.
- Abbrev appendix: add spoken-form aliases, not only `İKÜ`.

**Regression CW IDs:** 808, 83.

### 6.4 Side effect — list tag leakage (P2)

- **Router:** Strip trailing ` [tek kampüs]` / ` [tıp fakültesi]` from proposed university before `resolve_university_list_value()`.
- **Or payload:** Move tags to a separate metadata section, not on the same line as canonical list strings.

**Regression CW ID:** 702.

---

## 7. Verification plan

### 7.1 Re-run batch

```bash
./scripts/tag sweepclean --confirm
./scripts/tag importConvo --10
# Restart uvicorn after prompt/code changes
./scripts/tag sweep --10
```

### 7.2 Per-error acceptance criteria

| CW ID | Lead | Pass criteria |
|---|---|---|
| 1044 | Döner Demirci | **No** `deal_awaiting`; university = Marmara Maltepe; gender = Kız |
| 207 | Elif | **No** `deal_awaiting`; university = Sağlık Bilimleri |
| 586 | Büşra | **No** `fiyat-soruyor`; university = Haliç |
| 808 | Ben Kısaca S.D. | **No** `fiyat-soruyor`; university = Atlas Üniversitesi |
| 83 | Muhammet Can Üzümcü | **No** `fiyat-soruyor` at end state; university = Kent Üniversitesi - Taksim |
| 702 | Arzu | University resolves without `[tek kampüs]` in attribute string |

### 7.3 SQL audit queries

```sql
-- Latest gemini output for flagged IDs
SELECT c.chatwoot_conversation_id, r.gemini_result, r.completed_at
FROM conversations c
JOIN tag_assigner_runs r ON r.conversation_id = c.id
JOIN (
  SELECT conversation_id, MAX(completed_at) AS max_at
  FROM tag_assigner_runs WHERE status = 'success'
  GROUP BY conversation_id
) x ON x.conversation_id = r.conversation_id AND x.max_at = r.completed_at
WHERE c.chatwoot_conversation_id IN (83, 207, 586, 808, 1044, 702);

-- Deal list membership for resolved universities
SELECT u.name, m.chatwoot_list_value,
       EXISTS(SELECT 1 FROM deal_awaiting_universities d WHERE d.university_id = u.id) AS deal_awaiting
FROM universities u
JOIN university_chatwoot_label_map m ON m.university_id = u.id
WHERE m.chatwoot_list_value IN (
  'Marmara Üniversitesi - Maltepe',
  'Sağlık Bilimleri Üniversitesi',
  'Kültür Üniversitesi',
  'Kent Üniversitesi - Taksim',
  'Atlas Üniversitesi'
);
```

---

## 8. What is NOT broken (avoid scope creep)

These were **correct** in the latest batch and should not regress:

- Full-context backfill (Spec 024) — transcripts present for graded leads
- Çapa Tıp mapping (migration 025) — not in this error set
- DOU Dudullu / Yeni Yüzyıl tıp class — not re-flagged in last 3 runs
- Gender extraction on clear answers — not in error set
- District-only guard (Cevizlibağ class) — not re-flagged

---

## 9. Open questions for product/ops

1. **Deal list hygiene:** Which of the 36 `deal_awaiting_universities` rows are still truly pending vs now live? Who owns periodic audit?
2. **`fiyat-soruyor` lifecycle:** Should the label exist **at any point** in a serviced conversation, or only while sales still owes a price? Current prompt allows apply-then-remove; business may want **never apply if bot already sent Drive pricing**.
3. **Deterministic vs LLM for fiyat/deal_awaiting:** Is ops open to Router post-checks (regex on bot messages) for these two labels? Would reduce LLM variance significantly.

---

## 10. Appendix — error count math

Latest graded batch: **11 conversations**, **5 flagged** (~45% conversation-level error rate on errors-only grading). All 5 map to the 3 modes above with no other label/attribute complaints from business review.

Prior prompt work reduced errors from an earlier ~30% decision-level failure rate (Hatice/eylul/Sibel class) to this narrower tail. **Remaining work is structural (deal_awaiting) + LLM discipline (fiyat) + alias gaps (university).**

---

*End of handoff. For implementation sequencing, see recommended P0→P2 order in §6.*
