# Implementation Spec — Out-of-City University Matching

**Target files:** `app/layers/matching.py`, `app/layers/info_gatherer.py`, `app/db/queries.py`
**Depends on:** Migration 015 (`out_of_city_universities` table seeded)
**Do not modify:** Any migration files, `app/tagassigner/*`, `match_university()` internals

---

## Overview

When the existing Istanbul matching pipeline returns `NONE`, the system now checks whether the input matches a known Turkish university outside Istanbul. If it does, it sends the out-of-city canned response. If it does not, it asks for clarification once. A second failure escalates to FallBack.

This logic applies **only** in `awaiting_university` and `awaiting_university_clarification` states. It does **not** apply in `awaiting_campus_clarification`.

---

## 1. Dynamic Levenshtein Cutoff Update (`app/layers/matching.py`)

Extend `_get_levenshtein_cutoff()` from Fix 1 to add a third tier for longer inputs:

```python
def _get_levenshtein_cutoff(normalized: str) -> int:
    length = len(normalized)
    if length <= 3:
        return 0
    if length <= 5:
        return 1
    if length <= 7:
        return 2
    return 3
```

This function is already used in `match_university()` Tier 3 and `match_hotel_by_ngram()`. No other changes to those functions.

---

## 2. `match_out_of_city()` Function (`app/layers/matching.py`)

Add a new standalone function. Does **not** touch `match_university()`.

```python
def match_out_of_city(
    raw_text: str,
    out_of_city_unis: list[OutOfCityUniversity],
) -> Optional[OutOfCityUniversity]:
    """
    Scan out_of_city_universities by name and short_name.
    Returns the first matching university, or None.
    Called only after match_university() returns NONE.
    """
    normalized = normalize(raw_text)
    if not normalized:
        return None

    cutoff = _get_levenshtein_cutoff(normalized)

    # Exact match on name first
    for uni in out_of_city_unis:
        if normalize(uni.name) == normalized:
            return uni
        if uni.short_name and normalize(uni.short_name) == normalized:
            return uni

    # Levenshtein on name
    if cutoff > 0:
        hits: list[tuple[int, OutOfCityUniversity]] = []
        for uni in out_of_city_unis:
            dist = levenshtein_distance(normalized, normalize(uni.name))
            if dist <= cutoff:
                hits.append((dist, uni))
            if uni.short_name:
                dist_short = levenshtein_distance(normalized, normalize(uni.short_name))
                if dist_short <= cutoff:
                    hits.append((dist_short, uni))

        if hits:
            # Return closest match; if tie, any hit suffices —
            # all are out-of-city regardless of which specific university
            hits.sort(key=lambda x: x[0])
            return hits[0][1]

    return None
```

`OutOfCityUniversity` is a new Pydantic model in `app/db/models.py`:

```python
class OutOfCityUniversity(BaseModel):
    id: uuid.UUID
    name: str
    short_name: Optional[str]
    city: str
```

---

## 3. `get_all_out_of_city_universities()` Query (`app/db/queries.py`)

Add a query following the existing pattern of `get_all_universities()`:

```python
async def get_all_out_of_city_universities() -> list[OutOfCityUniversity]:
    rows = await pool.fetch("SELECT id, name, short_name, city FROM out_of_city_universities")
    return [OutOfCityUniversity(**dict(r)) for r in rows]
```

---

## 4. `_handle_awaiting_university()` Update (`app/layers/info_gatherer.py`)

Current behavior on NONE: calls `_handle_university_no_match()`.
New behavior: before calling `_handle_university_no_match()`, run out-of-city scan.

```python
async def _handle_awaiting_university(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    result = match_university(content, all_unis, all_aliases)

    if result.confidence == MatchConfidence.NONE:
        # Try out-of-city before clarification
        all_ooc = await queries.get_all_out_of_city_universities()
        ooc_match = match_out_of_city(content, all_ooc)
        if ooc_match:
            await _fire_out_of_city(conversation, cwid)
            return
        await _handle_university_no_match(conversation, cwid, content)
        return

    await _route_university_match(conversation, cwid, result)
```

---

## 5. `_handle_clarification()` Update (`app/layers/info_gatherer.py`)

Current behavior on second NONE: sends `CANNED_ISTANBUL` (out-of-city response).
New behavior: run Istanbul match first, then out-of-city scan, then FallBack.

```python
async def _handle_clarification(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    result = match_university(content, all_unis, all_aliases)

    if result.confidence not in (MatchConfidence.NONE, MatchConfidence.AMBIGUOUS):
        if result.parent_university_id:
            await _handle_parent_match(conversation, cwid, result.parent_university_id)
            return
        if result.university_id:
            await _handle_post_match(conversation, cwid, result.university_id)
            return

    # Istanbul match failed — try out-of-city
    all_ooc = await queries.get_all_out_of_city_universities()
    ooc_match = match_out_of_city(content, all_ooc)
    if ooc_match:
        await _fire_out_of_city(conversation, cwid)
        return

    # Both failed — FallBack stub
    await _escalate_human_needed(
        cid,
        f"University clarification reply '{content[:80]}' matched neither Istanbul nor out-of-city — FallBack stub",
    )
```

---

## 6. `_fire_out_of_city()` Helper (`app/layers/info_gatherer.py`)

Extracted helper to avoid duplication across the two call sites above:

```python
async def _fire_out_of_city(conversation: Conversation, cwid: int) -> None:
    cid = conversation.id
    advanced = await queries.update_conversation_state(
        cid, "completed", conversation.flow_state
    )
    if not advanced:
        return
    await _send_canned(cwid, CANNED_ISTANBUL)
```

---

## 7. What Must NOT Change

- `match_university()` internals — no modifications
- `_handle_university_no_match()` — no modifications; still handles clarification prompt and state transition to `awaiting_university_clarification`
- `awaiting_campus_clarification` handler — out-of-city scan is never called here
- Existing `CANNED_ISTANBUL` short code — reused as-is
- TagAssigner modules — untouched

---

## 8. Testing Checklist

After implementation, test the following scenarios with teardown between each:

| Scenario | Input | Expected |
|---|---|---|
| Clear out-of-city name | `Hacettepe Üniversitesi` | Out-of-city canned response, `completed` |
| Out-of-city short name | `ODTÜ` | Out-of-city canned response, `completed` |
| Typo on out-of-city name | `Hasettepe Universitesi` | Out-of-city canned response (Levenshtein) |
| Completely unknown input | `qwerty üniversitesi` | Clarification prompt sent |
| Unknown → Istanbul on retry | `qwerty` then `boğaziçi` | Normal flow continues |
| Unknown → out-of-city on retry | `qwerty` then `Hacettepe` | Out-of-city canned response |
| Unknown → unknown on retry | `qwerty` then `asdfgh` | `human_needed`, no outbound message |
| Short name ≤3 chars, no match | `XYZ` | Clarification prompt (cutoff=0, no Levenshtein) |
