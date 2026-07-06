# Implementation Spec — Deal-Awaiting via RecEngine

**Supersedes:** pre-gender `deal_awaiting` branch in `docs/v0-amendment-deal-awaiting.md`  
**Depends on:** Migration 016, spec 016 (out-of-city matching)  
**Target files:** `app/layers/rec_engine.py`, `app/webhooks/internal.py`, `app/layers/info_gatherer.py`, `app/db/queries.py`

---

## Overview

After a successful Istanbul university match, every lead proceeds to gender capture and RecEngine. On `NOT_FOUND`, RecEngine selects one of two sentinel hotels; the callback sends wired canned copy and optionally writes the `deal_awaiting` Chatwoot label.

Out-of-city and no-match flows are unchanged (spec 016).

---

## What `deal_awaiting_universities` means

The membership table is an **ops list of Istanbul schools you plan to serve** — deals in progress, inventory expected in the coming weeks/months. It is **not** a list of schools you will never serve.

| List membership | Business meaning | RecEngine NULL outcome |
|-----------------|------------------|------------------------|
| **On list** | We intend to serve this school this year; deal not live yet | Pending-deal message + **`deal_awaiting` Chatwoot label** |
| **Not on list** | No active deal / not pursuing (gender gap, one-off NULL, etc.) | Same pending-deal message, **no label** |

**Important:** List membership affects **labeling only**, not routing before RecEngine and not the user-facing message (both NULL paths send the same canned copy). **`FOUND` always wins** — if inventory exists (e.g. deal closed), the lead gets a real recommendation even when the school is still on the list until ops removes it.

### Examples

| Lead | On list? | RecEngine | Label |
|------|----------|-----------|-------|
| Cerrahpaşa, deal expected in ~2 months | Yes | NULL | Yes |
| Yeditepe male (no male dorm) | No | NULL | No |
| Yeditepe female (dorm exists) | Yes or No | FOUND | No |
| School you are not pursuing this year | No | NULL | No |

---

## Flow

```
Istanbul match → awaiting_gender → RecEngine
  FOUND                              → real hotel response_schemas
  NOT FOUND + on deal_awaiting list  → …0003 + deal_awaiting label
  NOT FOUND + not on list            → …0002, no label
  NOT FOUND + missing sentinel       → …0001 henuz (fallback)
```

---

## Sentinels

| Hotel name | UUID | When | User message | Chatwoot label |
|------------|------|------|--------------|----------------|
| `DEAL-AWAITING-STATE` | `…0002` | Istanbul NULL, **not** on list | Pending-deal canned | — |
| `DEAL-AWAITING-LABEL-STATE` | `…0003` | Istanbul NULL, **on** list | Same canned | `deal_awaiting` |
| `GLOBAL-NULL-STATE` | `…0001` | Callback fallback only | `henuz` | — |

Both `…0002` and `…0003` wire to canned response `27ac4381-1c05-4dd6-adc5-2449c8cef639` at `sending_order = 0`.

---

## RecEngine (`app/layers/rec_engine.py`)

On empty candidates (including stale-hotel rerun):

```python
if await queries.is_deal_awaiting_university(university_id):
    return RecResult(NOT_FOUND, hotel_id=DEAL_AWAITING_LABEL_STATE_ID)
return RecResult(NOT_FOUND, hotel_id=DEAL_AWAITING_STATE_ID)
```

Pass `result.hotel_id` to callback on `NOT_FOUND` (do not null it out).

---

## Callback (`app/webhooks/internal.py`)

1. Use `body.hotel_rec` when present; else fallback `GLOBAL_NULL_STATE_ID`.
2. After `_send_hotel_responses`, if `hotel_id == DEAL_AWAITING_LABEL_STATE_ID` → `_write_deal_awaiting_label`.

---

## InfoGatherer

No pre-gender `deal_awaiting_universities` check in `_handle_post_match`. Always proceed to `awaiting_gender`. The `deal_awaiting` label is written **only** in the RecEngine callback when the sentinel is `…0003`.

---

## List hygiene (ops)

- **Add** a university when you start pursuing a deal and want Chatwoot leads tagged `deal_awaiting` while inventory is not live yet.
- **Remove** when the deal is live and RecEngine consistently returns `FOUND` for that school (or when you stop pursuing the deal).
- **Do not** add schools you will not serve this year — those stay off the list; NULL leads get the message but no label.
- Empty list is valid — all NULL outcomes use `…0002` with no label.

---

## Manual test scenarios

1. Istanbul uni, **on** list, NULL → same pending-deal message + `deal_awaiting` label  
2. Istanbul uni, **not** on list, NULL → same message, no label  
3. On list but FOUND (e.g. deal went live) → real rec, no label  
4. Out-of-city → no RecEngine (016)
