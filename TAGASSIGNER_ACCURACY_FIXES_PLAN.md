# TAGASSIGNER_ACCURACY_FIXES_PLAN.md

**Status:** Spec — ready to implement. Self-contained for a newly-onboarded engineer/LLM.
**Date:** 2026-07-20.
**Origin:** Root-cause research on the run-2 accuracy report
([accuracy_optimization/tagassigner/results/20-07-2026_04.23_50_tagassigner-accuracy.md](accuracy_optimization/tagassigner/results/20-07-2026_04.23_50_tagassigner-accuracy.md))
and [docs/failcase_and_intent_label_research.md](docs/failcase_and_intent_label_research.md).
Companions: [DRIFT_SAVE_PLAN.md](DRIFT_SAVE_PLAN.md), [UNIVERSITY_ACCURACY_PLAN.md](UNIVERSITY_ACCURACY_PLAN.md).

This spec fixes the 8 wrong conversations from the run-2 grading and hardens three label
classes. **Do not change behavior beyond what is written here.** Every fix below was verified
at the source (code read + live DB/canonicalizer reproduction) during the research phase.

---

## 0. Branch & commit strategy (READ FIRST — non-negotiable)

The work is split so the safe fixes can ship independently of the experimental "prove
otherwise" model, and so the current model can be restored without losing the safe fixes.

- **Commit A — "riskless fixes"** (§2). Deterministic/data fixes. **Commit this on the CURRENT
  branch** (`TagAssigner-University-Capture-Optimization-Attempt` or whatever is checked out
  now). One commit.
- **Commit B — "Prove Otherwise model"** (§3). The LLM-proposes → Router-vetoes logic for
  identity and `ilgilenmiyor`. **Do NOT put this on the current branch.**
  1. First land Commit A on the current branch.
  2. Create a new branch **`Prove Otherwise Optimization Attempt`** off the current branch
     (i.e. off the tip that already contains Commit A).
  3. Commit B goes on that new branch, as **one** commit.

Result:
- Current branch = Commit A only (riskless fixes; the "current model").
- `Prove Otherwise Optimization Attempt` = Commit A + Commit B (riskless + experimental).
- Rolling back to the current model = stay on / return to the current branch; the riskless
  fixes are never lost.

Do not squash A and B together. Do not put B on the current branch.

---

## 1. Background: the 8 fail cases and the organizing principle

| # | Lead (cw) | Symptom | Root cause (verified) | Fix | Commit |
|---|---|---|---|---|---|
| 1 | berkan (924) | `ogrenci` + `Erkek` both wrong | `ogrenci` from widget only; gender from **bot pitch text** ("…erkek öğrenci yurdu") — no inbound-only guard | Gender inbound guard (A3) + identity veto/widget-strip (B1) | A + B |
| 2 | emaan (559) | Univ. written MSGSÜ, should be İstanbul Kent | **Regression:** bare `beyoğlu` alias (a district) added in migration 027 hijacks any Beyoğlu mention | Delete alias + stoplist (A1) | A |
| 3 | Bülent (1134) | `ilgilenmiyor` wrong | LLM over-applied to an **engaged** lead (asked price/room/washing machine) | `ilgilenmiyor` engagement-veto (B2) | B |
| 4 | İskender (1154) | İstanbul Üni withheld | Multi-campus `PARENT_ONLY`; plain "İstanbul Üniversitesi" value exists but unused | Curated default campus (A4) | A |
| 5 | Nuray (1055) | Boğaziçi withheld | Multi-campus `PARENT_ONLY`; **no** plain Boğaziçi value | Curated default campus (A4) | A |
| 6 | A.Kaya (977) | `universitede` missing | Taxonomy ambiguity (veli whose child studies) | **Deferred** (§5) | — |
| 7 | Sıla (707) | `veli` wrong (is a student) | LLM over-applies `veli` despite "2.sınıfı bitirdim" | Identity contradiction-veto (B1) | B |
| 8 | İbrahim (1359) | `hizmet-veremiyoruz` wrong; `deal_awaiting` missing | hizmet-veremiyoruz is LLM-only, no geo cross-check; İstanbul Aydın is **in-city**. deal_awaiting suppressed by a **stale `hotel_accessible_universities` row** (data) | hizmet-veremiyoruz geo-only (A2); deal_awaiting data cleanup **deferred** (§5) | A |

**Organizing principle (why each fix uses the mechanism it does):**

| Ground truth is… | Mechanism | Labels/fields here |
|---|---|---|
| A pure **data lookup** | **Fully Router-computed**, LLM stripped | `hizmet-veremiyoruz` (geography), `deal_awaiting` (already so) |
| **Language judgment** with detectable hard contradictions | **LLM proposes → Router vetoes on contradiction** ("prove otherwise") | identity, `ilgilenmiyor` |
| A value that must come from the **lead, not the bot** | **Inbound-only source guard** | `gender` |
| A deterministic name→value mapping | **Curated data** | university default campuses |

---

## 2. COMMIT A — riskless fixes (current branch)

### A1 — Remove the `beyoğlu` alias regression (fixes emaan)

**Root cause:** migration 027 added a bare `beyoğlu` → MSGSÜ Fındıklı campus alias
(`university_id = 82136f33-2b29-4830-ae0a-46cd8bd4bb3c`). Beyoğlu is a **district**; MSGSÜ's
Fındıklı campus is in it, so "beyoğlu" now matches MSGSÜ and hijacks any lead who mentions the
district. Verified: `canonicalize("Istanbul Kent University Beyoğlu")` → MSGSÜ today; with the
alias removed → **İstanbul Kent Üniversitesi Taksim** (correct).

**Do:**
1. New migration `migrations/028_remove_beyoglu_alias.sql` (idempotent):
   `DELETE FROM university_aliases WHERE alias = 'beyoğlu' AND university_id = '82136f33-2b29-4830-ae0a-46cd8bd4bb3c'::uuid;`
   Keep `fındıklı` and `fındıklı kampüsü` (those are real campus names, not districts).
2. Add `"beyoglu"` to `DISTRICT_STOPLIST` in
   [app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py)
   (normalized form is ascii-folded — use `"beyoglu"`) so a bare Beyoğlu token can never again
   be treated as a university signal, and so `docs/alias_collision_check.py` intent is enforced.
3. Apply migration 028 to the DB.

**Acceptance:** `canonicalize("Istanbul Kent University Beyoğlu")` and
`"Kent university istanbul beyoğlu"` resolve to İstanbul Kent (or `PARENT_ONLY`/none — **never**
MSGSÜ). No previously-correct MSGSÜ lead regresses (Görkem 1328 / Bilinmeyen 920 still resolve
to MSGSÜ via `fındıklı`/token-containment).

---

### A2 — `hizmet-veremiyoruz` becomes Router-computed from geography only (fixes İbrahim's wrong label)

**Decision (locked):** `hizmet-veremiyoruz` means **"the lead's university is outside İstanbul."**
Geography and nothing else — **no gender, no inventory/serviceability consideration.** It must
be **fully Router-computed**; the LLM gets no say.

**Root cause:** today it is LLM-only (a `LIST_1_USABLE` label in
[app/tagassigner/label_resolver.py](app/tagassigner/label_resolver.py)) with **no Router
cross-check**. İstanbul Aydın Üniversitesi is in İstanbul (private uni; "Aydın" = founder, not
the city), resolved to a valid İstanbul list value, yet the LLM still applied
`hizmet-veremiyoruz`. Nothing corrected it.

**Do (mirror the `fiyat-soruyor` / `deal_awaiting` Router-computed pattern):**
1. **Strip the LLM's proposal** always. Add `strip_llm_hizmet_veremiyoruz(labels)` to
   `label_resolver.py` (copy `strip_llm_fiyat_soruyor`), and call it in the Router's strip
   chain in [app/tagassigner/router.py](app/tagassigner/router.py) alongside the existing
   `strip_llm_fiyat_soruyor` / `strip_gemini_deal_awaiting` / `strip_gemini_info_check`.
2. **Compute deterministically.** Add `compute_hizmet_veremiyoruz(...)` (new module
   `app/tagassigner/hizmet_veremiyoruz.py`, or extend an existing helper). Rule:
   - If the Router resolved a concrete **İstanbul** `university_id` (i.e. the university
     canonicalizer produced a real İstanbul university) → **do NOT apply** (it's in-city).
   - Else, scan the lead's **inbound** text (reuse
     `extract_university_phrase_from_messages` from the canonicalizer, or the same inbound
     concatenation) with `match_out_of_city(phrase, out_of_city_unis)` from
     [app/layers/matching.py](app/layers/matching.py). Load the list via the existing
     `out_of_city_universities` table (148 rows; columns `id, name, short_name, city`). If it
     matches an out-of-city university → **apply** `hizmet-veremiyoruz`.
   - Otherwise (ambiguous / `bilinmiyor`, no out-of-city match) → **do NOT apply** (the prompt
     already says a failed/ambiguous lookup is not grounds for it).
3. Wire the compute step into the Router next to `compute_fiyat_soruyor` /
   `apply_deal_awaiting`.

**Acceptance:** İbrahim (İstanbul Aydın, in-city) → **no** `hizmet-veremiyoruz`. A lead naming a
genuinely out-of-city university (e.g. cw 652 "Eskişehir Osmangazi Üniversitesi") → **keeps**
`hizmet-veremiyoruz`. The LLM's raw `hizmet-veremiyoruz` proposal can never survive on an
in-city university.

> Note: İbrahim's **missing `deal_awaiting`** is a **data** problem (stale
> `hotel_accessible_universities` row for İstanbul Aydın), deferred to §5 by product decision.
> `deal_awaiting` logic stays **conservative and unchanged**.

---

### A3 — Gender: inbound-only source guard (fixes berkan's `Erkek`)

**Root cause:** gender (`ogrenci_cinsiyet`) is proposed by the LLM from the **whole transcript
including bot messages**, and `_merge_gender` in
[app/tagassigner/attribute_merger.py](app/tagassigner/attribute_merger.py) accepts it with no
source check. The bot's "…**erkek** öğrenci yurdumuzdur" pitch text contaminated berkan's
gender (he never stated it).

**Do (mirror the university inbound-only authoritative pattern):**
1. Add a helper `inbound_gender_signal(messages) -> Optional[str]` (returns `"male"`/`"female"`/
   `None`) that scans **inbound messages only** for an explicit gender statement about the
   student who will stay:
   - Female: standalone `kız`, `kız öğrenci`, `kadın`, `bayan`, `kızım`, `kız çocuğu`, `kızım için`.
   - Male: standalone `erkek`, `erkek öğrenci`, `bay`, `oğlum`, `erkek çocuğu`, `oğlum için`.
   - (For a veli, "kızım/oğlum" legitimately reveal the housed **student's** gender — include
     them.)
   - Match on normalized tokens; require the token to be the lead's own inbound text.
2. In the Router, thread this signal into `merge_attributes` / `_merge_gender`: **only accept a
   bot-proposed gender if `inbound_gender_signal` corroborates it** (or agrees). If there is no
   inbound gender signal, **withhold** gender regardless of the LLM's proposal (treat as
   `bilinmiyor`). Human-set gender still wins (existing guard unchanged).

**Acceptance:** berkan (no inbound gender statement; bot said "erkek öğrenci yurdu") → gender
**withheld**. A lead who answered "Kız mı erkek mi?" → "erkek" (inbound) → gender `Erkek`. A
veli who said "kızım için" → gender `Kız`.

---

### A4 — University curated default campuses (fixes İskender + Nuray)

**Decision (locked):** For a **small curated set** of universities, a bare parent mention with
no campus resolves to a specified default campus. **Not a blanket rule** — most multi-campus
schools genuinely distribute students and must keep withholding (`bilinmiyor-kampus`).

Curated exceptions (v1):
| Parent | Parent `university_id` (parent_universities) | Default campus `university_id` | Resulting list value |
|---|---|---|---|
| İstanbul Üniversitesi → **Beyazıt** | `c51006fd-bbde-410d-1a06-8c92182baba9` | `bceb53ee-580f-4265-a27d-716dae21c9eb` | `İstanbul Üniversitesi` |
| Boğaziçi Üniversitesi → **Ana Kampüs** | `c19098e9-4f4e-52d6-2540-a16f01922824` | `ffa47477-7504-48b0-8e82-837da80aa646` | `Boğaziçi - Ana Kampüs` |

**Do:**
1. Add a curated map. Preferred: a small table
   `parent_university_default_campus (parent_university_id uuid PK, university_id uuid)` seeded
   via `migrations/029_parent_default_campus.sql` with the two rows above, loaded into the
   `UniversityUniverse` cache. (A frozen dict in the canonicalizer is an acceptable v1 shortcut
   for exactly two entries, but the table is preferred for extensibility.)
2. In `canonicalize()`
   ([app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py)),
   in the branch that currently returns `PARENT_ONLY`: **before** returning `PARENT_ONLY`, if
   the matched parent is in the curated map, return `CanonResult(CAMPUS, default_campus_id)`
   instead. This runs only when no campus was resolvable (the `CAMPUS` paths already win first),
   so a lead who *does* name a campus is unaffected.

**Acceptance:** `canonicalize("İstanbul üniversitesi Amerikan Dili edebiyatı bölümünde")` →
`CAMPUS` → `İstanbul Üniversitesi`. `canonicalize("Boğaziçi Üniversitesi")` → `CAMPUS` →
`Boğaziçi - Ana Kampüs`. A multi-campus school NOT in the map (e.g. bare "Bahçeşehir") still
returns `PARENT_ONLY`. A lead naming a specific İÜ/Boğaziçi campus still resolves to that
campus, not the default.

---

## 3. COMMIT B — "Prove Otherwise" model (new branch `Prove Otherwise Optimization Attempt`)

**The model:** the LLM makes the primary call; the Router runs a thin, deterministic layer that
**tries to prove the opposite** and overrides only when it finds a hard contradiction. This
preserves the LLM's judgment on the genuinely ambiguous middle while killing the specific,
provable errors. Both fixes below scan the lead's **inbound** text only.

Implement both as a new post-`resolve_labels` reconciliation step in the Router (after label
resolution, before the final label write), operating on the resolved label set. Keep the two
concerns in one module (e.g. `app/tagassigner/prove_otherwise.py`) so Commit B is cohesive.

### B1 — Identity contradiction-veto (fixes Sıla, berkan's `ogrenci`; recovers missed cases)

Use the **identity signal lexicon** in §4. Compute `hard_signal ∈ {ogrenci, veli, ogrenci-degil,
None}` deterministically from inbound text. Let `llm_identity` be the identity label currently
in the set (identity is mutually exclusive — at most one).

Rules, in order:
1. **Hard signal wins (flip / recover):** if `hard_signal` is not `None`, set the conversation's
   identity to `hard_signal` — remove any other identity label, add `hard_signal`. This both
   *flips* a wrong LLM call (Sıla: LLM `veli`, inbound "2.sınıfı bitirdim" → `ogrenci`) and
   *recovers* a missed one (cw 270 "okuyorum" with LLM `none` → `ogrenci`; cw 1362 "kız çocuğu
   kalacak" → `veli`).
2. **Widget-only strip (narrow, heuristic — the one piece to watch):** else, if
   `llm_identity` is set AND the lead's inbound content is **only** the widget `Üniversitem:`
   prefill + greetings + bare price/room/location/gender/thanks messages (no first-person
   enrollment token and no child reference anywhere), **strip** `llm_identity` → none. This is
   the berkan case (widget + "maşallah fiyatlara bak" + "teşekkürler"). Detect "widget-only" by
   removing the widget scaffold, greeting boilerplate, and the generic-question patterns in §4,
   then checking whether any lead-authored substantive content remains.
3. **Otherwise keep the LLM's call** (ambiguous middle, e.g. cw 1067 Mine "YKS ye yeni girdi,
   sonuç bekliyoruz" — implicit parent the LLM may or may not catch; do not touch).

Respect the identity mutex (`ogrenci`/`veli`/`ogrenci-degil`) — the step must leave at most one.

**Acceptance:** Sıla → `ogrenci` (not `veli`). berkan → no identity label. cw 270 → `ogrenci`;
cw 1362 → `veli`. cw 884 / 977 (explicit "kızım/oğlum için") → `veli` unchanged. cw 656/988/1050
etc. ("kız öğrenci" as a **gender** answer only) → **no** identity label (the lexicon must NOT
treat bare "kız/erkek öğrenci" as `ogrenci`).

### B2 — `ilgilenmiyor` engagement-veto (fixes Bülent)

**Decision (locked):** keep `ilgilenmiyor` **bot-scoped** (it is disinterest, not terminal), but
have the Router **disprove** a wrongful application by detecting active engagement — because
engagement is reliably detectable while implicit disinterest is not.

Rule: if the resolved label set contains `ilgilenmiyor` AND the lead's inbound text shows
**active engagement**, strip `ilgilenmiyor`. Engagement signals (inbound, any of):
- asks about price/room/amenities/logistics: `fiyat`, `ücret`, `kaç kişilik`, `oda`,
  `metrekare`, `çamaşır`, `mutfak`, `banyo`, `wifi`, `depozito`, `kontrat`;
- asks about location/branches: `kampüs`, `yakın`, `semt`, `lokasyon`, `şube`, `nerede`;
- asks about visiting/next steps: `gezmek`, `görmek`, `randevu`, `ne zaman`.

Keep `ilgilenmiyor` only when the lead expressed disinterest and shows no such engagement.

**Acceptance:** Bülent (asked price, location, "çamaşır makinesi var mı") → `ilgilenmiyor`
**stripped**. A lead with a genuine hard "ilgilenmiyorum / anlaştık" and no follow-up questions
→ keeps `ilgilenmiyor` (emaan-style severe-price cases are unaffected if no engagement follows).

---

## 4. Identity & generic-question lexicon (evidence-backed, from the 50-conversation corpus)

Match on `normalize()`d inbound text. These were derived from reading every conversation's
inbound messages; cw references are real examples.

**STUDENT (`ogrenci`) — first-person enrollment/attendance only the student could say:**
- `oku(yorum|dum)` / `okuyom` ("…üniversitesinde okuyorum" — cw 270, 1359)
- `[1-4]\.?\s*sınıf(tayım|tayim|ı bitirdim|ı okuyorum)` ("2.sınıfı bitirdim" — cw 707)
- `kampüsünde(yim)` ("Mimar Sinan Fındıklı kampüsündeyim" — cw 1328)
- `hazırlık okuyorum`, `kendim için`, `ben kalacağım`, `yeni yerleştim`, `yatay geçiş yapaca`,
  `erasmus`

**PARENT (`veli`) — explicit child reference or parent self-ID:**
- `(kız[ıi]m|oğlum|çocuğum|öğrencim)\b.*(için|kalacak|okuyor)` ("kızım için soruyorum" — cw 884, 977)
- `(kız|erkek)\s*çocuğu` ("Kız çocuğu kalacak" — cw 1362)
- `velisiyim|annesiyim|babasıyım|velisi`

**NOT-STUDENT (`ogrenci-degil`) — explicit non-student:**
- `çalışıyorum|çalışan biriyim|memurum|mezunum|öğrenci değilim`
- (staj context is NOT `ogrenci-degil` by itself — a current student can intern; see cw 707.)

**NEITHER / UNKNOWN (no identity label) — the default. Do NOT treat these as identity:**
- Widget prefill only: "Üniversitem: X", "…hakkında bilgi alabilir miyim? … Başvuru Kodu: …"
- First-person **search** verbs: `bak[ıi]yorum`, `arıyorum`, `bilgi alabilir miyim`,
  `öğrenmek istiyorum`, `soruyorum` (a parent and a student phrase these identically).
- **Bare gender answers** (critical trap — these are GENDER, not identity):
  `kız`, `erkek`, `kız öğrenci`, `erkek öğrenci` answering "Kız mı erkek mi?" (cw 656, 716, 886,
  988, 1020, 1050, 1113, 1126, 1261, 1279, 1300).
- Bare university name / price / room / location questions.

**Generic-question patterns** (used by B1 rule 2 "widget-only" detection — content that is NOT
persona evidence): greetings (`merhaba*`, `selam`, `teşekkür*`, `maşallah`), and the price/room/
location/visit question keywords listed in B2's engagement set. If, after removing the widget
scaffold + greetings + these generic questions, nothing lead-authored remains, treat as
widget-only.

**Precision requirement:** before shipping Commit B, run the B1/B2 detectors against the full
inbound-message corpus (the `messages` table, `message_type='inbound'`) and confirm they do not
misfire (e.g. "kız öğrenci" must not trigger `ogrenci`; "oğlum" in a non-parent context is rare
but check). Tune the regexes until precision on the corpus is clean. Do not ship unmeasured hard
rules.

---

## 5. Deferred / explicitly out of scope

- **A.Kaya `universitede` (cw 977):** taxonomy question — should `universitede` describe the
  **housed student** even when the texter is a parent? Not decided. Not in this spec.
- **`hotel_accessible_universities` data cleanup:** the stale İstanbul Aydın row (and likely
  others) wrongly reports serviceable inventory, suppressing `deal_awaiting`. A full audit was
  **explicitly deferred** by the product owner. `deal_awaiting` logic stays conservative and
  unchanged; do not touch it.
- **English / Azerbaijani (foreign-language) leads:** out of scope; post-launch workstream.
- **DRIFT_SAVE_PLAN.md work** (label/attribute drift): separate, unchanged.

---

## 6. Validation & testing

**Unit tests (add alongside code):**
- A1: `canonicalize` on emaan phrases → not MSGSÜ; MSGSÜ leads unregressed. Extend
  `tests/test_university_canonicalizer.py`.
- A2: `compute_hizmet_veremiyoruz` — in-city uni → absent; out-of-city → present; ambiguous →
  absent; LLM proposal always stripped. New test.
- A3: `inbound_gender_signal` — bot-text "erkek öğrenci yurdu" (outbound) → None; inbound
  "erkek" → male; "kızım için" → female. `_merge_gender` withholds when no inbound signal.
- A4: curated default campuses resolve; non-curated multi-campus still `PARENT_ONLY`; explicit
  campus still wins.
- B1/B2: table-driven tests over the §4 lexicon, including the negative cases (bare "kız
  öğrenci" ≠ `ogrenci`; engaged lead → `ilgilenmiyor` stripped).

**Deterministic per-conversation acceptance (primary — do this, it is sample-size-independent):**
reproduce each fix on the real flagged conversations exactly as the research did (load the live
universe / run the Router logic on the stored transcripts) and confirm:

| Lead (cw) | Expected after fix |
|---|---|
| emaan 559 | university = İstanbul Kent (Taksim), not MSGSÜ |
| İbrahim 1359 | no `hizmet-veremiyoruz` |
| berkan 924 | gender withheld; no `ogrenci` |
| İskender 1154 | university = İstanbul Üniversitesi |
| Nuray 1055 | university = Boğaziçi - Ana Kampüs |
| Sıla 707 | `ogrenci`, not `veli` |
| Bülent 1134 | no `ilgilenmiyor` |
| cw 270 / 1362 | `ogrenci` / `veli` recovered (B) |

**Full test suite** (`venv/bin/python3 -m pytest tests/ -q`) must stay green (currently 450
passing). Run `docs/alias_collision_check.py` after migration 028 → 0 hard failures.

**Next accuracy run:** do NOT reuse the current 50-lead cohort. **`sweepclean` + import a fresh,
independent set of n ≈ 200 conversations**, then run the harness. Rationale: at n=50 each
conversation is ~2 points and the run-1→run-2 comparison was confounded by reusing the same
cohort and a shifting flag list; the aggregate percentages are directional only. n≈200 gives
~±5-point headline CIs. (For any lead-quality / Meta-facing claim later, a larger stratified
sample + a ~50-conversation fully hand-labeled gold set is required — separate effort.)

---

## 7. File / function / table reference

- **Router flow:** [app/tagassigner/router.py](app/tagassigner/router.py) `apply_tagassigner_result` —
  strip chain (`strip_llm_fiyat_soruyor`, `strip_gemini_deal_awaiting`,
  `strip_gemini_info_check`) → `resolve_labels` → university override (`resolve_university_override`)
  → `merge_attributes` → `apply_info_check` → `compute_fiyat_soruyor` → `apply_deal_awaiting`.
  Add: `strip_llm_hizmet_veremiyoruz` (strip chain), `compute_hizmet_veremiyoruz` (near
  `compute_fiyat_soruyor`), the identity + `ilgilenmiyor` veto step (after `resolve_labels`),
  and the gender inbound signal into `merge_attributes`.
- **Labels registry:** [app/tagassigner/label_resolver.py](app/tagassigner/label_resolver.py) —
  `LIST_1_USABLE` (contains `hizmet-veremiyoruz`, `ilgilenmiyor`, identity labels), the
  `strip_llm_*` helpers to copy.
- **Canonicalizer:** [app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py) —
  `canonicalize` (add curated-default branch), `DISTRICT_STOPLIST` (add `beyoglu`),
  `extract_university_phrase_from_messages`, `UniversityUniverse`/`get_university_universe`.
- **Matching primitives:** [app/layers/matching.py](app/layers/matching.py) — `match_out_of_city`,
  `normalize`, `scan_entities_by_ngram`.
- **Attribute merge:** [app/tagassigner/attribute_merger.py](app/tagassigner/attribute_merger.py) —
  `_merge_gender`.
- **Deterministic-label references (patterns to copy):**
  [app/tagassigner/fiyat_soruyor.py](app/tagassigner/fiyat_soruyor.py) (`compute_fiyat_soruyor`),
  [app/tagassigner/deal_awaiting.py](app/tagassigner/deal_awaiting.py) (`apply_deal_awaiting` — leave unchanged).
- **Tables:** `university_aliases`, `university_chatwoot_label_map`, `parent_universities`,
  `university_parent_map`, `out_of_city_universities` (id, name, short_name, city),
  `hotel_accessible_universities` (do NOT touch — deferred).
- **Key IDs:** MSGSÜ Fındıklı campus `82136f33-2b29-4830-ae0a-46cd8bd4bb3c`; İÜ parent
  `c51006fd-…`, İÜ Beyazıt (plain "İstanbul Üniversitesi") `bceb53ee-580f-4265-a27d-716dae21c9eb`;
  Boğaziçi parent `c19098e9-…`, Ana Kampüs `ffa47477-7504-48b0-8e82-837da80aa646`; İstanbul
  Aydın `307a1973-4845-4c15-a940-57ece93de827` (deferred).
- **Migrations:** latest applied is `027`; new ones start at **`028`**.

---

## 8. Build order

**On the current branch (Commit A):**
1. A1 beyoğlu alias removal (migration 028 + stoplist) — apply + verify emaan.
2. A4 curated default campuses (migration 029 + canonicalize branch) — verify İskender/Nuray.
3. A2 hizmet-veremiyoruz Router-computed geo-only (+ strip) — verify İbrahim.
4. A3 gender inbound-only guard — verify berkan gender.
5. Full test suite green; collision check clean. **Commit A on the current branch.**

**Create branch `Prove Otherwise Optimization Attempt` off that commit, then (Commit B):**
6. Build the §4 lexicon + detectors; measure precision on the inbound corpus.
7. B1 identity contradiction-veto (+ widget-only strip + positive recover).
8. B2 `ilgilenmiyor` engagement-veto.
9. Full test suite green; per-conversation acceptance table passes. **Commit B on the new branch.**

Then run the fresh n≈200 accuracy sweep (§6) to measure.
