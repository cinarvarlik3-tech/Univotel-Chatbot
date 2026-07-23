# Problem Explanations 3 — TagAssigner 200-lead accuracy run (2026-07-22)

**Run:** `2026-07-22-sweep200` · **Command:** `./scripts/tag sweepEmpty --200`
**Sample:** 197 graded conversations · **Report:**
[accuracy_optimization/tagassigner/results/22-07-2026_18.27_197_tagassigner-accuracy.md](../accuracy_optimization/tagassigner/results/22-07-2026_18.27_197_tagassigner-accuracy.md)
**Feedback (flags):**
[accuracy_optimization/tagassigner/inputs/feedback_2026-07-22-sweep200.json](../accuracy_optimization/tagassigner/inputs/feedback_2026-07-22-sweep200.json)

Every root cause below was **reproduced at the source** (live DB + the actual canonicalizer /
router code on the stored transcripts), not inferred from the symptom. Where your written guess
matched the code it is marked ✅; where the code told a different story it is marked ⚠ and
corrected.

---

## 1. Methodology & scope (what was and wasn't counted)

**Processing check first (per policy).** The DB holds **201** conversations. Of those:

- **198** have ≥1 successful `tag_assigner_run` → eligible.
- **3 were NOT processed and are excluded entirely:** cw **414** (a *second* "Sude" — run
  **failed**), cw **548** ("Sevgi" — run stuck in **`processing`**), cw **1477** ("Saygın özcan"
  — **no run row**). None are counted as success or fail.
- **Nancy (cw 1189)** removed from the graded set per your instruction (English lead — "don't
  write as success or fail"). Final graded **n = 197**.

**Grading is by exception** (the harness contract): every field the run wrote that you did *not*
flag is treated as correct. Accuracy is therefore **mistaken operations ÷ operations actually
done** on the 197 processed leads — not ÷ the DB total, exactly as you asked.

**hotel_accessible_universities errors were excluded** (per policy). I verified each candidate
against the live table before excluding it — see §5.

**Two of your reported items were NOT errors** — the code proves the system was right (§6). They
were not flagged.

---

## 2. Headline numbers (the outputs you asked for)

| Metric | Value (Wilson 95% CI) |
|---|---|
| **Run correctness (D3)** — every graded field exactly right | **81.7%** [75.7–86.5] (161/197) |
| **General attribute correctness (D1)** — mean of university/gender/room A3 | **97.5%** |
| &nbsp;&nbsp;• University (final/Router layer, A3) | **92.9%** [88.4–95.7] (183/197) |
| &nbsp;&nbsp;• Gender (final, A3) | **99.5%** [97.2–99.9] (196/197) |
| &nbsp;&nbsp;• Room type `oda_tiipi` (final, A3) | **100.0%** (197/197) |
| **General label correctness (D2)** — LLM-owned micro-F1 | **93.6%** |
| &nbsp;&nbsp;• Router-owned micro-F1 | **97.3%** |
| **Identity** — precision-given-call (B2) | **65.0%** [49.5–77.9] (26/40) |
| &nbsp;&nbsp;• Identity recall (B3) / decision rate (B1) | 89.7% / 100.0% |
| **Wrong LLM-labels applied (C2)** | 8.9% [5.5–14.1] (15/169) |
| **Missing Router-labels (C3)** | 5.3% [2.1–12.8] (4/76) |
| **Preservation integrity (C5)** | ✅ 0 violations |

**Where the error mass is (read this if nothing else):**

1. **Identity over-application** is the single biggest quality hole — B2 precision **65%**. The
   LLM stamps `ogrenci`/`veli` off widget prefill and "kız/erkek öğrenci" *gender* answers. 11
   of the flagged leads are this. (Cluster C.)
2. **University campus/district alias collisions** drove **9 Router-broke** university errors
   (the LLM was right, the Router's deterministic override made it wrong). (Cluster A.)
3. Everything else is a handful each: hizmet-veremiyoruz city-name gap (3), deal_awaiting data
   gaps (4), one kapora leak, one interrogative-gender misread.

The Router still *nets* strongly positive on university (**+57 rescued vs 9 broke**) — the
override is a big win overall, but its collision aliases now cost more than they should.

---

## 3. Cluster A — University: canonicalizer alias / token collisions

The Router runs a deterministic canonicalizer over the lead's inbound text and, when it finds a
match, **overrides** the LLM's university guess (`resolve_university_override`, treated as
*authoritative*). That override is right 57 times and wrong 9 times here. All 9 are one of these
four collisions, each reproduced by running `canonicalize()` on the real phrase.

### A1 — bare `güney kampüs` / `güney yerleşkesi` → Boğaziçi (regression, migration 027)

**Proven:** `canonicalize("Bahçeşehir Üniversitesi güney kampüs")` → **Boğaziçi - Ana Kampüs**;
`canonicalize("medeniyet üniversitesi güney kampüs")` → **Boğaziçi - Ana Kampüs**.

[migrations/027_campus_aliases.sql](../migrations/027_campus_aliases.sql) added the **bare**
aliases `'güney kampüs'` and `'güney yerleşkesi'` → Boğaziçi Ana Kampüs. "Güney kampüs" (south
campus) is a **generic term** that Bahçeşehir, Medeniyet, Medipol and others all use — it is not
a Boğaziçi identifier. This is the **exact same bug class** as the `beyoğlu` regression you
already fixed in migration 028: a district/generic word aliased to one specific campus, hijacking
every lead who says it.

- **Affected:** Merve (1446), Öykü Nil (267). Both LLM-correct, Router-broke.
- **Fix:** delete the bare `güney kampüs` / `güney yerleşkesi` aliases (keep `rumeli hisarı` /
  `hisarüstü`, which *are* Boğaziçi-specific), and add `"guney kampus"` / `"guney yerleskesi"` to
  `DISTRICT_STOPLIST` so they can never again be a standalone university signal. Mirror the
  migration-028 pattern exactly. Run `docs/alias_collision_check.py` after.

### A2 — our own property names + district names read as universities

**Proven:** `canonicalize("Academic House Maltepe … Üniversitem: yeditepe")` → **Maltepe
Üniversitesi**; same for Şevval ("… Üniversitem: Marmara üniversitesi") and Döner ("Marmara
Maltepe kampüsü"), and Doruk's housing district ("Maltepe'den okula") → **Maltepe Üniversitesi**.

The canonicalizer scans the **entire inbound blob**, which includes the widget-injected **branch
name the lead pasted** ("Academic House **Maltepe**", "Academia Seyrantepe") and **districts the
lead names for housing** ("Maltepe'den"). "Maltepe" is both a district *and* a university, so the
token wins over the university the lead actually stated.

- **Affected:** Eyşan Akdağ (909, stated Yeditepe), Şevval Çetinkaya (1227, stated Marmara),
  Döner Demirci (1044, stated Marmara-Maltepe campus), Doruk Yıldırım (12, stated İÜ
  Konservatuvar). All LLM-correct, Router-broke.
- **Fix:** before university extraction, **strip our own property/branch names** (the hotels
  table already lists them — `Academic House …`, `Academia …`, `GK …`, `Keten Suites`) from the
  text, and add the university-colliding districts (`maltepe`, `seyrantepe`, `ataşehir`,
  `beyoğlu` already done) to `DISTRICT_STOPLIST`. A district may only feed **campus**
  disambiguation once a *parent* is already matched — never select the university on its own.

### A3 — bare `istanbul` (a city/location word) → İstanbul Üniversitesi / İstanbul Aydın

**Proven:**
- Murat Ertan (1288): `canonicalize("… Fiyat istanbul için … Beyazıt Kampüsü …")` → **İstanbul
  Aydın Üniversitesi** — the bare "istanbul" beat the unambiguous **"Beyazıt Kampüsü"** signal
  (which is İstanbul Üniversitesi). ✅ your "istanbul immediately matched" guess.
- HasretCan Görür (380): `canonicalize("… Çukurova üniversitesi Yumurtalık … İstanbul'da
  kalmak …")` → **İstanbul Üniversitesi** — "İstanbul'da kalmak" (I'll *stay* in Istanbul) read
  as the university, burying the lead's actual Çukurova.
- Filiz Ayhan (183): the early "İstanbul merkeze yakın" resolved to İÜ before she later said
  "İstanbul aydın üniversitesi"; the flow had `stopped`, so the correct İ.Aydın never
  overwrote. Same root token.

The A4 "curated default campus" fix (İÜ → Beyazıt) means a bare "istanbul" token that reaches the
İÜ parent now resolves to a **concrete** value instead of withholding — which is good when the
lead means the university, but harmful when "istanbul" is just the city.

- **Fix:** add bare `"istanbul"` (and `"istanbul merkez"`) to `DISTRICT_STOPLIST` — a lone
  city-name token must never select İÜ or İ.Aydın. Both universities must be matched by their
  **distinguishing** words ("üniversitesi" + "aydın", or an İÜ campus like "beyazıt"), never by
  the city they sit in. This is the direct extension of the beyoğlu decision to the city itself.

### A4 — short/ambiguous aliases fuzzy-collide (`iou`→Okan, `isik`→Işık) — regression

**Proven:** `canonicalize()` on Furkan's ("mimar sinan … yıldızda") and Enda's ("kent üni
kağıthane") phrases both return **Okan Üniversitesi**; Hazel's ("İstanbul Teknik Üniversitesi …
itüdeyiz") returns **Işık Üniversitesi - Maslak**.

The offending rows: Okan carries a **3-character** alias `'iou'`, and Işık carries `'isik'` /
`'ışık'` (4 chars). Aliases this short fuzzy-match unrelated tokens under the canonicalizer's
Levenshtein tolerance — the identical failure mode as beyoğlu/güney. Furkan was correct in prior
runs, so this is a **regression** (an alias added since).

- **Affected:** Furkan Aytaş (1168 → should be MSGSÜ - Beşiktaş), Enda Ceren İn (575 → should be
  Kent Üniversitesi - Taksim), Hazel Turan (1167 → İTÜ, campus unstated).
- **Fix:** run `docs/alias_collision_check.py` and purge/lengthen sub-5-char aliases; enforce
  **exact-match only (no Levenshtein) for aliases ≤ 4 chars** (the same length floor already used
  in the out-of-city 1-gram scan). Specifically audit `iou`, `isik`, `ışık`.

### A-bonus — deterministic PARENT_ONLY withhold discards the LLM's correct campus

**Proven:** Nihan Türedi (1119) "Bahcesehir un8versitesi besiktas" → canonicalizer reaches only
**PARENT_ONLY** (Bahçeşehir matched, campus unresolved) and withholds, even though the LLM
correctly produced **Bahçeşehir - Çırağan** (Beşiktaş = the Çırağan campus). Sami Süner (772) "İÜ
Cerrahpaşa …" → **PARENT_ONLY** (matched the İÜ parent; "Cerrahpaşa" never mapped to the
*İstanbul Üniversitesi Cerrahpaşa* list value), so it withheld the LLM's correct İÜC.

Because the deterministic mention is marked *authoritative*, a PARENT_ONLY result **overrides and
throws away** the LLM's more-specific, correct campus.

- **Fix (two parts):** (1) add the missing campus aliases — `beşiktaş` → Bahçeşehir Çırağan,
  and `cerrahpaşa` / `iü cerrahpaşa` → *İstanbul Üniversitesi Cerrahpaşa*. (2) Soften the
  override: when the deterministic scan yields only PARENT_ONLY, **keep the LLM's campus if it is
  a valid campus of that same parent** instead of withholding.

---

## 4. Cluster C — Identity over-application (the biggest label hole)

Identity precision-given-call is **65%** (B2). The confusion matrix shows the shape exactly: of
leads whose true identity is **none**, the LLM stamped `ogrenci` on **6** and `veli` on **5**;
plus it called 2 real `veli` leads `ogrenci`.

**Root cause (one mechanism, many leads):** the LLM infers identity from (a) the fixed-widget
prefill ("**Erkek öğrenci** için opsiyonlarınızı öğrenebilir miyim", "Academic House Beşiktaş Kız
Öğrenci Yurdu") and (b) the lead's answer to *our* gender question ("Kız mı erkek mi?" → "kız
öğrenci"). Neither is evidence that the **texter** is the student — "kız/erkek öğrenci" is a
**gender** fact about the person who will stay, not a persona of the person typing. ✅ this is
exactly the design gap you suspected on `merve` (1196): student/parent is a property of the
*resident*, and the bot has no rule enforcing that.

- **Unwarranted `ogrenci`:** Nesrin (1381), Bircan Savaş (1247), Selda (1059), Ayşe (929), Yusuf
  Çalbay (459), Nuriye Yücedağ (850).
- **Unwarranted `veli`:** Zehra Bayraktar (1318), Aysun (1272), Nuran Seyfioğlu (1038), "." (347).
- **Wrong direction (is a parent, called student):** Nazan (972 — "iki kardeşler" = her two
  kids), Gülhan Can Cofcof (899 — "sınava girdi çocuk, oraları yazacak").
- **staj lead called `ogrenci` (should be `ogrenci-degil` per your call):** merve (1196).

**This is precisely what Commit B ("Prove Otherwise") targets** — and Commit B is **not on this
branch** (this branch is Commit A only). The B1 identity contradiction-veto + widget-only strip
would kill the `ogrenci`/`veli` false-positives (bare "kız öğrenci" must not trigger `ogrenci`),
and the child-reference recovery would flip Nazan/Gülhan to `veli`.

- **Fix:** land Commit B. Until then this is the dominant label-error source. The §4 lexicon in
  the fixes plan already lists the exact negative cases (656/716/886/… "kız öğrenci" = gender,
  not identity) — these 197 leads confirm it holds.

---

## 5. Cluster D/E/F/G — the smaller, self-contained bugs

### D — `hizmet-veremiyoruz` covers university names but not **city names** ✅

**Proven** by re-running `compute_hizmet_veremiyoruz` on the four city leads:

| Lead | Said | Extracted phrase → out-of-city scan | Label |
|---|---|---|---|
| Özlem Dinçer (1463) | "Ankara" | matched **"Ankara Bilim Üniversitesi"** (token "ankara") | ✅ applied |
| Duygu Turna (1426) | "İzmir" | no university-name match | ❌ missing |
| Nihan (992) | "İzmir / Bornova" | no match | ❌ missing |
| Erdem (593) | "Çorum" | no match (LLM proposed it, A2 stripped it) | ❌ missing |

**This answers your NOTE directly.** `hizmet-veremiyoruz` **is** a hard Router rule (spec A2):
[app/tagassigner/hizmet_veremiyoruz.py](../app/tagassigner/hizmet_veremiyoruz.py) always strips
the LLM's proposal, then re-derives the label by scanning the lead's university *phrase* against
the **`out_of_city_universities`** table — **university NAMES only**. So:

- It is **not** LLM inference, and **not** inconsistent-by-chat. It is deterministic.
- Özlem's "Ankara" worked **by accident** — "Ankara" is a token of the out-of-city *university*
  "Ankara Bilim Üniversitesi", so it matched. "İzmir"/"Bornova"/"Çorum" are city/district names
  that don't equal any university name → no match → no label. ✅ your exact guess ("only school
  names, not city names") is correct.
- **Fix:** give `compute_hizmet_veremiyoruz` an **out-of-İstanbul city/province gazetteer** (İzmir,
  Ankara, Bornova, Çorum, …) and apply the label when the inbound phrase names a non-İstanbul
  city/district, not only a non-İstanbul university. (Keep the in-city short-circuit so "Kadıköy"
  etc. never trip it.)

### E — `deal_awaiting` gaps (verified NOT hotel_accessible)

`deal_awaiting` needs a **resolved university_id** that is (1) on `deal_awaiting_universities` and
(2) has no serviceable property. Live-table check per lead:

| Lead | University | on deal_await list? | serviceable? | Verdict |
|---|---|---|---|---|
| Jule (856) / Nuriye (850) / Mübeccel (372) | İstanbul Üniversitesi **Cerrahpaşa** | **No** | No | **Data gap → flagged** |
| "..." (1016) | *unresolved* (ambiguous "Cerrahpaşa") | n/a (no id) | n/a | **Logic gap → flagged** |
| Gülhan (899) | Cerrahpaşa **Tıp** Fakültesi | Yes | No | ✅ got the label (control) |
| GÖKÇE (1045) / Alpay (1379) | İstanbul Aydın | Yes | **Yes (via hau)** | hotel_accessible → **excluded** |
| Kemal (710) | Okan (Tuzla) | No | **Yes (via hau)** | hotel_accessible → **excluded** |

Two genuine, non-hotel_accessible gaps:

- **E1 — İstanbul Üniversitesi Cerrahpaşa is missing from `deal_awaiting_universities`** while
  *Cerrahpaşa Tıp Fakültesi* is on it. Add İÜC (and audit the list for other out-of-service
  İstanbul institutions). Affects Jule, Nuriye, Mübeccel.
- **E2 — ambiguous resolution can't reach `deal_awaiting`.** "Cerrahpaşa" alone correctly
  withholds the university (İÜC vs Cerrahpaşa Tıp), so there's no `university_id` to look up —
  but **both** candidates are out-of-service. Add handling: when the university is withheld as
  ambiguous and *every* candidate is a deal_awaiting university, apply `deal_awaiting`. Affects
  "..." (1016). ✅ your "there is probably no system to handle this case" is correct.

### F — `kapora-alindi` leaks through the Router ✅

**Proven:** Sude (1169) has `kapora-alindi` in the final Chatwoot labels; the LLM proposed it off
the "10000 TL kapora" sales chat. It is a **`LLM_OWNED`** label with **no strip** — so the LLM can
apply a human-salespeople-only label and nothing stops it. (It also leaked onto **Aman (78)**,
which you didn't flag — same bug, so the count of 1 understates it.)

- **Fix:** add `strip_llm_kapora_alindi(labels)` and call it in the Router's strip chain next to
  `strip_llm_fiyat_soruyor` / `strip_llm_hizmet_veremiyoruz`. `kapora-alindi` must **never** pass
  the Router — exactly as you asked ("fail it at the router level"). It should only ever be
  human-set.

### G — gender read from a **question**, not a statement

**Proven:** Nergis Eraşcı (1107) asked "**Sadece kız öğrenciler için mi?**" (is it female-only?) —
a question about *our dorm's* policy — and gender was written **Kız**. The A3 inbound-gender guard
counts "kız öğrenci" as a female signal even inside an interrogative.

- **Fix:** in `inbound_gender_signal`, exclude interrogative frames — "kız/erkek öğrenci **için
  mi**", "**sadece** … için mi", trailing "mı/mi/mu/mü?" — before accepting a gender token. (İTÜ
  - Ayazağa university here was correct; only gender was wrong.)

---

## 6. Reported items that were NOT errors (code overrules the guess)

Per policy ("what the logs prove is above my opinion"):

- **Musab Adabağlı (1202)** — you said the university "wasn't assigned". It **was**: *Medeniyet
  Üniversitesi - Ünalan/Göztepe*, and `deal_awaiting` correctly applied. "istanbul medeniyet
  üniversitesi göztepe kuzey kampüsü" matched fine — the length didn't break it. No error.
- **"B" / topkapı (cw 495)** — "topkapi universitesi kazlicesme yerleskesi" resolved **correctly**
  to *Topkapı Üniversitesi - Kazlıçeşme*. The complaint maps to this lead, which was right. (The
  other "B", cw 261, is an English lead — "Topkapı Yerleşkesi" — left withheld; out of scope.)
- **Ecrin (760)** — "ayazağında okuyorum" → İTÜ - Ayazağa, and `ogrenci` is **legitimate** here
  ("okuyorum" = first-person enrollment). This is a success, not a failure. It works because
  "ayazağa" is an explicit campus alias (migration 018c) — whereas full parent names withhold at
  campus level, which is the asymmetry you noticed.

**Defensible design (not flagged), all pending your campus-exception decision (§7):**

- **Hamza Temiz (1376)**, **Bahar Ferda Topçu (940)**, **Aysun (1272)**, **Can (1269)** —
  bare "İstanbul Bilgi", "Bahçeşehir", "İTÜ" with **no campus stated** → withheld. This is the
  current multi-campus rule (only İÜ and Boğaziçi are curated defaults). Consistent with Farhan
  in the prior run. Whether to add these as exceptions is your call (§7).
- **Ayşe Özkan Darıcı (1283)** — said Medipol "Güney kampüs", got Medipol - **Kuzey**. The list
  has **exactly one** Medipol campus ("Medipol Üniversitesi - Kuzey"), so Kuzey is the only value
  the system *can* write for any Medipol lead. This is a **data-granularity** gap (no Medipol
  Güney entry — they're adjacent Kavacık yerleşkeleri), not a matching bug. Add a Medipol Güney
  list value only if it's a distinct serviceable location.

---

## 7. Your NOTES — answered

1. **"Remind me to clean up the `hotel_accessible_universities` table."** ⏰ **Reminder:** the
   table is over-wide. It falsely marks **İstanbul Aydın** (suppressing deal_awaiting on GÖKÇE
   1045 & Alpay 1379) and **Okan Tuzla** (Kemal 710) as serviceable. These were excluded from the
   accuracy numbers, but the table needs an audit/cleanup pass so `deal_awaiting` stops being
   suppressed on genuinely out-of-service universities.
2. **hizmet-veremiyoruz "in some chats and not others" (İzmir vs Ankara).** Answered in §5-D:
   it's a **hard, deterministic Router rule** that matches out-of-city *university names*, not
   city names. Ankara matched by luck (a university named "Ankara Bilim"). İzmir/Bornova/Çorum
   don't. The fix is a city/province gazetteer.
3. **"Ask me about the exceptions to the campus-level-specification rule."** Doing so now — see
   the question posed alongside this document. From this run, the schools where campus-withholding
   backfired are **İTÜ** (Can 1269, Hazel 1167), **Bahçeşehir** (Aysun 1272, Bahar 940, and the
   Çırağan case 1119), and **İstanbul Üniversitesi Cerrahpaşa** (Sami 772). Please confirm which
   of these (and any others) should resolve to a default campus, the way İÜ→Beyazıt and
   Boğaziçi→Ana Kampüs already do.

---

## 8. Per-lead disposition (all reported problems)

| Lead (cw) | Your report | Disposition | Flag |
|---|---|---|---|
| Filiz Ayhan (183) | uni İÜ from "istanbul merkeze" | ✅ istanbul→İÜ; correct = İ.Aydın | attr uni |
| Nancy (1189) | English | **excluded from sample** | — |
| Merve (1446) | Bahçeşehir Güney → Boğaziçi | ✅ güney-kampüs→Boğaziçi (mig 027) | attr uni |
| Duygu Turna (1426) | İzmir, no hizmet-veremiyoruz | ✅ city-name gap | label_missing |
| Özlem Dinçer (1463) | Ankara got hizmet-veremiyoruz | correct (matched a university) | — |
| Nesrin (1381) | unwarranted ogrenci | ✅ widget "erkek öğrenci" | identity none |
| Alpay Reisoğlu (1379) | missing deal_awaiting | hotel_accessible → **excluded** | — |
| Hamza Temiz (1376) | Bilgi not written | defensible multi-campus withhold | — |
| Zehra Bayraktar (1318) | unwarranted veli | ✅ no parent evidence | identity none |
| Eray Kalfaoğlu (1295) | unwarranted ogrenci | ✅ widget + gender answer | identity none |
| Murat Ertan (1288) | istanbul → İ.Aydın | ✅ correct = İÜ (Beyazıt) | attr uni |
| Ayşe Özkan Darıcı (1283) | Medipol Güney → Kuzey | only one Medipol campus exists | — |
| Aysun (1272) | Bahçeşehir not written; veli | uni defensible; veli wrong | identity none |
| Can (1269) | İTÜ not written | defensible İTÜ multi-campus withhold | — |
| Bircan Savaş (1247) | unwarranted ogrenci | ✅ widget + gender answer | identity none |
| Şevval Çetinkaya (1227) | Marmara → Maltepe | ✅ property-name "Maltepe" | attr uni |
| Musab Adabağlı (1202) | uni not assigned | **was assigned** (Medeniyet) | — |
| merve (1196) | staj → ogrenci not ogrenci-degil | your call: ogrenci-degil | identity ogrenci-degil |
| Sude (1169) | kapora-alindi must not pass | ✅ LLM_OWNED, no strip | label_wrong kapora |
| Furkan Aytaş (1168) | mimar sinan → Okan | ✅ `iou` short-alias (regression) | attr uni |
| Hazel Turan (1167) | İTÜ → Işık | ✅ `isik` short-alias | attr uni |
| Nihan Türedi (1119) | Bahçeşehir Beşiktaş not written | ✅ besiktas→Çırağan not aliased | attr uni |
| Nergis Eraşcı (1107) | "kız öğrenciler için mi" → Kız | ✅ interrogative gender | attr gender |
| Selda (1059) | unwarranted ogrenci | ✅ widget + gender answer | identity none |
| GÖKÇE Y. (1045) | missing deal_awaiting | hotel_accessible → **excluded** | — |
| Döner Demirci (1044) | Marmara-Maltepe → Maltepe | ✅ "maltepe" token | attr uni |
| Nuran Seyfioğlu (1038) | unwarranted veli | ✅ search phrase | identity none |
| "..." (1016) | Cerrahpaşa, missing deal_awaiting | ✅ ambiguous → no id (logic gap) | label_missing |
| Doruk Yıldırım (12) | İÜ Konservatuvar → Maltepe | ✅ district "Maltepe" | attr uni |
| Nihan (992) | İzmir/Bornova, no hizmet-veremiyoruz | ✅ city-name gap | label_missing |
| Nazan (972) | parent → ogrenci | your call: veli ("iki kardeşler") | identity veli |
| Bahar Ferda Topçu (940) | Bahçeşehir not written | defensible multi-campus withhold | — |
| Ayşe (929) | unwarranted ogrenci | ✅ widget + gender answer | identity none |
| Eyşan Akdağ (909) | yeditepe → Maltepe (property) | ✅ property-name "Maltepe" | attr uni |
| Gülhan Can Cofcof (899) | parent → ogrenci | your call: veli ("sınava girdi çocuk") | identity veli |
| Jule Aslan (856) | İÜC correct, no deal_awaiting | ✅ İÜC absent from list | label_missing |
| Nuriye Yücedağ (850) | no deal_awaiting; unwarranted ogrenci | ✅ both | label_missing + identity none |
| Sami Süner (772) | İÜC not written | ✅ "İÜ Cerrahpaşa" → PARENT_ONLY withhold | attr uni |
| Ecrin (760) | ayazağa → İTÜ correct | correct (success) | — |
| Kemal Alp (710) | Okan, no deal_awaiting/hizmet | hotel_accessible → **excluded** | — |
| Erdem (593) | Çorum, no hizmet-veremiyoruz | ✅ city-name gap | label_missing |
| Enda Ceren İn (575) | kent kağıthane → Okan | ✅ `iou` short-alias | attr uni |
| "B" (261/495) | topkapı kazlıçeşme not written | **495 was correct**; 261 English | — |
| Yusuf Çalbay (459) | unwarranted ogrenci | ✅ gender answer | identity none |
| HasretCan Görür (380) | İÜ false (Çukurova student) | ✅ "İstanbul'da kalmak"→İÜ | attr uni |
| Mübeccel (372) | İÜC correct, no deal_awaiting | ✅ İÜC absent from list | label_missing |
| "." (347) | unwarranted veli | ✅ widget only | identity none |
| Nehir (333) | unwarranted veli | ✅ search phrase (İÜ correct) | identity none |
| Öykü Nil (267) | Medeniyet Güney → Boğaziçi | ✅ güney-kampüs→Boğaziçi | attr uni |

---

## 9. Fix priority (by error mass, cheapest-first)

1. **Land Commit B (identity veto).** Biggest hole (B2 65%); 11+ leads. Already specced.
2. **Delete the `güney kampüs` / `güney yerleşkesi` aliases + stoplist** (A1). One migration,
   mirrors the beyoğlu fix; recovers Merve + Öykü and any future "X güney kampüs" lead.
3. **Stoplist bare `istanbul` + our property/branch names + colliding districts** (A2/A3). Recovers
   Filiz, Murat, HasretCan, Eyşan, Şevval, Döner, Doruk — 7 leads, deterministic.
4. **`strip_llm_kapora_alindi`** (F). Trivial; closes a label that must never be bot-set.
5. **City/province gazetteer for hizmet-veremiyoruz** (D). Recovers Duygu, Nihan, Erdem.
6. **Add İÜ Cerrahpaşa to `deal_awaiting_universities` + ambiguous-candidates handling** (E).
7. **Interrogative-gender guard** (G); **short-alias exact-match rule + alias audit** (A4);
   **PARENT_ONLY keeps a valid LLM campus** (A-bonus).
8. **`hotel_accessible_universities` cleanup** (your NOTE #1) — data, separate pass.
