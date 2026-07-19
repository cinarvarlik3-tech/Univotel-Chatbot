# TagAssigner — 50-Lead Accuracy Run: Root-Cause Explanations (Round 1)

**Run:** `2026-07-19-sweep50` · **Command graded:** `./scripts/tag sweepEmpty` (50 leads)
**Harness:** `accuracy_optimization/tagassigner/` (spec 029)
**Report:** [results/19-07-2026_19.28_50_tagassigner-accuracy.md](../accuracy_optimization/tagassigner/results/19-07-2026_19.28_50_tagassigner-accuracy.md)
**Feedback (structured flags):** [inputs/feedback_2026-07-19-sweep50.json](../accuracy_optimization/tagassigner/inputs/feedback_2026-07-19-sweep50.json)
**Method:** systematic-debugging (root cause before fixes). No working-code changes were made — this document is investigation + *proposed* solutions only.

---

## 0. Policy compliance (what was actually graded)

- **51 conversations exist in the DB; 50 were processed** (had a `status='success'` tag_assigner_run). The one unprocessed lead — **`1368 Nilay Çınar`** (`flow_state=stopped`, 0 runs) — was **excluded**, per the "only grade what was processed" policy.
- Rates are computed over **operations actually done** (50 processed conversations), not over the 51 DB rows.
- Two of the flagged items turned out **not to be errors** and were not counted (details in §4):
  - **Nilay (650)** — university *was* correctly written.
  - **Farhan (1138)** — the blank is a defensible campus-ambiguous withhold.

---

## 1. Headline results

| Metric | Result |
|---|---|
| **Run correctness** (every graded field exact, per conversation) | **78.0 %** (39/50) [64.8–87.2] |
| **General attribute correctness** (mean of uni/gender/room A3) | **94.0 %** |
| **Label micro-F1** — LLM-owned / Router-owned | **94.9 %** / **100 %** |
| University — correct-write (final) | **82.0 %** (41/50) |
| University — decision rate / coverage (final) | **64.0 %** (16/25) |
| University — correctness *given a decision* (final) | **100 %** (16/16) |
| Gender — correct-write | **100 %** (50/50) |
| Room type — correct-write | **100 %** (50/50) |
| Identity — precision / recall | **80 %** / **80 %** |

**One-line diagnosis:** gender and room type are effectively solved. **Every real defect in this run is in two areas — university resolution and identity (`veli`) — and they fail for completely different reasons.** University coverage is the single biggest lever: when the system *does* write a university it is **100 % correct**, but it withholds on 9 leads who clearly named their school.

**Do not "fix" the Router blindly.** Its deterministic university override is **net-positive**: on university it *rescued* the LLM **15** times (LLM hallucinated a school from the bot's own pitch text; the Router correctly withheld) and only *broke* **4**. The goal is to keep the rescues and remove the 4 breaks — not to weaken the withhold logic.

---

## 2. The university failures — one subsystem, six distinct root causes

All 9 university misses share a surface symptom ("attribute came out blank"), but they have **six different underlying causes**. Grouping them is the whole point — a single fix will not clear them.

### Layer attribution per lead (evidence: reproduced with the live canonicalizer)

| Lead | cw | Lead's words | LLM proposed | Written | Correct | Root cause |
|---|---|---|---|---|---|---|
| İskender Aga | 1154 | "İstanbul üniversitesi Amerikan Dili edebiyatı" | İstanbul Üniversitesi | *blank* | İstanbul Üniversitesi | **RC-U4** multi-campus policy |
| Sinemhan Kılıç | 988 | "Biruni üniversitesi" | Biruni Üniversitesi | *blank* | Biruni Üniversitesi | **RC-U1** `bilgi` alias collision |
| A. Kaya | 977 | "Biruni üniversitesine en yakın" | Biruni Üniversitesi | *blank* | Biruni Üniversitesi | **RC-U1** `bilgi` alias collision |
| Şükriye Ceylan | 716 | "Üsküdar üniversitesi" | Üsküdar Üniversitesi | *blank* | Üsküdar Üniversitesi | **RC-U4** multi-campus policy |
| Sami | 900 | "ÜÜ Np Sağlık yerleşkesi" | *bilinmiyor* | *blank* | Üsküdar Üniversitesi | **RC-U7** LLM miss + **RC-U4** |
| Gülçin | 1126 | "Boğaziçi güney kampüs" | Boğaziçi – Anadolu Hisarı | *blank* | Boğaziçi – Ana Kampüs | **RC-U5** missing campus alias |
| ayse44klc | 937 | "Boğaziçi … Rumeli Hisarı" | Boğaziçi – Anadolu Hisarı | *blank* | Boğaziçi – Ana Kampüs | **RC-U5** missing/colliding alias |
| Görkem Akdoğan | 1328 | "Mimar Sinan Fındıklı kampüsündeyim" | İstanbul Üniversitesi (hallucinated) | *blank* | MSGSÜ – Beşiktaş | **RC-U6** token-scan defeated by noise + **RC-U7** |
| Bilinmeyen | 920 | "Mimar Sinan Üni Beyoğlu" | *bilinmiyor* | *blank* | MSGSÜ – Beşiktaş | **RC-U6** + **RC-U7** |

---

### RC-U1 — Over-broad **bare-word aliases** collide with ordinary Turkish *(the most important finding)*

**What happens.** The university alias table contains **single-token aliases that are common Turkish words or word-fragments.** The worst offender in this run is the alias **`bilgi` → İstanbul Bilgi Üniversitesi.** "bilgi" means *"information"* and appears in nearly every greeting — the standard opener is literally *"…hakkında **bilgi** alabilir miyim?"* ("can I get **information** about…").

**Why it withheld Biruni.** Reproduced live, token by token:

```
"Ücret ve koşullar nasıl Biruni üniversitesi Kız ögrenci"                       → EXACT  → Biruni (CAMPUS) ✓
"Merhaba! Bunun hakkında daha faza bilgi alabilir miyim? …Biruni üniversitesi"  → ALIAS  → İstanbul Bilgi (PARENT_ONLY) ✗
```

The only difference is the greeting prefix containing **"bilgi"**. The scanner (`scan_entities_by_ngram`) then resolves the institution as a *parent* it can't pin to a campus → `PARENT_ONLY` → and because the Router treats the lead's own words as **authoritative**, it writes `bilinmiyor-kampus` (a withhold), **discarding the LLM's correct "Biruni Üniversitesi" guess.**

**Confirmation.** Removing *only* the `bilgi` alias flips **988 and 977** from `parent_only` → `campus (Biruni Üniversitesi – Ana Kampüs)`. Nothing else changes.

**This is not just about `bilgi`.** The alias audit found a whole class of landmines (all live, all reproduced):

| Alias | Resolves to | Collides with the everyday word | Severity |
|---|---|---|---|
| `bilgi` | İstanbul **Bilgi** Üni. | "bilgi" = information (in every greeting) | Silent **withhold** of the real school |
| `bir` | **Bir**uni Üni. | "bir" = one/a | **False-positive WRITE** |
| `su` | Sabancı Üni. (**SU**) | "su" = water | **False-positive WRITE** |
| `yu` | **Y**editepe Üni. | common fragment | **False-positive WRITE** |
| `rumeli` | İstanbul **Rumeli** Üni. | "Rumeli Hisarı" = Boğaziçi's campus | Mis-routes Boğaziçi leads |
| `teknik` | İTÜ (**Teknik**) | "teknik" = technical | Spurious parent match |

`bir` is the scariest: `"bir erkek yurdu arıyorum"` ("I'm looking for **a** male dorm") and `"bir kişilik oda"` ("**single** room") both canonicalize to **Biruni Üniversitesi (CAMPUS write)** — actively wrong data, worse than a blank. These did **not** detonate in this 50-lead sample only because of scan-order luck (a longer n-gram or an earlier `bilgi` happened to win first). At sweep scale they will.

**Proposed solution (not applied).**
1. **Purge / re-scope bare-word aliases.** No university alias should be a standalone common word or a fragment shorter than ~4 chars unless it is an unambiguous acronym. `bilgi` should be `"istanbul bilgi"` / `"bilgi üniversitesi"`, never bare `bilgi`; delete `bir`, `su`, `yu` (their parents already match via `biruni`, `sabancı`, `yeditepe`); re-scope `rumeli` and `teknik`.
2. Add a lint/CI check over the alias table that fails on any single-token alias appearing in a Turkish common-word stoplist (extend the existing `FACULTY_STOPLIST`/`DISTRICT_STOPLIST` pattern in `university_canonicalizer.py`).

---

### RC-U2 — The scanner returns **first-in-scan-order, not best-match** *(the enabling algorithm defect)*

**What happens.** `scan_entities_by_ngram` walks n-grams **longest-first, then left-to-right**, and returns the **first** non-NONE match — with **no ranking by confidence.** And `match_university` checks **parent-aliases *before* Tier-1 exact campus** matches.

Because "Biruni" only matches via the **1-gram** `biruni` (the 2-gram `"biruni üniversitesi"` returns NONE — it isn't the full campus name and isn't a registered 2-gram alias), it competes in the *last* scan tier. A spurious earlier 1-gram (`bilgi`) therefore wins purely on **position**. A more specific, higher-confidence EXACT campus match that sits later in the sentence never gets evaluated.

This is *why* RC-U1's bad aliases are so damaging: the algorithm has no notion of "an EXACT campus beats a parent-alias." Whoever appears first wins.

**Proposed solution (not applied).** Make the scan **confidence-ranked, not position-ranked**: collect all n-gram matches, then prefer `EXACT campus > campus alias > parent alias`, breaking ties by n-gram length. At minimum, a later EXACT campus match should outrank an earlier parent-alias match. (Fixing RC-U2 makes RC-U1 far less dangerous even before the aliases are cleaned.)

---

### RC-U3 — The Router feeds the **entire greeting/widget boilerplate** into the matcher *(the trigger)*

`extract_university_phrase_from_messages` concatenates **all** inbound messages — including the canned opener *"Merhaba! Bunun hakkında daha faza bilgi alabilir miyim?"* and the widget prefill *"Merhabalar Univotel! … hakkında bilgi alabilir miyim? Üniversitem: … Başvuru Kodu: UV-XXXX"*. That boilerplate is exactly what injects the collision tokens (`bilgi`) and the noise that defeats token-containment (RC-U6). The prompt already tells the *LLM* to "ignore the widget intro template," but the **deterministic scanner has no such filter.**

**Proposed solution (not applied).** Before scanning, **strip known boilerplate**: the standard greeting(s), the `Başvuru Kodu: …` line, and the widget scaffold, keeping the `Üniversitem:` payload and the lead's free-text answers. This is a surgical, low-risk change isolated to the extractor.

---

### RC-U4 — Multi-campus parents **withhold even when a usable plain list value exists**

**İskender (1154), Şükriye (716), Sami (900).** İstanbul Üniversitesi and Üsküdar Üniversitesi are genuinely multi-campus in the DB, so a bare "İstanbul üniversitesi" / "Üsküdar üniversitesi" resolves to `PARENT_ONLY`, and the 2026-07-15 authoritative-withhold policy (see `university_canonicalizer.resolve_university_override`, docs 028 / 028.1) forces `bilinmiyor-kampus`. İskender even named a faculty ("Amerikan Dili edebiyatı") that the matcher can't map to a campus.

But the **label map has a plain "İstanbul Üniversitesi" and "Üsküdar Üniversitesi" list value** — a parent-level tag that would be a perfectly good answer. Right now that recoverable signal is thrown away. This is the **1** genuine policy tension in the run: the withhold is "safe" but loses information the lead unambiguously provided.

**Proposed solution (not applied) — needs a product call.** When canonicalization is `PARENT_ONLY` **and** the parent has a plain (campus-less) Chatwoot list value, write the **parent value** instead of withholding. This is strictly better than blank for downstream routing and keeps the anti-hallucination guarantee (we only write what the lead actually named — the *institution*). Where the parent has *no* plain value (e.g. Bahçeşehir, see §4), keep withholding.

---

### RC-U5 — Missing / colliding **campus aliases** (data gaps)

**Gülçin (1126) "Boğaziçi güney kampüs"** and **ayse44klc (937) "Rumeli Hisarı"** both denote Boğaziçi's **Ana Kampüs** (the historic South/Güney campus in Rumelihisarı), but:
- there is **no alias** mapping `güney` or `rumeli hisarı` → Boğaziçi Ana Kampüs, and
- worse, `rumeli` is an **active alias for a different school** (İstanbul Rumeli Üniversitesi — RC-U1).

So `match_campus` can't resolve the campus → `PARENT_ONLY` → withheld. *(Your own note on ayse44klc — "probably that campus name doesn't mean anything in the DB, most likely not a code problem" — is exactly right; this is a data gap.)*

**Proposed solution (not applied).** Add campus aliases: Boğaziçi Ana Kampüs ← `güney`, `güney yerleşkesi`, `rumeli hisarı`, `rumelihisarı`, `hisarüstü`. Re-scope the bare `rumeli` alias so it can't hijack Boğaziçi leads.

---

### RC-U6 — `token_containment` is **defeated by long widget text**

**Görkem (1328) "Mimar Sinan Fındıklı", Bilinmeyen (920) "Mimar Sinan Üni Beyoğlu".** MSGSÜ resolves fine in isolation — `token_containment("Mimar Sinan Fındıklı")` → *Mimar Sinan Güzel Sanatlar Üniversitesi – Fındıklı Kampüsü*. But that function requires **all** significant phrase tokens to be a subset of one university's name. The **full multi-line widget message** adds many tokens ("academic house fatih kız öğrenci yurdu", "başvuru kodu", …), so the subset test fails → NONE. (For Görkem the `bilgi` collision additionally turns NONE into a spurious `PARENT_ONLY` before the widget noise even matters.)

Note the DB naming trap: the campus is stored as *"…Fındıklı Kampüsü"* but its Chatwoot list value is confusingly **"MSGSÜ – Beşiktaş"** — the lead's correct answer ("Fındıklı") doesn't visually match the label it should map to.

**Proposed solution (not applied).** This is largely fixed for free by RC-U3 (boilerplate stripping) + RC-U2 (best-match scan). Independently, `token_containment` could scan windowed n-grams rather than requiring the *whole* phrase to be a subset. Also consider adding `fındıklı` / `beyoğlu` as MSGSÜ campus aliases and reconciling the misleading "Beşiktaş" list value.

---

### RC-U7 — LLM extraction: **misses cryptic names, hallucinates from the bot's pitch text**

- **Sami (900):** "ÜÜ Np Sağlık yerleşkesi" (Üsküdar Üni. NP Sağlık Yerleşkesi) → LLM gave `bilinmiyor`. Cryptic abbreviation; understandable miss.
- **Görkem (1328):** LLM proposed **"İstanbul Üniversitesi"** — a name that appears **in the bot's own message** ("İstanbul Üniversitesi, Kadir Has… çevre üniversitelerine"), not in anything the lead said. The lead said "Mimar Sinan Fındıklı."

The second pattern is important and reassuring: the Router's authoritative inbound-only scan is what **catches** these pitch-text hallucinations (the 15 rescues). RC-U7 is real but is mostly a *safety net working*, not a new bug to chase.

---

## 3. Identity / label failures — all **LLM-layer**, and mostly a `veli` problem

Router involvement here is **zero** (Router-owned label F1 = 100 %, no preservation violations). Every identity/label error is the LLM ignoring — or falling into a genuine gap in — the prompt's rules.

| Lead | cw | LLM did | Should be | Verdict against the prompt |
|---|---|---|---|---|
| Görkem | 1328 | `veli` | `ogrenci` | **LLM error.** He said "**ben** tek kişi salonda konaklamak için soruyorum" / "başka **konaklayacağım**" — first-person self-stay = `ogrenci` (prompt line 214). `veli` requires an explicit child reference he never gave (lines 216–217). |
| Sıla | 707 | `veli` | not `veli` (student) | **LLM error.** "2.sınıfı bitirdim yaz stajı" = self-enrollment/year = `ogrenci` (line 212). No child reference → `veli` is a direct rule violation. |
| Mine Koşun | 1067 | *(none)* | `veli` (developer) | **Prompt-compliant withhold, not an LLM bug.** "YKS ye yeni girdi, sonuç bekliyoruz" has no explicit "oğlum/kızım"; the prompt (line 222) says *infer nothing* here. Developer wants inference the prompt forbids → **policy gap**, see below. |
| Mine Koşun | 1067 | `yerlesti` | `yeni-giris` (developer) | **LLM error on `yerlesti`.** Its gate needs an explicit "yeni yerleştim" **and** a July 20–30 date; the lead is *waiting for results* (not placed). **Definitional gap on `yeni-giris`**: the prompt defines it as "has just begun university," but the lead hasn't begun — no label cleanly covers "took the exam, awaiting placement." |

**The pattern:** the LLM has an **asymmetric `veli` problem** — it *over-applies* `veli` to leads who explicitly identify as students (Görkem, Sıla), while the developer *also* wants it applied to an implicit-parent case the prompt deliberately excludes (Mine). Over-application is the LLM breaking a clear rule; the Mine case is the rule itself not matching your intent.

**Bonus finding (not flagged):** Görkem's LLM output the malformed label **`ununivotelli`** (a typo of `univotelli`). The Router correctly dropped it as unknown — but that means Görkem, a returning customer ("geçen sene sizin aracılığınız ile Mari Suite'de kalmıştım"), lost the `univotelli` tag he earned. Worth a glance at whether the LLM produces malformed labels elsewhere.

**Proposed solutions (not applied).**
- **Görkem/Sıla (over-application):** tighten the prompt's `veli` section with the two exact failure phrasings as negative examples ("ben … konaklamak için soruyorum" and "N. sınıfı bitirdim" → `ogrenci`, never `veli`), or add them as few-shot corrections. This is a prompt/model-quality fix, not code.
- **Mine `veli`:** a **product decision** — do you want "sonuç bekliyoruz / third-person about the candidate" to count as `veli`? If yes, the prompt's veli rule must be widened to allow that specific inference (with care: it loosens a deliberately strict rule).
- **Mine `yeni-giris`:** decide whether `yeni-giris` should also cover "just took YKS, awaiting placement," or whether a distinct "sınav-sonuç-bekliyor"-type label is warranted. Right now the taxonomy has a hole between `pre-sinav`, `yerlesti`, and `yeni-giris`.

---

## 4. The two flagged items that are **not** errors

**Nilay (650) — university WAS set.** You flagged "Türk Alman Üniversitesi not set," but it is present on **both** surfaces: the Chatwoot custom attribute reads `university = "Türk Alman Üniversitesi"`, and the DB `university_id` resolves to the same. It resolved cleanly (`CAMPUS`) because "Türk Alman Üniversitesi" is a 3-gram EXACT match that outranks the `bilgi` collision regardless of position. **Scored correct.** *(If you observed a blank in the Chatwoot UI, it may have been a stale panel — worth a refresh to confirm.)*

**Farhan (1138) — the blank is a *correct* withhold.** The widget said "Üniversitem: Bahcesehir university" with **no campus**. Bahçeşehir is multi-campus in the DB (Kuzey / Çırağan / Tıp Fakültesi) with **no plain "Bahçeşehir Üniversitesi" list value**, so there is no single correct value to write and the lead named no campus → `bilinmiyor-kampus` is the designed behavior. This is the *good* half of the anti-hallucination policy (contrast İskender/Üsküdar in RC-U4, where a plain value *does* exist). **Left unflagged.** If a plain "Bahçeşehir Üniversitesi" list value were added, RC-U4's fix would then cover it.

---

## 5. Response to your NOTE (uni-specific-page widgets → auto-set university)

> *"We might want to make the uni-specific page widgets automatically set university custom attribute…"* (raised on Gülçin)

**This would help, but it is not a substitute for fixing §2, and it carries real caveats.**

- **Where it helps:** Gülçin arrived via the **BOUN-specific** page widget ("Merhaba! **BOUN** yakınında öğrenci konaklaması hakkında bilgi alabilir miyim? Başvuru Kodu: UV-K5FA"). If that page reliably stamps `university = Boğaziçi`, you'd resolve the *institution* deterministically and side-step RC-U5's alias gap for that lead.
- **Caveat 1 — parent vs campus.** A BOUN page can only assert the *institution*, not the campus. For a multi-campus school it would set the parent → your own `PARENT_ONLY`/`bilinmiyor-kampus` logic still applies. So this rides on the **RC-U4** decision (write the plain parent value or not). For single-campus pages (e.g. a Biruni page) it's an unambiguous win.
- **Caveat 2 — it doesn't cover the biggest cohort.** Farhan and İskender did **not** use a uni-specific page; they typed the university into the **generic** widget or in free text. Auto-set from the page only helps page-specific arrivals, which is a minority. The alias/scan fixes (RC-U1/U2/U3) help *everyone*.
- **Caveat 3 — trust boundary.** If a lead lands on the BOUN page but is actually asking about a different school, a hard auto-set could write the wrong university. Recommend treating the page signal as a **high-confidence campus/parent hint fed into the same canonicalizer** (so it can still be overridden by an explicit contradictory statement), not as an unconditional write.

**Recommendation:** pursue it as a *ranked input to the existing resolver*, decided together with RC-U4, **after** the alias cleanup — otherwise the same collision logic can still corrupt it.

---

## 6. Priority-ordered fix list (proposed — none applied)

| # | Fix | Clears | Effort / risk | Type |
|---|---|---|---|---|
| 1 | Purge/re-scope bare-word aliases (`bilgi`, `bir`, `su`, `yu`, `rumeli`, `teknik`, …) + add a CI stoplist lint | RC-U1 (Sinemhan, A.Kaya) + prevents future false-positive **writes** | Low / low | Data + test |
| 2 | Confidence-rank the n-gram scan (EXACT campus beats earlier parent-alias) | RC-U2 (defuses U1 broadly) | Med / med | Code |
| 3 | Strip greeting/widget boilerplate before the deterministic scan | RC-U3, RC-U6 (Görkem, Bilinmeyen) | Low / low | Code |
| 4 | Add Boğaziçi/MSGSÜ campus aliases (`güney`, `rumeli hisarı`, `fındıklı`, `beyoğlu`) | RC-U5 (Gülçin, ayse44klc) | Low / low | Data |
| 5 | **Product call:** write plain parent value on `PARENT_ONLY` when one exists | RC-U4 (İskender, Şükriye, Sami) | Low code / **policy** | Policy + code |
| 6 | Tighten `veli` prompt guidance with the Görkem/Sıla negative examples | Identity over-application | Low / low | Prompt |
| 7 | **Product call:** define labels for "took exam, awaiting placement" & implicit-parent | Mine Koşun (`yeni-giris`, `veli`) | — / **policy** | Taxonomy |

**Sequencing note:** #1 → #2 → #3 are the highest-value, lowest-risk cluster and together address the bulk of the university misses *and* the latent false-positive-write risk. #5 and #7 are product decisions, not bugs.

---

## Appendix A — Evidence trail (reproductions)

All reproductions used the **live** matcher/canonicalizer against the production DB universe (read-only):

- **`bilgi` collision & positional race:** `"…bilgi… Biruni üniversitesi"` → ALIAS→İstanbul Bilgi (`PARENT_ONLY`); same phrase without the greeting → EXACT→Biruni (`CAMPUS`). Winning n-gram in the failing case is the **1-gram `bilgi`**, reached before the 1-gram `biruni` purely by position.
- **Fix confirmation:** removing only the `bilgi` alias flips cw 988 & 977 → `CAMPUS Biruni`; no other case changes (so the *other* misses are genuinely different root causes).
- **Latent false-positive writes:** `"bir erkek yurdu arıyorum"` and `"bir kişilik oda fiyatı"` → `CAMPUS Biruni Üniversitesi`; `"su tesisatı hakkında"` → `CAMPUS Sabancı Üniversitesi`.
- **Multi-campus withholds:** İstanbul Üni (4 campuses) and Üsküdar Üni (3 campuses) resolve `PARENT_ONLY` on a bare institution name; the label map nonetheless holds a plain "İstanbul Üniversitesi" / "Üsküdar Üniversitesi" value.
- **Router net-effect (from the harness A5):** university rescued **15**, broke **4**, LLM-origin errors **5** → the deterministic override is **+11 net** on university.

## Appendix B — Structured flags fed to the harness

13 flags across 11 conversations (2 identity, 1 label-wrong, 1 label-missing, 9 attr-wrong-university); full file: [feedback_2026-07-19-sweep50.json](../accuracy_optimization/tagassigner/inputs/feedback_2026-07-19-sweep50.json). Judgment calls (Nilay/Farhan not flagged; Sıla mapped to cw 707; Mine's self-healed `yerlesti` noted not flagged) are recorded in that file's `converter_notes`.
