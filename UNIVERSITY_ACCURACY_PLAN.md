# UNIVERSITY_ACCURACY_PLAN.md — University Coverage Fixes

**Status:** ✅ **IMPLEMENTED 2026-07-20** (see §-1 for what actually shipped vs. planned).
**Context:** University resolution is the dominant TagAssigner accuracy failure (9 of 11
missed conversations in the 50-lead run; correct-write 82%, coverage only **64%**, and
correctness-*given*-a-decision **100%** — i.e. we withhold universities we should write; we
almost never write a wrong one). Root-cause detail:
[docs/problem_explanations_1.md](docs/problem_explanations_1.md) §2 (RC-U1…RC-U7).
Companion (separate concern): [DRIFT_SAVE_PLAN.md](DRIFT_SAVE_PLAN.md).

---

## -1. Implementation record (what shipped, and what the plan got wrong)

Implemented 2026-07-20. Full test suite **450 passing**; `docs/alias_collision_check.py`
**0 hard failures**; targeted validation on the 9 real flagged conversations **all pass**
(6 now resolve to the correct campus, 3 correctly stay `PARENT_ONLY` as accepted withholds);
15-conversation regression spot-check **no regressions**.

**Diagnosis corrections found during implementation (the plan's guesses that were wrong):**

- **`bir`→Biruni was never an alias.** It was a real bug in `normalize()`: a substring (not
  word-boundary) suffix strip chewed "biruni"/"BİRUNİ" down to "bir". **Fixed in
  `app/layers/matching.py:normalize()`** (word-boundary-aware suffix strip) with a regression
  test — no data change. This is the actual RC-U1 root cause for the Biruni cases, deeper than
  "bad alias data."
- **`su`→Sabancı and `yu`→Yeditepe are NOT alias rows** — they match via Tier-1
  `university_short_name` ("SU", "YÜ"), which are genuine abbreviations. Deleting an alias
  would be a no-op. Left as-is (see open items below).
- **MSGSÜ had a two-parent data bug**, not just a missing parent-map row: two
  `parent_universities` rows exist (one clean-named, alias-bearing, campus-less; one
  malformed-named, campus-bearing, alias-less). Migration 027 repoints the campus onto the
  clean parent via `UPDATE` (not the planned `INSERT`).
- **`"bilgi üniversitesi"` as the re-scope target does NOT work** — `normalize()` strips the
  "üniversitesi" word, collapsing it back to bare "bilgi". Migration 026 uses `"istanbul
  bilgi"` / `"istanbul rumeli"` instead (non-collapsing). Locked by a test.

**Shipped changesets:**
- `app/layers/matching.py`: `normalize()` word-boundary fix; **WS3a** confidence-ranked
  `scan_entities_by_ngram`; a **stopword guard** (`_ENTITY_SCAN_STOPWORDS`) so a bare common
  word like "bu"/"su" can't produce a confident false campus match via a colliding short_name
  (the free-text-scan-scoped mitigation for the Tier-1 collisions §0 deferred — added after a
  real conversation, cw1168, surfaced "bu"→Beykent).
- `app/tagassigner/university_canonicalizer.py`: **WS3b** windowed `token_containment`.
- `migrations/026_alias_hygiene.sql`: delete `teknik`; re-scope `bilgi`→`istanbul bilgi`,
  `rumeli`→`istanbul rumeli`. **Applied to DB.**
- `migrations/027_campus_aliases.sql`: Boğaziçi (`güney kampüs`/`rumeli hisarı`/…) + MSGSÜ
  (`fındıklı`/`beyoğlu`) campus aliases; MSGSÜ campus↔parent repoint. **Fully applied to DB**
  (the `UPDATE` repoint was applied 2026-07-20 after author authorization; bare "mimar sinan"
  / "msgsü" now resolves to CAMPUS instead of withholding).
- `docs/alias_collision_check.py`: new **C7** (bare common-word aliases) + **C8**
  (short_name common-word collisions) checks; extracted a pure `find_stoplist_alias_collisions`
  helper.
- Tests: `tests/test_matching.py`, `tests/test_university_canonicalizer.py`,
  new `tests/test_alias_collision_check.py`.

**Open items:**
1. **`su`→Sabancı / `yu`→Yeditepe / `mü`→Marmara / `BÜ`→Beykent short-name collisions**
   (C8/C7 findings). **Decided NOT to guard the Tier-1 discrete-answer path** (2026-07-20):
   there, a bare "SU"/"YÜ" is a *legitimate* abbreviation answer, so guarding it would break
   real matches to prevent a near-nonexistent false positive. The genuine risk — an incidental
   common word in free text — is already handled by `_ENTITY_SCAN_STOPWORDS` in
   `scan_entities_by_ngram`. Left as-is by design.
2. **End-to-end re-grade** (still open, needs a sweep run): re-run TagAssigner on the affected
   `cw` set and re-snapshot through the accuracy harness to confirm the coverage lift in
   production numbers. Validation here was at the canonicalizer level (deterministic); this
   would confirm it end-to-end through the Router + merge.

---

## 0. Scope — decided in review

**IN (this plan):**
- **WS1 — Alias hygiene:** remove/re-scope bare single-token aliases that collide with
  ordinary Turkish words (`bilgi`, `bir`, `su`, `yu`, `rumeli`, …). Fixes RC-U1 (Biruni
  withholds) and removes the latent false-positive-**write** landmine (`bir`→Biruni,
  `su`→Sabancı).
- **WS2 — Campus aliases:** add the specific campus/parent aliases decided in review
  (Boğaziçi güney / Rumeli Hisarı → Ana Kampüs; Mimar Sinan Fındıklı / Beyoğlu → the single
  MSGSÜ entry). Fixes RC-U5 and the Mimar Sinan cases (RC-U6).
- **WS3 — Matcher robustness:** (3a) confidence-ranked entity scan so a real campus token
  beats a spurious earlier parent-alias regardless of position; (3b) windowed
  token-containment so a clean mention buried in widget noise still resolves; (3c) lock
  multi-message (university in msg 1, campus in msg 2) parity with a test. Fixes RC-U2/RC-U6
  and makes multi-message robust.

**OUT / dropped:**
- **Boilerplate-stripping** (was "item 2") — **dropped.** It risked discarding the lead's
  own `Üniversitem:` widget field, and WS1 removes the collision (`bilgi`) at its source so
  there is nothing to strip. WS3b handles the noise structurally without dropping any text.

**DEFERRED (product decision, not in this plan):**
- **Plain parent values on `PARENT_ONLY`** (was "item 5") — İskender / Şükriye / Sami. Needs
  new operator-facing Chatwoot list entries for every multi-campus university and risks the
  LLM lazily writing parents. `bilinmiyor-kampus` is a defensible withhold for these 3. If
  revisited, prefer a **faculty→campus mapping** (e.g. "Amerikan Dili edebiyatı" → Beyazıt)
  over parent values. These 3 conversations are **accepted withholds** for now.

---

## 1. Background — how university resolution works (for a cold implementer)

Runtime path, all read-only to this plan except where noted:

1. Router ([app/tagassigner/router.py](app/tagassigner/router.py)) builds the lead's
   university phrase by concatenating **all inbound messages**
   (`extract_university_phrase_from_messages` in
   [app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py))
   — so a university in message 1 and a campus in message 2 are already seen as one phrase.
2. `resolve_university_override(proposed_uni, mention, label_map, universe, mention_is_authoritative=True)`
   canonicalizes that phrase deterministically and, when authoritative, **overrides the LLM's
   guess.**
3. `canonicalize(phrase, universe)` precedence:
   - `scan_entities_by_ngram` EXACT/ALIAS/LEVENSHTEIN with a **campus** (`university_id`) →
     `CAMPUS`.
   - `token_containment` unique campus hit → `CAMPUS`.
   - `scan` ALIAS with a **parent** → `match_campus`; resolves → `CAMPUS`; single-campus
     parent → that campus; else → `PARENT_ONLY` (`bilinmiyor-kampus`, a withhold).
   - else → `NONE` (belt/LLM guess used).
4. The matching primitives (`scan_entities_by_ngram`, `match_university`, `match_campus`,
   `token_containment`, `normalize`) live in
   [app/layers/matching.py](app/layers/matching.py) and are **shared with InfoGatherer** — so
   fixing them fixes both, and multi-message capability is structural, not new.

**Aliases** live in the `university_aliases` table
(`id, university_id, alias UNIQUE, parent_university_id, created_at`) — an alias points at a
**campus** (`university_id`) or a **parent** (`parent_university_id`). They are added/changed
via **numbered idempotent migration SQL files** (see
[migrations/018c_itu_ayazaga_alias.sql](migrations/018c_itu_ayazaga_alias.sql) as the pattern).
Latest migration is `025`; new files start at **`026`**.

**Why coverage fails today (the four in-scope causes):**
- **RC-U1:** the alias `bilgi` (Turkish for "information", in every greeting) matches İstanbul
  Bilgi Üni; positioned before the real university token, it hijacks the scan → `PARENT_ONLY`
  → withhold. Same class: `bir`→Biruni, `su`→Sabancı (these can even produce false **writes**).
- **RC-U2:** `scan_entities_by_ngram` returns the **first** match in scan order (longest n-gram
  first, then leftmost) with **no confidence ranking**, and `match_university` checks
  parent-aliases *before* exact campuses — so a spurious earlier parent-alias beats a real
  later campus.
- **RC-U5:** missing campus aliases (`güney`/`rumeli hisarı`→Boğaziçi Ana Kampüs;
  `fındıklı`/`beyoğlu`→MSGSÜ) — and `rumeli` actively mis-points to İstanbul Rumeli Üni.
- **RC-U6:** `token_containment` requires **all** phrase tokens ⊆ one university's name, so
  widget noise defeats an otherwise-clean "Mimar Sinan Fındıklı" mention.

---

## 2. ⚠️ Critical sequencing constraint

**WS1 must land before (or with) WS3a.** WS3a makes the scan *prefer the most specific
(campus-level) match*. If the spurious short aliases are still present, that preference would
**amplify** them — e.g. `su`→Sabancı and `bir`→Biruni are EXACT **campus** matches, so a
confidence-ranked scan would pick them *over* a correct parent. Clean the aliases first, then
turn on ranking. Do **not** merge WS3a while `bir`/`su`/`yu`-class aliases still exist.

Recommended order: **WS1 → WS2 → WS3a → WS3b → validate.**

---

## 3. WS1 — Alias hygiene

**Goal:** no single-token alias may be an ordinary Turkish word or a fragment that collides
with normal chat, while keeping every legitimate acronym.

### 3.1 Identify the collisions (data-driven, not by hunch)
Extend [docs/alias_collision_check.py](docs/alias_collision_check.py) with a new check:

- **C7 — common-word / corpus collisions:** flag any single-token alias whose `normalize()`d
  form (a) is in a **Turkish common-word stoplist** (seed it from the greeting/boilerplate
  vocabulary + a general list: `bilgi, bir, su, ve, için, var, yok, okul, yurt, oda, kız,
  erkek, merkez, güney, kuzey, teknik, …`), **or** (b) appears frequently as a token in the
  **real inbound-message corpus** (query `messages WHERE message_type='inbound'`) in
  conversations that are not actually about that university. (a) is the hard gate; (b) is the
  evidence that ranks severity.

The existing C1–C6 checks (cross-target collisions, name-shadow, empty-norm, raw dups) stay.

### 3.2 Remedy per flagged alias (three actions)
- **Delete** when the university already matches via its full name or an unambiguous acronym:
  `bir` (→ matches via `biruni`), `su` (→ `sabancı` / acronym stays elsewhere), `yu`, and any
  2-char word-collision. Zero legitimate matches lost.
- **Lengthen** when the short form is the only hook: `bilgi` → `bilgi üniversitesi` (a 2-token
  alias fires only on the 2-gram, never the greeting's standalone "bilgi").
- **Keep** unambiguous acronyms untouched: `boun, itu, ytu, msgsu, khas, gsu, bau, fsm, izu,
  sbu, pru, ozu, tau, …`.

Confirm the final delete/lengthen list against the C7 output before writing SQL.

### 3.3 Apply
New migration **`migrations/026_alias_hygiene.sql`** — idempotent `DELETE`s for removed
aliases and `INSERT … WHERE NOT EXISTS` (+ `DELETE` of the bare form) for lengthened ones,
wrapped in `BEGIN;`/`COMMIT;` like 018c.

### 3.4 Guard against regression
- Run `docs/alias_collision_check.py` (with C7) — must exit 0.
- Add it to CI, **or** add a unit test under [tests/](tests/) that loads the alias set and
  asserts no single-token alias is in the stoplist. This prevents a future migration
  reintroducing a bare common word.

**Files:** `docs/alias_collision_check.py` (extend), `migrations/026_alias_hygiene.sql` (new),
CI wiring / test (new). **Risk:** low — deletions are only for aliases with a redundant
match path; C7 + corpus scan proves low legitimate usage.

**Fixes on its own:** Sinemhan (988), A. Kaya (977) resolve to Biruni. Removes false-write risk.

---

## 4. WS2 — Campus aliases

**Goal:** add the campus/parent aliases decided in review. Data-only, idempotent migration.

### 4.1 Aliases to add (resolve exact UUIDs at implementation time)
Target by **name**; the implementer looks up the `university_id` / `parent_university_id`:

- **Boğaziçi – Ana Kampüs** (campus) ← `güney kampüs`, `güney yerleşkesi`, `rumeli hisarı`,
  `rumelihisarı`, `hisarüstü`.
  *(Prefer these multi-token forms over a bare `güney`/`rumeli`, which would collide — same
  philosophy as WS1.)*
- **MSGSÜ** — the single list entry is `MSGSÜ - Beşiktaş` (verify there is exactly one; if
  multiple, use the Beşiktaş one). Add **campus** aliases `fındıklı`, `fındıklı kampüsü`,
  `beyoğlu` → that entry, and a **parent** alias `mimar sinan` → the MSGSÜ parent (so the scan
  reaches MSGSÜ before falling to token-containment).

### 4.2 Apply & verify
- New migration **`migrations/027_campus_aliases.sql`** — idempotent inserts (018c pattern).
- Re-run `docs/alias_collision_check.py` — must stay green (confirms none of the new aliases
  collide or get name-shadowed).

**Files:** `migrations/027_campus_aliases.sql` (new). **Risk:** low.

**Fixes (with WS1 removing the `bilgi` hijack so the scan reaches the right parent):** Gülçin
(1126), ayse44klc (937), Görkem (1328), Bilinmeyen (920).

---

## 5. WS3 — Matcher robustness

**File:** [app/layers/matching.py](app/layers/matching.py) and
[app/tagassigner/university_canonicalizer.py](app/tagassigner/university_canonicalizer.py).
**Prereq:** WS1 merged (see §2).

### 5.1 WS3a — confidence-ranked entity scan
Change `scan_entities_by_ngram` from "return the first non-NONE n-gram match" to "collect all
non-NONE matches and return the best," ranked by:

1. **campus-level over parent-level** — a result with `university_id` set beats one with only
   `parent_university_id`.
2. **confidence** — `EXACT` > `ALIAS` > `LEVENSHTEIN`.
3. **n-gram length** desc, then **leftmost** position (stable tiebreak).

Effect: a real EXACT campus token (e.g. `biruni`) beats a spurious earlier parent-alias
regardless of position; makes multi-message robust (campus resolves wherever it appears).
`canonicalize()`'s first branch already returns `CAMPUS` when the scan yields a campus-level
match, so this integrates without changing canonicalize.

**Guardrails:** keep the phrase-gate behavior identical for currently-passing cases; all
existing `app/layers/matching` tests must pass; add tests for (a) campus-EXACT after an
earlier parent-alias wins; (b) parent-only phrase still returns the parent; (c) the Biruni
"greeting-then-university" phrase resolves to campus.

### 5.2 WS3b — windowed token-containment
Change `token_containment` (in `university_canonicalizer.py`) so that instead of requiring
**all** significant tokens of the whole phrase to be ⊆ one university's name tokens, it scans
**token windows** (longest-first) and returns the first **unique** containment hit, keeping the
existing faculty/structural/district stoplist drop. Fixes clean mentions buried in widget
noise (Görkem/Bilinmeyen) generally.

**Priority note:** WS2's `mimar sinan` + `fındıklı`/`beyoğlu` aliases already fix the two known
cases via the scan path, so WS3b is **general robustness, lower priority** — it can ship after
WS3a or be deferred. **Ambiguity risk:** more windows = more chances for a spurious unique
hit; keep the strict "unique hit only" guard and prefer longer windows. Add tests for a
noise-buried mention resolving and for a two-university phrase staying ambiguous (no hit).

### 5.3 WS3c — multi-message parity test
Add a test proving a university stated in message 1 + campus in message 2 resolves end-to-end
through `extract_university_phrase_from_messages` → `canonicalize` (e.g. "Boğaziçi
üniversitesi" then "Rumeli Hisarı" → Ana Kampüs, post-WS2). This is already structurally
supported by concatenation; the test **locks parity with InfoGatherer** and prevents
regression.

**Files:** `app/layers/matching.py`, `app/tagassigner/university_canonicalizer.py`,
`tests/` (matching + canonicalizer). **Risk:** medium (core matcher) — mitigated by the
existing test suite + new cases.

---

## 6. Validation

Because the accuracy harness `snapshot` reads **stored** `university_id`, validating end-to-end
would require re-running TagAssigner on the affected conversations. Cheaper and deterministic:

1. **Targeted resolution test** (primary acceptance): assert that each in-scope conversation's
   real inbound phrase now canonicalizes as expected. Reuse the harness/DB tooling to load the
   live `universe` and run `canonicalize` on the actual concatenated inbound text:

   | cw | Lead phrase | Expected after fix |
   |---|---|---|
   | 988 Sinemhan | "…Biruni üniversitesi…" | `CAMPUS` → Biruni |
   | 977 A. Kaya | "…Biruni üniversitesine…" | `CAMPUS` → Biruni |
   | 1126 Gülçin | "Boğaziçi güney kampüs" | `CAMPUS` → Boğaziçi – Ana Kampüs |
   | 937 ayse44klc | "Boğaziçi … Rumeli Hisarı" | `CAMPUS` → Boğaziçi – Ana Kampüs |
   | 1328 Görkem | "Mimar Sinan Fındıklı …" | `CAMPUS` → MSGSÜ – Beşiktaş |
   | 920 Bilinmeyen | "Mimar Sinan Üni Beyoğlu" | `CAMPUS` → MSGSÜ – Beşiktaş |
   | 1154 İskender / 716 Şükriye / 900 Sami | multi-campus, no campus stated | `PARENT_ONLY` (accepted withhold — item 5 deferred) |

2. **Regression:** `docs/alias_collision_check.py` exits 0; full `app/layers/matching` +
   canonicalizer test suites pass.
3. **No false writes:** confirm no previously-correct university flips (spot-check the leads
   that already resolved correctly — e.g. Nilay 650 Türk Alman, 230 İstanbul Üni, 656
   Yeditepe — still resolve).
4. **(Optional) full harness re-grade:** re-run TagAssigner on the affected `cw` set, then
   `snapshot` + `calculate` and confirm university coverage rises (~64% → ~85–90%) with no
   regression elsewhere.

## 7. Acceptance criteria

- The **6 in-scope** university misses (988, 977, 1126, 937, 1328, 920) resolve to their
  expected campus values via the targeted resolution test.
- The **3 deferred** cases (1154, 716, 900) return `PARENT_ONLY` (accepted withhold).
- `docs/alias_collision_check.py` (with C7) exits 0 and is wired into CI/test.
- No previously-correct university resolution regresses; no new false-positive **writes**.
- All new behavior is covered by tests; matcher change ships only after WS1.

## 8. Build order (summary)

1. **WS1** alias hygiene — extend collision checker (C7) → migration 026 → CI guard.
2. **WS2** campus aliases — migration 027 → re-run collision checker.
3. **WS3a** confidence-ranked scan (only after WS1) + tests.
4. **WS3b** windowed token-containment (optional/robustness) + tests.
5. **WS3c** multi-message parity test.
6. **Validate** per §6; confirm §7.

## 9. Out of scope / tracked elsewhere
- Parent values / faculty→campus mapping for İskender/Şükriye/Sami (item 5, deferred — §0).
- Identity (`veli`) prompt tightening and the `yerlesti` Router-gate — see
  [docs/problem_explanations_1.md](docs/problem_explanations_1.md) and
  [DRIFT_SAVE_PLAN.md](DRIFT_SAVE_PLAN.md) §9.
- LLM label/attribute drift — [DRIFT_SAVE_PLAN.md](DRIFT_SAVE_PLAN.md).
