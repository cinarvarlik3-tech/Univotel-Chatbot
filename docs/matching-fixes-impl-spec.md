# Implementation Spec — Matching Fixes & Invalid Input Handling

**Target files:** `app/layers/matching.py`, `app/layers/info_gatherer.py`
**Test coverage:** F6, F8 in `docs/wa_test_links.md`
**Do not modify:** `app/db/queries.py`, any migration files, `app/tagassigner/*`

---

## Fix 1 — Dynamic Levenshtein Cutoff (`app/layers/matching.py`)

### What to change

Replace the module-level constant:

```python
LEVENSHTEIN_CUTOFF = 2
```

With a function:

```python
def _get_levenshtein_cutoff(normalized: str) -> int:
    length = len(normalized)
    if length <= 3:
        return 0
    if length <= 5:
        return 1
    return 2
```

### Where to apply it

In `match_university()`, Tier 3 loop — replace the hardcoded cutoff reference:

```python
# Before
if dist <= LEVENSHTEIN_CUTOFF:

# After
if dist <= _get_levenshtein_cutoff(normalized):
```

In `match_hotel_by_ngram()`, replace:

```python
# Before
if levenshtein_distance(normalized_candidate, normalized_name) <= LEVENSHTEIN_CUTOFF:

# After
if levenshtein_distance(normalized_candidate, normalized_name) <= _get_levenshtein_cutoff(normalized_candidate):
```

### Why

`LEVENSHTEIN_CUTOFF = 2` on short inputs produces false positives. `"TÖÜ"` normalizes to `"tou"` (3 chars) and was matching `"ku"` (Koç) at distance 2. With cutoff 0 for ≤3 chars, short inputs only pass through Tier 1 exact match and Tier 2 alias lookup — which is correct, since all valid short names (`su`, `ku`, `gsü`, `fbü`, `acu`, `prü`) are already registered as aliases or `university_short_name` entries and never reach Tier 3.

### What must NOT change

`LEVENSHTEIN_CUTOFF` can be kept as a module constant for reference or removed entirely — but it must no longer be used in any comparison. Do not change the normalize function, the tier order, or any other logic in `match_university()`.

---

## Fix 2 — Campus Alias Lookup in `awaiting_campus_clarification` (`app/layers/info_gatherer.py`)

### What to change

In `_handle_awaiting_campus_clarification()`, after the existing `campus_label` comparison loop fails to find a match, also check aliases for each campus.

Current code:

```python
normalized_reply = normalize(content)
matched = None
for campus in campuses:
    if normalize(campus.campus_label) == normalized_reply:
        matched = campus
        break
```

Replace with:

```python
all_aliases = await queries.get_all_university_aliases()

normalized_reply = normalize(content)
matched = None
for campus in campuses:
    # Primary: match against campus_label
    if normalize(campus.campus_label) == normalized_reply:
        matched = campus
        break
    # Secondary: match against aliases registered to this campus's university_id
    campus_aliases = [
        a for a in all_aliases
        if a.university_id == campus.university_id
    ]
    for alias in campus_aliases:
        if normalize(alias.alias) == normalized_reply:
            matched = campus
            break
    if matched:
        break
```

### Why

`awaiting_campus_clarification` only compared the lead's reply against `campus_label` values from `university_parent_map`. Campus aliases (e.g. `taşkışla` for İTÜ Maçka) live in `university_aliases` and were never consulted in this state. A lead typing `taşkışla` when asked which İTÜ campus would always fail to match even though the alias is correctly registered in the DB. This fix extends the lookup to include all aliases whose `university_id` matches a candidate campus.

### What must NOT change

Do not change the `clarification_attempt` increment/reset logic, the escalation path, or the `_handle_post_match` call that follows a successful match. Only the matching block is modified.

---

## Fix 3 — Double Invalid University Behavior (`app/layers/info_gatherer.py`)

### Current behavior

`_handle_university_no_match()` sends `CANNED_CLARIFY_UNI_NAME` on first failure and sends `CANNED_ISTANBUL` (out-of-city response) on second failure (when state is already `awaiting_university_clarification`).

### New behavior

On second failure: **do not send any outbound message.** Set `flow_state = human_needed` silently (existing `_escalate_human_needed()` behavior — DB write only, no Chatwoot message).

```python
async def _handle_university_no_match(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id

    if conversation.flow_state == "awaiting_university_clarification":
        # Second failure — silent escalation, no outbound message
        await _escalate_human_needed(
            cid,
            f"University clarification reply '{content[:80]}' failed twice — FallBack stub",
        )
        return

    # First failure — send clarification prompt
    await _send_canned(cwid, CANNED_CLARIFY_UNI_NAME)
    if word_count_after_normalize(content) > 2:
        await queries.update_conversation_state(
            cid, "awaiting_university_clarification", "awaiting_university"
        )
```

### Why

The previous behavior sent `CANNED_ISTANBUL` (out-of-city) on any second invalid university input. This is wrong for two reasons: the lead may have typed a real Istanbul university with a bad typo, and responding with out-of-city content is actively misleading. Silent FallBack escalation is the correct path — it keeps the bot from making false claims and routes the conversation to human handling without revealing the bot's limitations.

---

## Fix 4 — Double Invalid Campus Behavior (`app/layers/info_gatherer.py`)

### Current behavior

`_handle_awaiting_campus_clarification()` sends `CANNED_CLARIFY_CAMPUS_NAME` on first failure. On second failure (`clarification_attempt >= 1`) it calls `_escalate_human_needed()` — correct. No outbound message is sent on second failure — also correct.

### Verify this is already working

Check that the second-failure path in `_handle_awaiting_campus_clarification()` is:

```python
if conversation.clarification_attempt >= 1:
    await _escalate_human_needed(
        cid,
        f"Campus clarification reply '{content[:80]}' failed twice — FallBack stub",
    )
    return
```

And that `_escalate_human_needed()` does **not** send any outbound Chatwoot message — only writes to DB and logs. If this is already the case, no change is needed here beyond Fix 2 above.

---

## Fix 5 — National University List (Deferred — Do Not Implement Now)

A second `universities` table covering all Turkish universities (not just Istanbul) is planned. It will be used to distinguish "real university outside Istanbul" from "completely unrecognized input" in the invalid university path. Architecture and migration will be specced separately.

**No action required in this implementation pass.**

---

## Testing Checklist

After implementing Fixes 1–4, run the following F-suite cases with teardown between each:

| Test | Step | Expected result |
|---|---|---|
| F6 step 2 | `taşkışla` in `awaiting_campus_clarification` | Matches İTÜ Maçka via alias, proceeds to gender |
| F8 step 3 | `beşiktaş` (invalid campus, first attempt) | Sends `CANNED_CLARIFY_CAMPUS_NAME`, reprompts |
| F8 step 3 repeated | Second invalid campus | Silent `human_needed`, no outbound message |
| F8 TÖÜ test | `TÖÜ` as university input | No match — does not false-positive to Koç or any other university |
| F8 double invalid uni | Two consecutive invalid university inputs | First: `CANNED_CLARIFY_UNI_NAME`. Second: silent `human_needed` |

Run teardown SQL between every test:

```sql
UPDATE conversations
SET flow_state = NULL, university_id = NULL, gender = NULL,
    pending_parent_university_id = NULL, ilgili_otel = NULL,
    ilgili_otel_set_at = NULL, ilgili_otel_set_by = NULL,
    auto_run_count = 0, manual_run_count = 0,
    clarification_attempt = 0
WHERE chatwoot_conversation_id = <your_test_cw_id>;
```

Also clear Chatwoot labels and custom attributes in the UI before each fresh run.

---

## What Not to Touch

- `phrase_gate.py` — phrase gate is complete and passing all F-suite cases
- `app/db/queries.py` — no new queries needed; `get_all_university_aliases()` already exists
- `university_aliases` table — DB is correct; `taşkışla` alias is registered with the correct `university_id`
- `university_parent_map` table — `campus_label` values are correct; do not rename them
- Any TagAssigner modules
- Any migration files
