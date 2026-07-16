# Spec 028 — TagAssigner Bug Fixes 2 (Mode C mention-fallback fix)

**Status:** Ready for implementation — plan only, no code written yet
**Date:** 2026-07-15
**Predecessor:** `docs/026_tagassigner_sweep_error_handoff.md` (original error taxonomy), `docs/027_tagassigner_mode_abc_fix_plan.md` (Mode A/B/C implementation, already merged)
**Audience:** Engineer executing the fix. Self-contained — can run in a fresh chat context.

---

## 0. Background

Spec 027 shipped Modes A/B/C (deal_awaiting gating, fiyat-soruyor Router ownership, deterministic university canonicalization). A live sweep on 2026-07-15 (10 conversations, `TAGASSIGNER_PROVIDER=openai` / `gpt-5.4-mini`) was graded and investigated end-to-end. This spec is the fix for the one root cause found.

**Code-version check (resolved, not in question):** the sweep ran the current code. Verified two ways — pycache for `router.cpython-312.pyc` / `university_canonicalizer.cpython-312.pyc` compiled at 17:12:53, after the last source edit (17:09:43) and before the sweep (17:24:51); and behaviorally, re-running `resolve_university_override()` against the exact stored sweep inputs reproduces the exact stored Chatwoot values. No staleness involved — do not re-litigate this.

---

## 1. Root cause

`university_mention` (the optional field Mode C added for the LLM to echo the lead's raw university words) was **absent from all 10 rows** of the sweep — `gpt-5.4-mini` never emits it. The prompt labels it `optional — best effort` (`system_prompts/tagassigner_prompt.md:65`), so the model skips it.

When `mention` is absent, `resolve_university_override()` (`app/tagassigner/university_canonicalizer.py:190`) falls back to canonicalizing `proposed_uni` — **the LLM's own `attributes.university` guess** — instead of the lead's actual words. This makes the safety net check the LLM's answer against itself, which structurally cannot catch a hallucinated campus: if the LLM guesses `"Bahçeşehir Üniversitesi - Kuzey"` for a lead who only wrote "bahcesehir", canonicalizing that guess just returns that same guess with `CanonConfidence.CAMPUS` (exact list-value match), because the guess string itself is a valid, well-formed campus name.

**Proof the deterministic matcher is not the problem — the input routed to it is.** Re-running `canonicalize()` on the *lead's own raw words* (bypassing the LLM's guess entirely) produces the correct result in every case from the sweep:

```
canonicalize('bahcesehir')                       -> parent_only  (correct: withhold)
canonicalize('Topkapı üniversitesi')             -> parent_only  (correct: withhold)
canonicalize('medeniyet Üniversitesi')           -> parent_only  (correct: withhold)
canonicalize('Bogazici University')              -> parent_only  (correct: withhold)
canonicalize('yeditepe')                         -> campus       (correct: resolves, single campus)
canonicalize('sbü')                              -> campus       (correct: resolves, single campus)
canonicalize('Topkapı Üniversitesi Altunizade')  -> parent_only  (correct: withhold — campus not in DB)
```

Confirmed against live Chatwoot state, 4 of 10 swept conversations wrote a hallucinated campus that should have withheld as `bilinmiyor-kampus`:

| cw | Lead | Campus given? | Wrote (wrong) | Should be |
|---|---|---|---|---|
| 641 | "Üniversitem:bahcesehir" | no (3 campuses) | `Bahçeşehir Üniversitesi - Kuzey` | `bilinmiyor-kampus` |
| 237 | "Topkapı üniversitesi" | no (3 campuses) | `Topkapı Üniversitesi - Topkapı` | `bilinmiyor-kampus` |
| 1072 | "medeniyet Üniversitesi" | no (3 campuses) | `Medeniyet Üniversitesi - Ünalan/Göztepe` | `bilinmiyor-kampus` |
| 1049 | "My University: Bogazici University" | no (2 campuses) | `Boğaziçi - Ana Kampüs` | `bilinmiyor-kampus` |

Correctly resolved in the same sweep (not to be regressed): cw909 Yeditepe (single-campus), cw1217 sbü/Sağlık Bilimleri (single-campus), cw430 Topkapı Altunizade (correctly withheld — data gap, see §5), cw326/420/526 (no university stated, correctly `bilinmiyor`).

**Measured accuracy this run (university-matching dimension only, cw430 excluded as a data gap not a code bug):** 5/9 correct = ~56%, not the ~89% a surface read suggests (cw237 "Kh. Mahad" looks plausible and was mis-graded as correct-withhold in a prior manual pass — it is not; live Chatwoot confirms a campus was written).

**Policy decision (made by product owner 2026-07-15, do not re-litigate):** when an institution is named with no campus and the institution has multiple campuses, TagAssigner must **withhold** (`bilinmiyor-kampus`) — never guess, never default to a "primary" campus. This applies uniformly, including to Bahçeşehir — bare "bahçeşehir" must withhold, **not** resolve to Çırağan or any other specific campus. No per-university default-campus feature is in scope for this spec.

---

## 2. Governing principles (carried over from spec 027, still apply)

- **Model-agnostic.** Must behave identically across `gemini-2.5-flash`, `gpt-5.4-mini`, `haiku-4.5`. This fix is specifically about *not depending* on the LLM reliably emitting an optional field — the whole point of moving to Router-computed input.
- **No reliance on higher compute.** Do not raise `LLM_REASONING_EFFORT` to get the model to emit `university_mention` more reliably. Fix it deterministically in the Router instead.
- **Scale to 10–20k conversations per sweep.** No new per-conversation unbounded DB/API calls.
- **Never invent a campus.** `bilinmiyor-kampus` is not a failure state — for multi-campus institutions named without a campus, it is the only correct output.

---

## 3. Fix — Router-computed mention, LLM echo becomes a pure fallback

**Goal:** Stop trusting the LLM to reliably populate `university_mention`. Compute the canonicalization input deterministically from the lead's own inbound messages in the Router, and only fall back to the LLM's `university_mention` / `attributes.university` guess when the deterministic scan itself finds nothing.

### 3.1 What to implement

1. **New function** in `app/tagassigner/university_canonicalizer.py`: `extract_university_phrase_from_messages(messages: list[Message]) -> Optional[str]`.
   - Pure function (aside from taking already-loaded `messages`, no I/O).
   - Scans **inbound** messages only (the lead's own words — mirrors what `fiyat_soruyor.py` already does for its own transcript scan, same file/pattern to copy).
   - Do not just concatenate the whole transcript and feed it to `canonicalize()` — that risks token-containment or n-gram matches on institution names mentioned in bot template text (Router-authored pitch messages reference specific universities near a hotel, e.g. "Marmara Üniversitesi, Ticaret Üniversitesi vb. civar okullarına" — inbound-only avoids this entirely, which is why inbound-only is a hard requirement, not just an optimization).
   - Within inbound messages, this only needs to hand the **concatenated inbound text** (or the single most relevant inbound message — see 3.2 for the tie-breaking approach) to `canonicalize()`; `canonicalize()` already runs `scan_entities_by_ngram` + `token_containment` internally, so no separate keyword-matching needs to be built here — reuse, don't reinvent.
   - Normalize/join multiple inbound messages so a lead who writes "Topkapı üniversitesi" in one message and "Altunizade kampüsü" in a later one (cw430's actual shape) still resolves as one phrase — see cw430 transcript in Appendix A.

2. **`app/tagassigner/router.py`**, in `apply_tagassigner_result` (around line 199-211, the existing Mode C override block):
   - Router already loads or can load `full_history_messages` / `get_messages_for_conversation` (Mode B's `compute_fiyat_soruyor` already needs the same messages — reuse that same fetch, do not add a second DB round-trip. Check the existing `full_history_messages` plumbing added for Mode B at router.py:145-158 before adding a new load path).
   - Compute `deterministic_phrase = extract_university_phrase_from_messages(messages)`.
   - Pass this as the primary `mention` input to `resolve_university_override()`, **not** `result.university_mention`.
   - `result.university_mention` (the LLM's echo) becomes the fallback used only when `deterministic_phrase` is `None`/empty — i.e. reverse today's priority. Keep the field and its parsing in `payload_builder.py` (still useful for older/other-provider responses and as a debugging signal in `gemini_result`), but it is no longer the primary channel.

3. **`app/tagassigner/university_canonicalizer.py`::`resolve_university_override`** — no signature change needed if the caller does the swap described in 3.2 below; confirm the existing precedence logic (CAMPUS wins, PARENT_ONLY only downgrades when the belt itself doesn't resolve, NONE/sentinel falls through to belt) still holds correctly when `mention` is now Router-computed instead of LLM-echoed. Re-read the docstring at lines 165-209 before touching it — the precedence was already fixed once during spec 027's code review pass and must not regress.

### 3.2 Precise call-site change (router.py)

Current (spec 027) shape, approximately:
```python
universe = await get_university_universe()
override_uni = resolve_university_override(
    proposed_uni, result.university_mention, label_map, universe
)
```

New shape:
```python
universe = await get_university_universe()
messages = full_history_messages or await queries.get_messages_for_conversation(conversation_id)
deterministic_mention = extract_university_phrase_from_messages(messages)
override_uni = resolve_university_override(
    proposed_uni,
    deterministic_mention or result.university_mention,
    label_map,
    universe,
)
```
(Confirm whether `full_history_messages` is guaranteed populated for both the `run_tagging` full-history path and the batch path per the existing Mode B wiring — if the batch path can arrive with `full_history_messages=None`, reuse whatever fallback load Mode B already added rather than introducing a second one.)

### 3.3 Do NOT

- Do not have `extract_university_phrase_from_messages` scan outbound/bot messages — this is the mechanism that prevents the pitch-template false-positive risk described in 3.1.
- Do not remove `result.university_mention` from `TagResult` / `parse_tag_result` — it stays as a fallback and as sweep-debugging signal in `gemini_result`.
- Do not add a per-university "default campus" concept. Explicitly out of scope per the 2026-07-15 policy decision (§1) — bare "bahçeşehir" withholds like every other bare multi-campus mention.
- Do not change `canonicalize()`'s internal precedence tiers (n-gram exact/alias → token-containment → parent+match_campus) — they are already proven correct (§1); only the *input* fed to them changes.
- Do not raise `LLM_REASONING_EFFORT` as an alternative fix.

---

## 4. Verification checklist

**Unit tests** (extend `tests/test_university_canonicalizer.py`, add new pure-function tests for `extract_university_phrase_from_messages` — no LLM, no network):

- [ ] `extract_university_phrase_from_messages` on a `messages` fixture shaped like cw641 (`Üniversitem:bahcesehir`, one inbound message) returns a phrase that canonicalizes to `parent_only`.
- [ ] Same for cw237-shaped fixture (`"Topkapi university please"` + `"Üniversitem Topkapı üniversitesi"` across two inbound messages) — must combine both inbound messages, not just the first — returns `parent_only`.
- [ ] Same for cw1072 (`"medeniyet Üniversitesi"`) and cw1049 (`"My University: Bogazici University"`) — both `parent_only`.
- [ ] cw430-shaped fixture (`"Merhaba fiyat bilgisi alabilir miyim"` then `"Topkapı üniversitesi Altunizade kampüsü"`) — combines to `parent_only` (Altunizade isn't in the DB fixture either, so this is really testing the campus-not-found path, not the multi-message combination path — cover both with separate fixtures if the combination logic needs its own dedicated case).
- [ ] cw909-shaped fixture (`"Üniversitem: yeditepe"`) — single-campus parent, resolves to `campus`.
- [ ] cw1217-shaped fixture (`"Üniversitem: sbü"`) — single-campus, resolves to `campus`.
- [ ] A fixture with a bot/outbound message mentioning a *different* specific university (mirroring the real "Marmara Üniversitesi, Ticaret Üniversitesi vb." pitch text) alongside an inbound message naming nothing — confirms outbound text is never scanned and the result stays `bilinmiyor`/`parent_only`, not hijacked by the bot's own copy.
- [ ] `resolve_university_override` end-to-end with the Router-computed mention takes precedence over a present-but-wrong `result.university_mention` (simulate a provider that *does* emit `university_mention` but gets it wrong — deterministic scan must still win).
- [ ] `resolve_university_override` falls back to `result.university_mention` only when the deterministic scan returns `None` (e.g. a message-loading edge case).

**Empirical — fresh re-import + re-sweep** (`sweepclean --confirm` → `importConvo` for the same 4 leads → `sweep`, restart uvicorn after code changes per project convention):

- [ ] cw641 (Bahçeşehir/ebrukapicioglu): `university` = `bilinmiyor-kampus`, not Kuzey.
- [ ] cw237 (Topkapı/Kh. Mahad): `university` = `bilinmiyor-kampus`, not Topkapı-Topkapı.
- [ ] cw1072 (Medeniyet): `university` = `bilinmiyor-kampus`, not Ünalan/Göztepe.
- [ ] cw1049 (Boğaziçi): `university` = `bilinmiyor-kampus`, not Ana Kampüs.
- [ ] No regression: cw909 (Yeditepe) still resolves to Yeditepe; cw1217 (sbü) still resolves to Sağlık Bilimleri; cw430 (Altunizade) still withholds; cw326/420/526 still `bilinmiyor`.

**Cross-provider (Phase 4 style, carried over from spec 027 — still owed):**

- [ ] Re-run the same 4 conversations under `gemini` and `anthropic` providers. Since the fix removes dependence on the LLM emitting `university_mention` at all, all three providers should now produce identical `bilinmiyor-kampus` results for cw641/237/1072/1049 regardless of what each model's `attributes.university` guess or `university_mention` echo says. This is the strongest proof the fix is model-agnostic — if any provider still resolves one of these to a specific campus, the Router-computed `deterministic_mention` is not actually winning precedence and `resolve_university_override`'s logic needs re-inspection, not a per-provider patch.

---

## 5. Explicitly out of scope for this spec (do not fix here)

- **Topkapı Altunizade campus** (cw430, "İhsan Yiğit") — confirmed a pure data gap, not a code bug. No `Altunizade` row exists anywhere in `universities`, `university_aliases`, or `university_chatwoot_label_map` for İstanbul Topkapı Üniversitesi (which has exactly 3 campuses: Kazlıçeşme, Levent TSYD, Topkapı). Withholding is currently correct. If ops confirms this campus should exist, that's a migration (add the university row + alias + Chatwoot label map row, pattern-matched on `migrations/025_capa_tip_chatwoot_mapping.sql`) — not touched by this spec.
- **`ogrenci_cinsiyet` stray label leakage** (seen in cw641, cw1217's `gemini_result.labels`) — confirmed cosmetic. `resolve_labels` (`label_resolver.py`) only ever writes labels present in `LIST_1_USABLE`/`LIST_2_TERMINAL`, and `ogrenci_cinsiyet` is in neither, so it is silently dropped before any Chatwoot write — live labels confirmed clean (`['universitede']` only). Optional low-priority prompt tightening if it recurs at higher volume, not required by this spec.
- **Per-university default-campus feature** — explicitly rejected by the 2026-07-15 policy decision (§1). Do not implement.
- **Mode A / Mode B (deal_awaiting, fiyat-soruyor)** — both verified working correctly in this sweep (no false `deal_awaiting`; `fiyat-soruyor` correctly applied on cw430's explicit price ask and correctly suppressed on cw326 after the bot sent "35000 TL"). Not touched by this spec.

---

## Appendix A — Raw transcripts for the 4 regression cases (captured 2026-07-15, live DB)

**cw641 — ebrukapicioglu:**
```
[IN]  Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum. Üniversitem:bahcesehir
[OUT] Merhabalar Kız öğrenci için mi bakıyordunuz erkek öğrenci için mi efendim?
[IN]  Erkek
[OUT] Osmanbey'de bulunan GK regency 4 yıldızlı otelimizi iletiyorum sizlere ...
```
LLM wrote `attributes.university = "Bahçeşehir Üniversitesi - Kuzey"`; no campus was ever stated.

**cw237 — Kh. Mahad:**
```
[IN]  Merhabalar Univotel! Academic House Ataşehir Kız Öğrenci Yurdu hakkında bilgi alabilir miyim? Detayları öğrenebilir miyim? Üniversitem:
[OUT] Merhabalar efendim
[OUT] Size daha iyi yardımcı olabilmem için hangi üniversite ve hangi kampüsteydeniz efendim?
[OUT] Efendim?
[IN]  Topkapi university please
[IN]  Üniversitem Topkapı üniversitesi
[IN]  Cevabınızı bekliyorum. Ortak odaya ihtiyacım var
```
LLM wrote `"Topkapı Üniversitesi - Topkapı"`; live Chatwoot custom_attributes confirms this was written. Contact name confirmed via Chatwoot API: "Kh. Mahad". No campus was ever stated — this is the same failure class as cw641, not a correct withhold.

**cw430 — İhsan Yiğit:**
```
[IN]  Merhaba fiyat bilgisi alabilir miyim
[OUT] Size daha iyi yardımcı olabilmem için hangi üniversite ve hangi kampüsteydeniz efendim?
[IN]  Topkapı üniversitesi Altunizade kampüsü
```
LLM wrote `bilinmiyor`; university correctly withheld (data gap, not a code bug — see §5). `fiyat-soruyor` correctly applied by Mode B.

**cw1072 — (Medeniyet):**
```
[IN]  Bana en yakın Univotel neresi? Üniversitem: medeniyet Üniversitesi. Bayan için Tek kişilik oda fiyat bilgisi verebilir misiniz lütfen
[OUT] Tabiki de efendim sizlere iki lokasyonumuzu ileteyim
[OUT] Academic House Ataşehir, ... Yeditepe, Acıbadem vb. çevre üniversitelerine ...
[OUT] Academic House Kadıköy, ...
```
LLM wrote `"Medeniyet Üniversitesi - Ünalan/Göztepe"`; no campus was ever stated (İstanbul Medeniyet Üniversitesi has 3 campuses: Cevizli/Kartal, Orhanlı, Ünalan/Göztepe). Note the outbound pitch text mentions "Yeditepe, Acıbadem" — this is exactly the kind of bot-authored text that must never be scanned by `extract_university_phrase_from_messages` (§3.3).

**cw1049 — (Boğaziçi):**
```
[IN]  Hello! I'm looking for a student dormitory. My University: Bogazici University
[OUT] Tabiki de efendim
[OUT] Kız öğrenci için mi bakıyordunuz erkek öğrenci için mi efendim?
[IN]  Kız öğrenci
[OUT] Efendim GK Rezidans, ...
```
LLM wrote `"Boğaziçi - Ana Kampüs"`; no campus was ever stated (Boğaziçi has 2 campuses: Ana Kampüs, Anadolu Hisarı).

---

*End of spec.*
