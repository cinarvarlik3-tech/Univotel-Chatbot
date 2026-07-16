# Spec 027 — TagAssigner Modes A/B/C Fix Plan (Spec 026 follow-up)

**Status:** Ready for execution — plan only, no code written yet
**Date:** 2026-07-15
**Predecessor:** `docs/026_tagassigner_sweep_error_handoff.md` (error taxonomy)
**Audience:** Engineer executing the fix. Each phase is self-contained and can run in a fresh chat context.

---

## 0. Governing principles (read first)

The three persistent Spec-026 errors are the three decisions currently delegated to the LLM (or to a stale table check) that models disagree on. **Every fix moves the decision into deterministic Router code.** Router ownership *is* model-agnosticism.

**Hard constraints:**
- **Model-agnostic.** Behavior must be identical across `gemini-2.5-flash`, `gpt-5.4-mini`, `haiku-4.5`. Provider is set by `TAGASSIGNER_PROVIDER` in `.env` (currently `openai` → `gpt-5.4-mini`).
- **No reliance on higher compute.** Do not "fix" anything by raising `LLM_REASONING_EFFORT`. Keep it low/none. Determinism, not compute.
- **Scale to 10–20k conversations per sweep.** Any per-conversation DB load of static data must be cached.
- **`deal_awaiting` is add-only.** TagAssigner may ADD it but must NEVER remove it (closure is a deliberate human workflow with follow-up actions, handled by a future command). `fiyat-soruyor` is bidirectional (Router adds AND removes).

**Ownership after this plan:**

| Label | Owner | Add | Remove |
|---|---|---|---|
| `deal_awaiting` | Router (deterministic) | when on-list AND no serviceable property for uni+gender | **never** (human/command only) |
| `fiyat-soruyor` | Router (deterministic) | when asked-and-not-yet-informed | when informed |
| `university` attribute | LLM proposes + **Router canonicalizes** (option 3) | Router's deterministic match wins on confident disagreement | — |

---

## 1. Allowed APIs & key files (verified signatures — do not invent)

These were read from the live tree on 2026-07-15. Copy from them; do not assume other signatures exist.

**Deal-awaiting (Mode A):**
- `app/tagassigner/deal_awaiting.py` → `apply_deal_awaiting(university_id, labels) -> list[str]` (add-only; currently checks only `is_deal_awaiting_university`).
- `app/db/queries.py:1048` → `is_deal_awaiting_university(university_id: uuid.UUID) -> bool`.
- `app/db/queries.py:684` → `find_hotels_by_gender_and_university(gender: str, university_id: uuid.UUID) -> list[Hotel]` — filters `gender_scope = $gender OR 'mixed'`, `is_visible = true`, `gender_scope IS NOT NULL`, excludes `GLOBAL_NULL_STATE_ID`. **This is RecEngine's exact serviceability predicate** (`app/layers/rec_engine.py:110-120`).
- Conversation gender: `conv.gender` stored as `'female'`/`'male'`/`NULL` (RecEngine uses it directly).
- Router call site: `app/tagassigner/router.py:256` → `apply_deal_awaiting(conv.university_id, info_decision.labels)`.
- `deal_awaiting` is in `label_resolver.ROUTER_OWNED_NEVER_REMOVE` (`app/tagassigner/label_resolver.py:29`) — **keep it there.**

**fiyat-soruyor (Mode B):**
- `app/tagassigner/label_resolver.py:19` → `fiyat-soruyor` currently in `LIST_1_USABLE` (must move out).
- `app/tagassigner/label_resolver.py:229` → `strip_gemini_deal_awaiting(...)` — the pattern to copy for a new `strip_llm_fiyat_soruyor`.
- `app/db/queries.py:639` → `get_messages_for_conversation(conversation_id, since=None) -> list[Message]` (ORDER BY `created_at`, `is_private=false`).
- `app/db/models.py:99` → `Message`: `.content`, `.message_type` (`'inbound'`/`'outbound'`), `.created_at`, `.sent_at`.
- Curated price-intent phrase list already exists: `system_prompts/divergence_classifier_prompt.md:37`.
- Prompt section to delete: `system_prompts/tagassigner_prompt.md:234-251`.
- Router integration point: `app/tagassigner/router.py:245-256` (right before/with `apply_deal_awaiting`).

**University canonicalization (Mode C):**
- `app/layers/matching.py` → `scan_entities_by_ngram(text, universities, aliases) -> MatchResult`, `normalize(text) -> str`, `match_campus(text, parent_id, campuses, aliases)`, `MatchConfidence` enum, `MatchResult(confidence, university_id, parent_university_id)`.
- `app/db/queries.py:978` → `get_all_universities() -> list[University]`; `:984` → `get_all_university_aliases() -> list[UniversityAlias]`; `:1025` → `get_campuses_for_parent(parent_id) -> list[UniversityParentMap]`.
- Existing thin resolver (the "P" side of option 3): `app/tagassigner/university_resolver.py` → `resolve_university_list_value(proposed, label_map)`.
- Router resolution point: `app/tagassigner/router.py:177-189`.
- LLM output parse: `app/tagassigner/payload_builder.py:133-167` (`parse_tag_result`) — requires every key in `TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES`.

**Anti-patterns to avoid:**
- Do NOT wire the `university_aliases` table into TagAssigner by hand — reach it through `scan_entities_by_ngram` (which already consumes aliases).
- Do NOT reuse `scan_entities_by_ngram` output blindly: a bare `istanbul` alias resolves to the İÜ **parent** (intentional — leads say "istanbul" for İstanbul Üniversitesi). Accept only campus-level (`university_id`) matches at the top precedence tier; parent-only matches degrade to `bilinmiyor-kampus`.
- Do NOT run token-containment on bare district names without the district stoplist (it will match campuses named after districts, e.g. `kadıköy → Doğuş-Kadıköy`).
- Do NOT let `deal_awaiting` become removable.
- Do NOT raise reasoning effort as a fix.

---

## Phase 0 — Clean baseline re-grade (do before any code)

**Why:** The Spec-026 graded sweep (2026-07-14 18:55 UTC) predates the current prompt/router (mtime 21:43) and ran under a since-changed config. We must measure improvement against the *current* worktree, not the stale artifact.

**What to do:**
1. With `uvicorn` running and current `.env` (`TAGASSIGNER_PROVIDER=openai`):
   ```bash
   ./scripts/tag sweepclean --confirm
   ./scripts/tag importConvo --10
   ./scripts/tag sweep --10
   ```
2. Pull each conversation's stored output + resolved state:
   ```sql
   SELECT c.chatwoot_conversation_id, r.gemini_result, r.completed_at
   FROM conversations c JOIN tag_assigner_runs r ON r.conversation_id=c.id
   JOIN (SELECT conversation_id, MAX(completed_at) mx FROM tag_assigner_runs
         WHERE status='success' GROUP BY conversation_id) x
     ON x.conversation_id=r.conversation_id AND x.mx=r.completed_at;
   ```
3. Repeat the sweep with `TAGASSIGNER_PROVIDER=gemini` and `=anthropic` (restart uvicorn between). Record which of the 5 Spec-026 errors reproduce **per model**.

**Deliverable:** a baseline table `mode × still-reproduces × {gemini, openai, anthropic}`. This is the yardstick for every later phase and quantifies the model-agnostic gap being closed.

**Verification checklist:**
- [ ] Baseline table captured for all 3 providers.
- [ ] For each flagged CW ID (83, 207, 586, 808, 1044, 702) the current behavior is recorded, not assumed.

---

## Phase 1 — Mode A: `deal_awaiting` serviceability add-gate

**Goal:** Stop adding `deal_awaiting` to leads we can actually serve. Add-only preserved; removal out of scope.

**What to implement (copy RecEngine's predicate — do not reinvent):**

1. New query in `app/db/queries.py`, sibling to `find_hotels_by_gender_and_university` (`:684`): `has_any_serviceable_property(university_id) -> bool` — same filters minus the gender clause (`is_visible=true AND gender_scope IS NOT NULL AND id != GLOBAL_NULL_STATE_ID`). Used only when gender is unknown.

2. Change `app/tagassigner/deal_awaiting.py::apply_deal_awaiting` to take gender and apply the serviceability gate. Semantics:
   ```
   add deal_awaiting  ⟺  university_id set
                          AND is_deal_awaiting_university(university_id)
                          AND NOT serviceable(university_id, gender)
   where serviceable(uid, g):
     g in ('female','male') → find_hotels_by_gender_and_university(g, uid) is non-empty
     g is None/unknown      → has_any_serviceable_property(uid)   # conservative: any property ⇒ don't apply
   ```
   Keep it **add-only** (never removes; still no-op when `deal_awaiting` already present or `university_id` is None).

3. Update the one call site `app/tagassigner/router.py:256` to pass `conv.gender`.

**Do NOT:** remove `deal_awaiting` from `ROUTER_OWNED_NEVER_REMOVE`; add any removal path; touch the `deal_awaiting_universities` table (list hygiene is a human/ops job).

**Verification checklist:**
- [ ] `tests/test_deal_awaiting.py` extended: (a) on-list + no property for gender → adds; (b) on-list + property exists for gender → does NOT add; (c) on-list + gender unknown + any property → does NOT add; (d) on-list + gender unknown + zero properties → adds; (e) already-present label preserved.
- [ ] Empirical: on a **fresh re-import** (labels cleared), CW 1044 (Marmara Maltepe, Kız) and CW 207 (Sağlık Bilimleri, unknown) receive **no** `deal_awaiting`. (Note: a re-sweep of an already-labeled conversation will NOT strip an existing label — that's expected; verify on fresh state.)
- [ ] A synthetic male lead on a female-only deal-list school still receives `deal_awaiting` (Yeditepe-class not regressed).

---

## Phase 2 — Mode B: `fiyat-soruyor` full Router ownership

**Goal:** Router computes `fiyat-soruyor` deterministically (add AND remove); LLM no longer touches it.

**Semantics (state machine, per product definition "asked and not yet informed"):**
```
fiyat-soruyor ⟺ (∃ inbound message matching PRICE_ASK)
                AND NOT (∃ outbound message matching PRICE_DELIVERED
                         with created_at ≥ the last matching inbound PRICE_ASK)
PRICE_ASK (inbound, normalized): explicit price tokens only —
   "fiyat", "ücret", "ne kadar", "kaça", "aylık kaç", "kaç tl", "fiyat ne",
   "fiyat nedir", "fiyat bilgisi", "ücretler", "price", "how much"
   (reuse system_prompts/divergence_classifier_prompt.md:37). Generic "bilgi"/"detay" do NOT qualify.
PRICE_DELIVERED (outbound): regex \d+\s*tl   OR   ("detaylar ve fiyat bilgisi" AND a drive link)
   (a bare drive link alone does NOT qualify — photos/location use drive too)
```

**What to implement:**
1. New module `app/tagassigner/fiyat_soruyor.py`: `compute_fiyat_soruyor(messages: list[Message], labels: list[str]) -> list[str]` — pure function; applies the state machine over ordered messages; adds or removes the label. Normalize with `app.layers.matching.normalize` for accent/case-robust matching.
2. `app/tagassigner/label_resolver.py`: move `fiyat-soruyor` **out of** `LIST_1_USABLE`; add `strip_llm_fiyat_soruyor(labels)` copying `strip_gemini_deal_awaiting` (`:229`).
3. `app/tagassigner/router.py`: in `apply_tagassigner_result`, strip the LLM's `fiyat-soruyor` (alongside the existing `strip_gemini_deal_awaiting`/`strip_gemini_info_check` at `:172`), then after `resolve_labels`, call `compute_fiyat_soruyor(messages, resolved)`. `apply_tagassigner_result` must have `messages` — load via `get_messages_for_conversation(conversation_id)` if not already passed (batch path `batch_client.process_batch_results` calls it without messages).
4. `system_prompts/tagassigner_prompt.md`: delete the `fiyat-soruyor` section (`:234-251`); remove it from any label list and the final checklist. Also fix the stale `model: "gemini-2.5-flash-lite"` self-declaration at `:12`.

**Verification checklist:**
- [ ] New `tests/test_fiyat_soruyor.py`: widget opener only → not applied (fixes Büşra/Ben Kısaca B1); explicit "fiyat ne kadar" then no price sent → applied; price ask then bot "15000 TL" → removed (fixes Muhammet B2); price ask then "Detaylar ve fiyat bilgisi:" + drive → removed; ask-after-delivery re-applies.
- [ ] `grep -n "fiyat-soruyor" system_prompts/tagassigner_prompt.md` returns nothing.
- [ ] `grep -n "fiyat-soruyor" app/tagassigner/label_resolver.py` shows it is NOT in `LIST_1_USABLE`.
- [ ] Re-grade CW 586, 808, 83 across all 3 providers → identical `fiyat-soruyor` outcome (proves determinism).

---

## Phase 3 — Mode C: deterministic university canonicalization (option 3)

**Goal:** LLM proposes; Router canonicalizes deterministically and overrides on confident disagreement. Fixes Kent→Kültür (C2) and Atlas→bilinmiyor-kampus (C1) with no extra compute.

**What to implement:**

1. New module `app/tagassigner/university_canonicalizer.py`:
   - `DISTRICT_STOPLIST` constant (normalized): `kadikoy, cevizlibag, besiktas, avcilar, mecidiyekoy, taksim, atakoy, atasehir, kartal, beylikduzu, bakirkoy, sisli, umraniye, uskudar, fatih, eyup, esenyurt, dudullu, hamidiye, ayazaga, …` (seed from the prompt's district-guard list; extend as needed).
   - `FACULTY_STOPLIST`: `tip, fakultesi, fakulte, muhendislik, hukuk, tibbi, dis, hastane, arastirma, egitim, meslek, yuksekokul, myo, onlisans, lisans, bolum, bolumu`.
   - `token_containment(phrase, universities) -> Optional[University]`: unique university whose `normalize(name)+short_name` token set contains ALL significant lead tokens (after dropping FACULTY+DISTRICT+structural tokens). Return only on a unique hit.
   - `canonicalize(phrase, universities, aliases, campuses_by_parent) -> CanonResult` with **precedence**:
     1. `scan_entities_by_ngram` → EXACT/ALIAS with `university_id` (campus) ⇒ that campus.
     2. `token_containment` unique campus ⇒ that campus.
     3. `scan_entities_by_ngram` → `parent_university_id` ⇒ `match_campus` over phrase; if a campus resolves ⇒ it; elif parent is single-campus ⇒ that campus; else ⇒ `bilinmiyor-kampus` (institution known, campus not).
     4. else ⇒ none.
   - This precedence is why the intentional `istanbul → İÜ parent` alias never hijacks `istanbul kent → Kent` (tier 2 wins) yet bare `istanbul` still yields İÜ→`bilinmiyor-kampus` (tier 3).

2. **Cache the university universe** (`get_all_universities` + `get_all_university_aliases` + parent map) behind a module-level TTL cache (e.g. 10 min) so a 10–20k sweep loads it once, not per conversation.

3. LLM contract (option 3 — additive, backward-compatible):
   - `system_prompts/tagassigner_prompt.md`: add an OPTIONAL output field `university_mention` = the **verbatim university words the lead used** (or `bilinmiyor`). Keep `university` (best-effort list guess) as today. Keep the district/persona/multi-university guards — they decide *whether* to echo a mention at all.
   - `app/tagassigner/payload_builder.py::parse_tag_result`: read `university_mention` if present; do NOT make it a required key (option-3 fallback must survive its absence).

4. Router `app/tagassigner/router.py:177-189`: compute both signals and apply option-3 override:
   ```
   P_id = resolve_university_list_value(result.attributes["university"], label_map)   # LLM's list guess (belt)
   M    = canonicalize(university_mention or <scan inbound messages>, cached universe) # deterministic (suspenders)
   final_uni_id = M.campus_id            if M is a confident campus            # M wins on confidence
                = None (bilinmiyor-kampus) if M is parent-ambiguous
                = P_id                    otherwise (fallback)
   log an override whenever M.campus_id and P_id disagree   # for grading
   ```

**Do NOT:** change the LLM to "pick from the list" harder; add per-school aliases for near-name cases (token-containment handles Kent/Kültür without them); remove the `istanbul` alias.

**Verification checklist (all run WITHOUT an LLM — pure functions):**
- [ ] New `tests/test_university_canonicalizer.py` table (validated on live data 2026-07-15):
  `İstanbul kent üniversitesi → Kent-Taksim` (C2), `Atlas tıp fakültesi → Atlas-Hamidiye` (C1),
  `kültür üniversitesi → Kültür`, `çapa tıp → İÜ Çapa Tıp`, `bahçeşehir tıp → Bahçeşehir Tıp`,
  `marmara maltepe → Marmara Maltepe`, `beykent ayazağa → Beykent Ayazağa` (not İTÜ),
  `doğuş dudullu → Doğuş Dudullu`;
  guards → NONE: `kadıköy`, `cevizlibağ`, `hamidiye`, `tıp fakültesi`, `kız öğrenci`;
  `istanbul` alone → İÜ parent / `bilinmiyor-kampus`.
- [ ] Cache proven: a 10k-row sweep issues the 3 universe queries a bounded number of times, not per-conversation.
- [ ] Re-grade CW 83, 808 across all 3 providers → identical resolved university (proves determinism); CW 83 no longer cascades into a wrong `deal_awaiting` (Kent not on deal-list).

---

## Phase 4 — Cross-model verification & acceptance

**What to do:**
1. Run the full unit suite: `test_deal_awaiting.py`, `test_fiyat_soruyor.py`, `test_university_canonicalizer.py`, plus existing `test_label_resolver.py`, `test_payload_builder.py`.
2. Re-run `sweepclean → importConvo --10 → sweep --10` under **each** provider (`gemini`, `openai`, `anthropic`), restarting uvicorn between.
3. Compare against Phase 0 baseline.

**Acceptance criteria:**

| CW ID | Lead | Pass criteria |
|---|---|---|
| 1044 | Döner | No `deal_awaiting` on fresh import; uni=Marmara Maltepe; gender=Kız |
| 207 | Elif | No `deal_awaiting` on fresh import; uni=Sağlık Bilimleri |
| 586 | Büşra | No `fiyat-soruyor`; uni=Haliç |
| 808 | Ben Kısaca | No `fiyat-soruyor`; uni=**Atlas Üniversitesi** (not bilinmiyor-kampus) |
| 83 | Muhammet | `fiyat-soruyor` removed at end; uni=**Kent - Taksim** (not Kültür); no `deal_awaiting` |
| 702 | Arzu | uni resolves without `[tek kampüs]` leakage |

- [ ] **Model-agnostic proof:** for A/B/C the resolved labels+university are identical across all 3 providers on every flagged lead. Any divergence means a decision is still leaking to the LLM — investigate before closing.
- [ ] `LLM_REASONING_EFFORT` still low/none (no compute crutch introduced).

---

## Appendix A — Empirical evidence backing this plan (2026-07-15)

- **Mode A predicate is RecEngine's:** `find_hotels_by_gender_and_university('female', Marmara-Maltepe)` → Academic House Maltepe(90)+Ataşehir(100) — the pitched property → non-empty → correctly no label. Sağlık Bilimleri has female+mixed inventory → gender-unknown → no label.
- **Mode C matcher proven on live data** via the two-layer canonicalizer: C1 Atlas resolves via n-gram (ATLAS short-name), C2 Kent via token-containment; district stoplist makes `kadıköy`/`cevizlibağ`/`hamidiye` return NONE while all positive controls pass.
- **Landmine:** alias `istanbul → parent c51006fd…` (İÜ) is intentional (leads answer "istanbul" for İstanbul Üniversitesi) — precedence tiers keep it from hijacking specific matches.

## Appendix B — Out of scope / follow-ups

- One-time cleanup of the 2 historical leads already carrying wrong `deal_awaiting` — handled by the human/command workflow (not TagAssigner).
- `deal_awaiting_universities` list hygiene — manual ops task.
- Optional alias-hygiene audit for other over-broad single-token aliases.
- Decision to commit the uncommitted `app/llm/` provider abstraction.

*End of plan.*
