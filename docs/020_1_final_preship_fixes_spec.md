# Spec 020.1 — Divergence Recovery: Final Pre-Ship Fixes

**Status:** Build-ready. Hand to Claude Code (Cursor). Amends Spec 020. **This is the last change set before launch** — scope is frozen to four items. Do not add anything not listed here.

**Origin:** Suite D-FIX live results. Every failed/partial case maps to one of these fixes:
- A4, B3, C1, E1 (double-message half) → **Fix 1** (invert the no-match gate)
- A2 (comma) → **Fix 2** (punctuation in `normalize`)
- İTÜ "Ayazağa" → **Fix 3** (alias row)
- D2, D7 → **not fixed**; documented in README for post-launch (Fix 4 / README)

**Out of scope (explicitly cut — do not implement):** hotel aliases / partial hotel-name matching, campus alias sweep, invisible-hotel data questions, any "consider later" item from prior specs. Whole-name hotel matching is kept as-is (verified working).

---

## Root cause (one defect drives four failures)

`_run_deterministic_extraction` in `app/layers/info_gatherer.py` still runs the **old** `classify_university_reply()` gate on the `awaiting_university` no-match path, plus a redundant unguarded `is_near_miss_university()`. Two mechanisms swallow divergence messages before the classifier is reached:

1. `classify_university_reply`'s `word_count ≤ 2 → ANSWER_ATTEMPT` rule catches short divergence messages ("konum neresi", C1) → clarify.
2. The redundant `or is_near_miss_university(...)` re-runs a wide fuzzy check (cutoff+2, up to distance 5) against ~150 university names *outside* the off-script guard, so even correctly-flagged off-script messages ("fiyat ne", A4/B3) match something → clarify.

B2 passing (a long `complex` message routed correctly to divergence-escalate) proves the divergence pipeline itself works — it is only being pre-empted for short/question inputs. Fix 1 removes the pre-emption.

---

# FIX 1 — Invert the no-match flow (classifier-first; near-miss demoted to fallback)

**Decisions locked:** invert (not patch); LLM never names a university (option A — it returns intent-or-"not an inquiry", deterministic `is_near_miss_university` owns typo detection against the real DB); applies to `awaiting_university` **and** `awaiting_university_clarification`.

## 1.1 Remove the old gate from `_run_deterministic_extraction`

In `app/layers/info_gatherer.py`, inside `_run_deterministic_extraction`, the current no-match block is:

```python
if not entity_filled and result.confidence == MatchConfidence.NONE:
    if flow_state in ("new", "awaiting_university", "awaiting_university_clarification"):
        if match_out_of_city(content, all_ooc):
            await _fire_out_of_city(conv, cwid)
            await queries.reset_divergence_persistence(cid)
            return "progress"

    if flow_state == "awaiting_university":
        assessment = classify_university_reply(content, all_unis)
        if (
            assessment == AnswerAssessment.ANSWER_ATTEMPT
            or is_near_miss_university(content, all_unis)
        ):
            await _handle_university_no_match(conv, cwid, content)
            return "clarify"

    return "none"
```

**Replace with** (delete the entire `if flow_state == "awaiting_university":` classifier block; keep out-of-city; everything non-matched falls to divergence):

```python
if not entity_filled and result.confidence == MatchConfidence.NONE:
    if flow_state in ("new", "awaiting_university", "awaiting_university_clarification"):
        if match_out_of_city(content, all_ooc):
            await _fire_out_of_city(conv, cwid)
            await queries.reset_divergence_persistence(cid)
            return "progress"

    # No deterministic match. Everything (short, question-shaped, typo'd) goes to
    # divergence. Near-miss typo detection re-enters as a fallback inside
    # _run_divergence_recovery (Fix 1.2), never here.
    return "none"
```

**Also remove** the now-unused imports/usages in this file: `classify_university_reply`, `AnswerAssessment` (from `app.layers.answer_classifier`) are no longer called by `_run_deterministic_extraction`. Leave `answer_classifier.py` itself in the tree (it may be referenced by tests / other paths) but confirm no remaining production caller. `is_near_miss_university` stays imported — it is used by Fix 1.2.

## 1.2 Add near-miss fallback inside `_run_divergence_recovery`

The LLM only ever returns an intent. When that intent is `no_intent` or `complex` (i.e. "not a real inquiry") **and** the pending slot is university, a genuine typo'd university name ("Marmaraa", "Bogazçi") must still reach clarification instead of being ignored/escalated. Deterministic `is_near_miss_university` (checked against the real `universities` list) makes that call — the LLM never names a school.

In `_run_divergence_recovery`, currently:

```python
    intent = classification.intent
    if conversation.last_divergence_intent == intent.value:
        repeat_count = conversation.divergence_repeat_count + 1
    else:
        repeat_count = 1
    await queries.update_divergence_persistence(cid, intent.value, repeat_count)
```

**Insert the near-miss fallback BEFORE the persistence-counter update** (so a typo'd-uni turn is treated as a university attempt, not a divergence, and does not touch the divergence counter):

```python
    intent = classification.intent

    # Near-miss fallback (Fix 1.2): LLM found no real inquiry, but the message
    # looks like a typo'd university name and the pending slot is university.
    # Deterministic, DB-grounded; the LLM never names a university.
    if (
        intent in (Intent.NO_INTENT, Intent.COMPLEX)
        and flow_state in ("awaiting_university", "awaiting_university_clarification")
    ):
        all_unis = await queries.get_all_universities()
        if is_near_miss_university(content, all_unis):
            await _handle_university_no_match(conversation, cwid, content)
            return

    if conversation.last_divergence_intent == intent.value:
        repeat_count = conversation.divergence_repeat_count + 1
    else:
        repeat_count = 1
    await queries.update_divergence_persistence(cid, intent.value, repeat_count)
```

Add `Intent` to the imports in `info_gatherer.py` (from `app.layers.divergence_classifier`, alongside the existing `classify` import — move it to a module-level import if cleaner).

## 1.3 Escalation authority in the clarification state (locked decision #3)

`_handle_university_no_match` already encodes the one-clarification-round rule via `clarification_attempt`:
- First call (attempt 0): send `clarify_uni_name`, increment, advance to `awaiting_university_clarification`.
- Second call (attempt ≥ 1): `_escalate_human_needed`.

This is the **single escalation authority for university-typo attempts**, in both states. The divergence **persistence counter** (3× same intent → escalate) is the escalation authority for genuine divergence intents (e.g. price asked repeatedly). These never stack on the same message: a near-miss turn routes to `_handle_university_no_match` (uses `clarification_attempt`) and returns before the persistence counter is touched (Fix 1.2 ordering guarantees this); a divergence-intent turn routes through the persistence path and never calls `_handle_university_no_match`. No special-casing needed — the ordering in 1.2 enforces the separation. **Do not** add a second escalation branch in the clarification state.

## 1.4 Behavior after Fix 1 (maps to failed tests)

- **C1** `konum neresi` (awaiting_university): no match → divergence → LLM `location` → `answer_and_reanchor` (district-neutral canned). No clarify.
- **A4** `fiyat ne` → `fiyat söyle` → `konum neresi` → `ödeme nasıl` (awaiting_university): each → divergence → distinct intent → answered. No escalate; state stable.
- **B3** `fiyat ne` ×3 (awaiting_university): each → divergence → `price`; persistence 1→primary, 2→alt, 3→escalate **with `human_needed` label** (via `_escalate_human_needed`).
- **E1 (double-message half):** coalesced burst no longer produces a stray university-clarification message; resolves to a single turn (see also debounce, unchanged).
- **Typo preserved:** `Marmaraa` (awaiting_university) → no match → divergence → LLM `no_intent`/`complex` → `is_near_miss_university` True → `_handle_university_no_match` → clarify. Genuine typos still reach clarification.

---

# FIX 2 — Strip punctuation in `normalize()`

**Decision locked:** replace punctuation with a space (not delete); `normalize()` only.

## 2.1 The change

In `app/layers/matching.py`, `normalize()` is currently:

```python
def normalize(text: str) -> str:
    """Lowercase, strip Turkish diacritics, strip university suffixes, trim."""
    text = text.replace("İ", "i").replace("I", "ı")
    text = text.lower().translate(_DIACRITIC_MAP).strip()
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text
```

**Replace with** (punctuation → space, then collapse whitespace, BEFORE suffix stripping):

```python
def normalize(text: str) -> str:
    """Lowercase, strip Turkish diacritics, strip punctuation, strip university suffixes, trim."""
    text = text.replace("İ", "i").replace("I", "ı")
    text = text.lower().translate(_DIACRITIC_MAP)
    # Punctuation → space so tokens like "itu," don't diverge from "itu".
    # Diacritics are already folded to ASCII above, so \w keeps letters/digits.
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text
```

`re` is already imported at the top of `matching.py`. No new import.

## 2.2 Why this is safe and what it fixes

- Fixes **A2**: `normalize("İTÜ,")` → `"itu"` (was `"itu,"`), so the İTÜ parent-alias exact match fires whether or not a comma follows. `tokenize("İTÜ, kız")` → `["itu", "kiz"]`.
- Ripples correctly through every consumer of `normalize` (university match, `match_campus`, hotel match, phrase-gate widget Levenshtein) — all get cleaner tokens.
- Improves suffix stripping as a side effect: `"istanbul üniversitesi."` now strips to `"istanbul"`.

## 2.3 Mandatory pre-apply audit (Fix 2 blast radius)

`normalize()` runs on **every message and every matcher**. Before finalizing, Cursor must:
1. Grep for any exact-equality comparison against `normalize(...)` output that could depend on punctuation surviving. Expected: none (all matchers compare normalized-both-sides). Confirm.
2. Run the full `tests/test_matching.py` suite — all existing cases must pass unchanged (none exercise punctuation, so none should break).
3. Confirm phrase-gate widget-template matching still passes its tests (widget Levenshtein uses `normalize` on both sides).
4. Add one new test: `test_normalize_strips_punctuation` asserting `normalize("İTÜ,") == "itu"` and `normalize("a.b,c") == "a b c"`.

---

# FIX 3 — İTÜ "Ayazağa" alias

**Decision locked:** single alias, `"ayazağa"`, for İTÜ's Maslak campus `university_id = a17cc4c1-12b8-4762-9731-64ba9235d0de` (verified via Supabase MCP: the campus is a `universities` row mapped under İTÜ in `university_parent_map`; "Maslak" resolves by name-substring, so this alias is the sole route for "Ayazağa").

## 3.1 Migration `migrations/018c_itu_ayazaga_alias.sql`

Constraint-agnostic INSERT (works whether or not a unique constraint exists on `university_aliases`):

```sql
BEGIN;

INSERT INTO university_aliases (university_id, alias)
SELECT 'a17cc4c1-12b8-4762-9731-64ba9235d0de'::uuid, 'ayazağa'
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE university_id = 'a17cc4c1-12b8-4762-9731-64ba9235d0de'::uuid
      AND alias = 'ayazağa'
);

COMMIT;
```

## 3.2 Verification (post-apply)

```sql
-- Expect exactly one row:
SELECT id, university_id, alias, parent_university_id
FROM university_aliases
WHERE alias = 'ayazağa' AND university_id = 'a17cc4c1-12b8-4762-9731-64ba9235d0de';
```

The alias resolves via `match_campus`'s scoped-alias branch during `awaiting_campus_clarification`, because `get_campuses_for_parent(İTÜ)` includes this `university_id`. (Confirmed present in `university_parent_map`.)

---

# FIX 4 / README — Document D2/D7 as post-launch

**No code change.** Add a "Known Limitations — Post-Launch" section to `README.md`. It must capture the diagnosis and the tradeoff so it is decision-ready later, not a re-investigation:

> **Phrase-gate openers with commercial intent get a plain slot question instead of an intent-flavored answer.**
> Openers that trip a phrase-gate keyword filter — Filter 6 (proximity, e.g. "yakın") or Filter 7 (price/info, 2 of {fiyat, bilgi, icin}) — resolve to `GREETING` → `activate` → a plain `hangi` (university) question. The divergence classifier never runs on them, because it only fires on phrase-gate `IGNORE`. Result: a lead opening with "fiyat bilgisi alabilir miyim" or "daha yakın şubeniz var mı" is asked "hangi üniversite?" rather than receiving a price/location-flavored acknowledgment first. This is correct, non-dropping behavior (the flow continues, the answer arrives at the recommendation) and matches what a human agent would ask — it is a warmth/polish gap, not a failure.
> **Fix (deferred):** let openers that trip the price/proximity filters carry their intent into the divergence router instead of routing straight to `activate`. Cost: the divergence classifier (an LLM call) would run on more first messages, blurring the currently-clean phrase-gate/divergence separation on the hottest path. Deferred pending post-launch volume data on how often this pattern occurs.

---

## Files touched (complete list)

| File | Fix | Change |
|---|---|---|
| `app/layers/info_gatherer.py` | 1 | Remove old-gate block in `_run_deterministic_extraction`; add near-miss fallback in `_run_divergence_recovery`; adjust imports (`Intent` in, `classify_university_reply`/`AnswerAssessment` out). |
| `app/layers/matching.py` | 2 | Punctuation-strip in `normalize()`. |
| `migrations/018c_itu_ayazaga_alias.sql` | 3 | New migration, single alias INSERT. |
| `README.md` | 4 | Known-Limitations post-launch note. |
| `tests/test_matching.py` | 2 | Add `test_normalize_strips_punctuation`. |
| `tests/test_info_gatherer_handlers.py` (or equiv) | 1 | Add: no-match short message → divergence (not clarify); near-miss typo → clarify; divergence-escalate writes label. |

## Acceptance criteria

1. `awaiting_university` short/question no-match messages ("konum neresi", "fiyat ne") route to divergence, not clarification.
2. Genuine near-miss typos ("Marmaraa") still reach clarification via the fallback.
3. Persistence 3rd-strike escalate writes the `human_needed` label.
4. `normalize("İTÜ,") == "itu"`; "İTÜ, kız" resolves identically to "İTÜ kız".
5. Full `pytest` green — **existing `test_matching.py` unchanged-and-passing is a hard gate** (Fix 2 blast radius).
6. Ayazağa alias present and resolvable during İTÜ campus clarification.
7. README carries the D2/D7 note.

## Do NOT do (scope guard)

- No hotel aliases, no partial hotel-name matching.
- No campus alias sweep beyond the single Ayazağa row.
- No changes to phrase-gate opener routing (D2/D7 is documented, not fixed).
- No new intents, no routing-table changes, no prompt changes.
- No touching working paths except as required by Fix 1/2.
