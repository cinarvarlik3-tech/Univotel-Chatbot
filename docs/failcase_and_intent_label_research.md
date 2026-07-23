# Fail-Case Root Causes + Intent/Identity Label Research

**Date:** 2026-07-20 · **Basis:** run-2 accuracy report
([results/20-07-2026_04.23_50_tagassigner-accuracy.md](../accuracy_optimization/tagassigner/results/20-07-2026_04.23_50_tagassigner-accuracy.md)).
**Method:** systematic-debugging (root cause before fixes). All root causes below were
**verified at the source** (code read + live DB/canonicalizer reproduction), not theorized.
**No working code was changed** — this is research + proposed fixes only.

---

## 0. The one cross-cutting theme

Every high-frequency error class traces to the **same architectural gap**: a label/attribute
with a *deterministic ground truth available* is left to the **LLM to guess**, with **no Router
cross-check**. Where the Router already computes deterministically (`info-check`,
`fiyat-soruyor`, `deal_awaiting`, university-via-canonicalizer) accuracy is ~100% and stable.
Where it doesn't (`hizmet-veremiyoruz`, `gender`, identity), the LLM misfires and nothing
catches it. **The single highest-leverage direction is to extend Router-side determinism to
these three.**

---

## 1. The 8 wrong conversations — verified root cause + fix

### 1.1 berkan (924) — `ogrenci` wrong **and** `Erkek` wrong (2 errors)

**Evidence:** LLM raw = `labels:[universitede,ogrenci,erkek], gender:Erkek`. Lead's only inbound
content: the widget starter ("Üniversitem: İstanbul Teknik Üniversitesi") + "Maşallah
fiyatlara bak" + "teşekkürler". The lead **never answered** the bot's "Kız mı erkek mi?"
question. The bot **did** send *"Academia Seyrantepe … erkek öğrenci yurdumuzdur"*.

- **`ogrenci` root cause:** the LLM applied `ogrenci` on the widget template alone — a **direct
  violation** of the prompt's own rule ("the widget template is not persona evidence → no
  `ogrenci`", prompt lines 187–196). LLM-layer adherence failure.
- **`Erkek` root cause (confirmed):** gender is proposed by the LLM from the **entire
  transcript including bot messages**, and `_merge_gender`
  ([app/tagassigner/attribute_merger.py](../app/tagassigner/attribute_merger.py)) accepts it
  with **no inbound-only guard** (unlike university, which scans inbound messages only). So the
  bot's "**erkek** öğrenci yurdumuzdur" pitch text contaminated gender. This is your exact "if a
  salesperson message has the word 'Erkek'" hypothesis — **confirmed**. It is a systemic gap,
  not a one-off: any lead who receives a gendered dorm suggestion is exposed.

**Fixes (proposed):**
1. **Inbound-only gender guard (primary):** mirror the university `extract_*_from_messages`
   pattern — only accept a gender value if an **inbound** message contains an explicit gender
   statement (answer to the gender question: "erkek"/"kız"/"erkek öğrenci"/"kız öğrenci", or a
   self-statement). If no inbound gender signal, **withhold** gender regardless of the LLM's
   proposal. Fixes berkan's `Erkek`.
2. **Identity: deterministic self-enrollment/parent guard (see §3)** — with no self-enrollment
   keyword in inbound text, don't let `ogrenci` stand from the widget template alone.

---

### 1.2 emaan (559) — university written as MSGSÜ, should be İstanbul Kent

**Evidence (reproduced):** `canonicalize("Istanbul Kent University Beyoğlu")` → **MSGSÜ Fındıklı**
today; with the bare `beyoğlu` alias removed → **İstanbul Kent Üniversitesi Taksim** (correct).

- **Root cause (confirmed, and it's mine):** migration `027_campus_aliases.sql` added a bare
  `beyoğlu` → MSGSÜ campus alias. **Beyoğlu is a district** (MSGSÜ's Fındıklı campus sits in
  it), so "beyoğlu" now hijacks any lead who mentions the district. emaan named İstanbul Kent
  (also near Beyoğlu/Taksim) and got MSGSÜ. This is the exact district-collision class the
  canonicalizer's `DISTRICT_STOPLIST` exists to prevent — my alias bypassed it. **This is a
  regression introduced by WS2.**
- **English is NOT the culprit here:** "university" is already in `normalize()`'s suffix list,
  so "Istanbul Kent University" → "istanbul kent" → resolves to İstanbul Kent correctly once
  `beyoğlu` is gone. (Broader English support is a separate, smaller issue — see §6.)

**Fix (proposed, high confidence):** delete the bare `beyoğlu` alias (keep `fındıklı` /
`fındıklı kampüsü`). Optionally add `beyoğlu` to `DISTRICT_STOPLIST` so it can never be
re-added as a bare campus alias. Reproduction shows this alone fixes emaan.

---

### 1.3 Bülent Öztürk (1134) — `ilgilenmiyor` wrong

**Evidence:** LLM raw = `labels:[ogrenci_cinsiyet, ilgilenmiyor]`. Transcript shows sustained
engagement — asks price, location ("cevizlibağa yakın mı"), room type, and "çamaşır makinesi
var mı" (washing machine). **No disinterest, no price objection, no "anlaştık".**

- **Root cause:** the prompt defines `ilgilenmiyor` as **explicit** disinterest ("severe price
  objection, 'ilgilenmiyorum', 'zaten bir yerle anlaştık'", prompt line 245). The LLM applied
  it to an engaged-but-inconclusive conversation → **over-application**, ignoring "explicit".
  LLM-layer.

**Fix (proposed):** endorse your own suggestion — **make `ilgilenmiyor` human-only** (move it
to the human-terminal tier, like `kayıp`/`sozlesme-imzalandi`). It is near-terminal and
commercially sensitive (falsely marking a live lead "not interested" can suppress follow-up).
The bot demonstrably can't apply it with precision. **Trade-off:** the bot also won't
auto-apply it when it *is* correct (e.g. emaan's genuine price mismatch) — but for a
near-terminal label, precision >> recall, and a human can add it. If you'd rather keep it
bot-scoped, the weaker alternative is a Router keyword-gate (only allow it when inbound text
contains an explicit disinterest phrase).

---

### 1.4 İskender Aga (1154) — İstanbul Üniversitesi withheld

**Evidence (reproduced):** `canonicalize("İstanbul üniversitesi Amerikan Dili edebiyatı …")` →
`PARENT_ONLY`. İstanbul Üni is multi-campus and "Amerikan Dili edebiyatı" doesn't resolve to a
campus. **A plain "İstanbul Üniversitesi" list value EXISTS** (confirmed).

- **Root cause:** the deferred "RC-U4" class — multi-campus parent with no resolvable campus →
  withhold. But here a **plain parent list value is available and unused.**

**Fix (proposed — this is your "write it if the exact name is present" idea, made precise):**
when `canonicalize` returns `PARENT_ONLY` **and** the parent has a plain (campus-less) Chatwoot
list value, **write the plain value** instead of withholding. Safe because it only fires when
the lead named the institution and a campus-agnostic value exists; the anti-hallucination
guarantee holds (we write only what the lead actually named — the institution). Fixes İskender.
Does **not** over-write when a campus *is* resolvable (that path returns `CAMPUS` first).

---

### 1.5 Nuray (1055) — Boğaziçi withheld (different from İskender!)

**Evidence (reproduced):** `canonicalize("Boğaziçi Üniversitesi")` → `PARENT_ONLY`, and **NO
plain "Boğaziçi Üniversitesi" list value exists** (only "Boğaziçi - Ana Kampüs" and "Boğaziçi -
Anadolu Hisarı").

- **Root cause:** same multi-campus withhold, but Nuray **cannot** be fixed by §1.4's
  plain-value rule — there is no plain value to write.

**Fix (proposed — needs a product call):** either (a) add a plain "Boğaziçi Üniversitesi" →
Ana Kampüs list value (treat the main campus as the institution default), or (b) a general
"single **dominant/main** campus" default when the lead names a multi-campus parent with no
campus. (a) is lower-risk and data-only. Note this is a genuine judgment call — writing
Ana Kampüs for a bare "Boğaziçi" is a mild assumption (most Boğaziçi students mean the main
campus, so it's usually right).

---

### 1.6 A.Kaya (977) — `universitede` missing (the "tricky" one)

**Evidence:** LLM raw this run = `labels:[veli]` only (no `universitede`). A.Kaya is a **parent**
("Kızım için Biruni üniversitesine en yakın yer") whose **daughter** is at Biruni. University is
now correctly written (Biruni). Last run had `universitede`; this run doesn't.

- **Root cause (medium confidence — genuine taxonomy ambiguity):** the prompt defines
  `universitede` as "**The lead** is studying at university." For a **veli**, the *lead* (parent)
  is **not** studying — the *daughter* is. So the LLM has a defensible reading that `universitede`
  shouldn't apply to a parent. The instability across runs (present last time, absent now) shows
  the LLM itself is unsure. This is a **definition gap**, not a clean bug.

**Fix (proposed):** decide and encode whether academic-phase labels (`universitede`, `1-sinif`,
…) describe the **student being housed** (daughter) or the **texter**. The rest of the system
already treats `university`/`gender` as "the student who will stay" even for a veli (prompt line
45). Making `universitede` consistent with that — *the housed student is at university* — is the
coherent choice, and is **deterministically derivable**: if a concrete university is resolved
for the conversation, `universitede` (or a more specific year label) applies. A Router rule
"concrete university resolved ⇒ ensure `universitede` present unless a year-specific label is"
would fix A.Kaya and remove the instability. (Low urgency — you flagged it as marginal.)

---

### 1.7 Sıla (707) — `veli` wrong (student mislabeled parent)

**Evidence:** LLM raw = `labels:[veli, 3-sinif, ilgilenmiyor]`. Lead: "Kız öğrenci",
"**2.sınıfı bitirdim** yaz stajı" (first-person self-enrollment). **Same error in run 1** — so
it's **systematic, not drift.**

- **Root cause:** LLM **over-applies `veli`**, ignoring the prompt's rule that a first-person
  enrollment statement ("2. sınıftayım", "okuyorum") = `ogrenci`, and `veli` requires an
  explicit child reference (prompt lines 210–223). The "staj" (internship) context likely
  nudges the model toward "graduate/parent". LLM-layer, reproducible.

**Fix (proposed):** deterministic identity guard (§3) — a first-person enrollment/year phrase
in inbound text forces `ogrenci` and blocks `veli`. Fixes Sıla and run-1 Görkem.

---

### 1.8 İbrahim (1359) — `hizmet-veremiyoruz` wrong + `deal_awaiting` missing

**Evidence (all verified):**
- LLM raw = `labels:[universitede, hizmet-veremiyoruz, ogrenci], uni:İstanbul Aydın Üniversitesi`.
- İstanbul Aydın **is in İstanbul** (private uni; "Aydın" is the founder's name, not the city).
- İstanbul Aydın **IS on the `deal_awaiting_universities` list** (verified).
- `has_any_serviceable_property(İstanbul Aydın)` = **True** (1 *female* hotel; **0 male**).
- İbrahim's gender = **unknown**. `apply_deal_awaiting(aydın, gender=None, …)` returns **no
  deal_awaiting** — verified live.

- **`hizmet-veremiyoruz` root cause (confirmed):** it is **LLM-only with NO Router cross-check**
  (grep confirms it's just a LIST_1 label; nothing in the Router validates it against the
  resolved university). The LLM misread "Aydın Üniversitesi" as the *city* of Aydın (out-of-
  city) and applied it — **while simultaneously** the canonicalizer resolved a valid **İstanbul**
  list value. These are contradictory and nothing caught it. The prompt even says
  hizmet-veremiyoruz requires "no value in the İstanbul list applies" (line 249) — but there's no
  enforcement.
- **`deal_awaiting` missing root cause (confirmed):** **unknown gender.** With gender unknown,
  serviceability falls back to "any property exists" (conservative), and İstanbul Aydın has a
  *female* property → treated as covered → deal_awaiting suppressed. Had gender been known =
  male (İbrahim is male, said "okuyorum"), `find_hotels_by_gender_and_university(male, aydın)` =
  0 → not serviceable → deal_awaiting **would** fire.

**Fixes (proposed):**
1. **Router guard for `hizmet-veremiyoruz` (primary, high confidence):** strip any LLM
   `hizmet-veremiyoruz` when the resolved university is a valid **İstanbul list value**. Better
   still, **compute it deterministically** from the `out_of_city_universities` table (which
   exists) — apply iff the resolved university is out-of-city; otherwise never. This removes LLM
   guessing for a label that has crisp ground truth, mirroring `deal_awaiting`.
2. **`deal_awaiting`:** once #1 stops the false hizmet-veremiyoruz, deal_awaiting still needs
   **gender** to fire correctly. İbrahim's gender was unrecoverable from his messages (he never
   stated it). This is a coverage limit, not a bug — but it argues for the gender-capture
   improvements in §2 and for revisiting whether an unknown-gender lead at a deal_awaiting
   university with **only opposite-inventory** should still be flagged (a product call).

---

## 2. Intent labels — how to make them reliably better

`hizmet-veremiyoruz` and `deal_awaiting` both key off the **resolved university**, which the
system already knows deterministically. **Stop letting the LLM decide serviceability.**

**Recommended architecture (extends the proven `deal_awaiting` pattern):**
- **`hizmet-veremiyoruz` → fully Router-computed:** apply iff resolved university ∈
  `out_of_city_universities`; **strip** any LLM proposal otherwise. Ground truth is a table
  lookup — the LLM should have zero say. Kills İbrahim-class errors and the whole "typo/ambiguous
  name → wrongly out-of-city" risk.
- **`ilgilenmiyor` → human-only** (§1.3), or Router keyword-gate. It's near-terminal; bot
  precision is the priority.
- **`deal_awaiting`:** already Router-computed and correct in principle; its accuracy is now
  **gated by gender coverage** (§1.8). Improve gender capture (§2-gender below) and it improves
  automatically.

This converts the three "intent/serviceability" labels from *LLM-guessed* to *data-derived*,
which is exactly where the system is already at ~100%.

---

## 3. Identity (`ogrenci` / `veli`) — how to make it better

**The pattern (from both runs):** the LLM errs in **both** directions — over-applies `ogrenci`
on weak signal (berkan: widget only) **and** over-applies `veli` on clear students (Sıla, run-1
Görkem). The prompt rules are already correct and detailed; the model just doesn't adhere. So
prompt-only tweaks are necessary but **not sufficient**.

**Recommended: a deterministic identity guard, computed from INBOUND text (like fiyat-soruyor).**
High-precision, keyword-anchored, applied by the Router:
- **Force `ogrenci`** when inbound text contains a first-person enrollment/year statement:
  `okuyorum`, `X'te okuyorum`, `N. sınıf(tay)ım`, `N. sınıfı bitirdim`, `hazırlık okuyorum`,
  `kendim için`, `ben kalacağım`, `yeni yerleştim`. → fixes Sıla, Görkem.
- **Force `veli`** when inbound text contains explicit parent reference: `oğlum/kızım/çocuğum/
  öğrencim için`, `velisiyim/annesiyim/babasıyım`. → matches A.Kaya (correctly veli).
- **Block/withhold identity** when the ONLY signal is the widget template or a bare
  location/gender/price question (no first-person enrollment, no child reference). → fixes
  berkan's spurious `ogrenci`.
- Where none of these fire, fall back to the LLM (genuinely ambiguous cases).

This is the "determinism where applied" principle again: the *clear* identity cases (which are
where the LLM flips) become deterministic; only the truly ambiguous middle is left to the model.

**Prompt improvements (do alongside, cheap):** add the exact observed failures as negative
few-shot examples — Sıla's "2.sınıfı bitirdim yaz stajı" → `ogrenci` (staj does not imply
parent/graduate); berkan's widget-only → **no** identity label.

**Gender capture (helps identity, deal_awaiting, and gender accuracy at once):** add an
inbound-only gender guard (§1.1) AND consider a lightweight Router scan for the explicit
gender-answer pattern so a "Kız mı erkek mi?" → "erkek" exchange is captured deterministically
and can't be contaminated by dorm-suggestion text.

---

## 4. Responses to your three proposed fixes

| Your idea | Verdict | Detail |
|---|---|---|
| İskender: "enlarge the phrase gate — if an exact uni name like İstanbul Üniversitesi is present, write it" | ✅ **Adopt (as §1.4)** | Precise form: on `PARENT_ONLY`, if the parent has a plain list value, write it. İstanbul Üni has one. Safe. |
| Bülent: "remove `ilgilenmiyor` from the bot's scope (salesperson-only)" | ✅ **Adopt (§1.3)** | Well-justified — near-terminal, bot can't apply with precision. Small recall cost. |
| İbrahim: "should be `deal_awaiting`, not `hizmet-veremiyoruz`" | ✅ **Right diagnosis** | hizmet-veremiyoruz is a clean fix (Router guard, §1.8-1). deal_awaiting will fire once gender is known; the miss was gender-driven, not a deal_awaiting bug. |

---

## 5. What else I think is important

1. **Regression I introduced:** the bare `beyoğlu` alias (emaan). Fix promptly (§1.2) — it's a
   *wrong write*, worse than a withhold, and will hit any Beyoğlu-district lead.
2. **Gender contamination is systemic**, not one lead — it will recur on every gendered dorm
   suggestion. Prioritize the inbound-only gender guard.
3. **The exception-grading ceiling:** these numbers are an *upper bound* on accuracy (missing
   labels the human doesn't notice aren't counted). For lead-quality / Meta conclusions you need
   a small **fully hand-labeled gold set**, not just exception grading (see §7).
4. **Re-used sample:** run 2 re-scored ~the same 50 leads as run 1, so the run-1→run-2
   improvement (78%→84%) is real but measured on an overlapping sample. A fresh import is needed
   for a clean independent read.

---

## 6. English-language support (raised on Farhan/emaan)

Partial support already exists: `normalize()` strips the "university"/"uni" suffix, so
"Istanbul Kent University" → "istanbul kent" resolves correctly (verified). The real gaps are
(a) English **campus/faculty** words and word-order ("Kent university istanbul" resolves, but
some orderings don't), and (b) English intent/identity phrasing (emaan's missing `ogrenci` —
which you asked to exclude). Recommendation: treat English as a **later, separate workstream**;
most of the current English "misses" are actually the district-collision (emaan) or multi-campus
withhold (Farhan) issues above, not language per se.

---

## 7. Ideal sample size for the next run

Two different needs, two different answers:

**A. Headline accuracy (run-correctness, attribute rates).** At p≈0.84, the Wilson half-width
is `≈ 1.96·√(p(1-p)/n)`:
- n=50 → **±10 pts** (current — too wide to detect a real improvement).
- **n=150 → ±6 pts**, n=200 → ±5 pts, n=385 → ±3.5 pts.
- **Recommendation: 150–200** for routine accuracy tracking. This is the sweet spot — meaningful
  tightening without excessive grading effort.

**B. Intent / identity / lead-quality labels (what you'd show Meta).** These are **rare** — in
this run identity labels appeared in ~7/50 (14%), `ilgilenmiyor` in 3, `hizmet-veremiyoruz` in a
handful. Precision on a label needs ~30–50 instances of that label to get to ±10–12 pts. At
~14% prevalence that means **~350–500 conversations**, or — much cheaper — **stratified
oversampling**: deliberately include conversations that carry disinterest / parent / out-of-city
/ price-objection signals so each rare label reaches n≈30+ without grading 500 random chats.
- **Recommendation:** for lead-quality claims, either **400+** random **or** ~150 random **+ a
  targeted oversample** of the rare-label conversations, **plus a ~50-conversation fully
  hand-labeled gold set** to escape the exception-grading recall ceiling.

**Bottom line:** **200** for the next general run (independent, freshly imported); go to
**~400 or stratified + a 50-gold subset** specifically before you use the labels to judge Meta's
lead quality.

---

## 8. Prioritized next steps (proposed — none implemented)

1. **Delete the bare `beyoğlu` alias** (fixes emaan; undoes my regression). Data-only, minutes.
2. **Router-compute `hizmet-veremiyoruz`** from `out_of_city_universities` + strip LLM
   proposals on in-city unis (fixes İbrahim; kills a whole error class). Code.
3. **Inbound-only gender guard** (fixes berkan gender; systemic). Code.
4. **Deterministic identity guard** from inbound self-enrollment/parent keywords (fixes Sıla,
   Görkem, berkan's `ogrenci`). Code + prompt negatives.
5. **`ilgilenmiyor` → human-only** (fixes Bülent). Config/registry.
6. **Plain-parent-value on `PARENT_ONLY`** (fixes İskender; helps any multi-campus parent with a
   plain value). Code.
7. **Boğaziçi main-campus default / plain value** (fixes Nuray). Product call + data.
8. **`universitede` for the housed student even when veli** (fixes A.Kaya; low urgency). Prompt
   or Router rule.
9. **Next accuracy run at n=200, freshly imported**; a 50-conversation gold set before any Meta
   lead-quality claim.
