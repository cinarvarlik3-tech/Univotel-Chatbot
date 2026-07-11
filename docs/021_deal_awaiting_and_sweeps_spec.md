# Spec 021 — TagAssigner `deal_awaiting` Label + Sweep Operations

**Status:** Build-ready. Hand to Claude Code (Cursor). Independent of Spec 020.1 (divergence fixes) — can be built in parallel, but see §0 sequencing.

**Goal:** (1) Make TagAssigner a deterministic safety net that applies the `deal_awaiting` Chatwoot label when a lead's university is on the deal list but InfoGatherer's RecEngine callback never fired and no human added it. (2) Add manual sweep operations so the existing/unlabeled conversation backlog can be run through TagAssigner (which, with (1), backfills `deal_awaiting` across the backlog) for outreach.

**Governing principles (do not violate):**
- `deal_awaiting` is **Router-computed, never Gemini-assigned.** The LLM is never consulted for it. It is a deterministic DB membership check.
- It is **add-only.** Nothing in this spec ever removes `deal_awaiting`.
- Sweeps **reuse the existing queue and Router.** No new tagging pipeline, no new Chatwoot write path, no new webhook.
- Sweep triggers **extend the existing private-note `tag` handler** and add one terminal script. No new command framework.

---

## 0. Sequencing (critical)

**Part A (Router `deal_awaiting` step) must be complete before Part B (sweeps) is useful.** A sweep runs the Router; only the Router step produces the `deal_awaiting` label. If sweeps are built without Part A, they run clean and add no `deal_awaiting` labels (Gemini cannot assign it — `label_resolver` strips it). Build A first, or at least land both before validating.

Note: TagAssigner has tagged nothing in production yet, so at launch every conversation has zero successful runs — `sweep` and `sweepSafe` cover the identical population for the initial backfill. The 24h window in `sweepSafe` only becomes meaningful once runs accumulate.

---

# PART A — Router-computed `deal_awaiting` label

## A.1 New module: `app/tagassigner/deal_awaiting.py`

Mirrors the structure of `app/tagassigner/info_check.py` (Router-owned label, computed deterministically, never by Gemini).

```python
"""
Router-computed deal_awaiting label.

deal_awaiting is never assigned by Gemini (label_resolver strips any Gemini
proposal of it). It is computed deterministically from the conversation's
resolved university: membership in deal_awaiting_universities. Add-only —
never removed here.

This mirrors the RecEngine callback trigger. TagAssigner is the safety net for
conversations where InfoGatherer broke before the RecEngine callback fired and
a human did not add the label manually.
"""
from __future__ import annotations
import uuid
from typing import Optional

from app.db import queries

DEAL_AWAITING_LABEL = "deal_awaiting"


async def apply_deal_awaiting(
    university_id: Optional[uuid.UUID],
    labels: set[str],
) -> set[str]:
    """
    Add deal_awaiting to the desired label set iff the conversation's university
    is on the deal_awaiting list and the label is not already present.
    Add-only: never removes. No-op when university_id is None.
    """
    if university_id is None:
        return labels
    if DEAL_AWAITING_LABEL in labels:
        return labels  # already present — add-only, leave it
    if await queries.is_deal_awaiting_university(university_id):
        return labels | {DEAL_AWAITING_LABEL}
    return labels
```

`queries.is_deal_awaiting_university(university_id)` **already exists** in `app/db/queries.py` (one-row membership check against `deal_awaiting_universities`). Do not rewrite it.

## A.2 Wire into the Router pipeline (`app/tagassigner/router.py`)

The Router's `run_tagging` pipeline currently runs, in order:

1. Read current labels live from Chatwoot
2. Fetch messages; build Gemini payload
3. `gemini_client.call_gemini` → labels + attributes
4. `label_resolver.resolve_labels`
5. `attribute_merger.merge_attributes`
6. `info_check.apply_info_check`
7. Write labels + changed attributes to Chatwoot (`record_self_write`)
8. Reset counter; mark success

**Insert a new step 6.5, immediately after `apply_info_check` and before the Chatwoot write:**

```python
# 6.5 — Router-computed deal_awaiting (add-only; deterministic university check)
from app.tagassigner.deal_awaiting import apply_deal_awaiting
labels = await apply_deal_awaiting(conversation.university_id, labels)
```

- `conversation.university_id` is already available on the loaded conversation row — **no new query** to fetch it.
- `labels` is the working desired-label set produced by steps 4 + 6. Keep whatever type the Router already uses (set/list); if it is a list, convert to set for the union and back, matching the existing `apply_info_check` convention exactly.
- The existing step 7 writes the full desired label set to Chatwoot (Chatwoot label POST replaces the full set), so contributing `deal_awaiting` here requires no new write path.

## A.3 `label_resolver.py` — guard `deal_awaiting` as Router-owned

`deal_awaiting` must be handled exactly like `info-check` is today:

1. **Strip it from Gemini's proposal.** Wherever `resolve_labels` strips a Gemini-proposed `info-check` before applying taxonomy, add `deal_awaiting` to that strip. Gemini must never be able to assign `deal_awaiting`, regardless of what the prompt returns.
2. **Never remove it if already present.** If `deal_awaiting` is in the current/live label set (set earlier by RecEngine callback or a human), `resolve_labels` must preserve it into the output set — treat it as never-remove (same guard class as LIST 2: `kapora-alindi`, `sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak`).

Net: after `resolve_labels`, `deal_awaiting` is present iff it was already present (preserved) — never added by Gemini. Then step 6.5 adds it if the university qualifies. This is the same add-then-preserve lifecycle `info_check` uses.

## A.4 System prompt — no change

Do **not** add `deal_awaiting` to the TagAssigner Gemini system prompt. It is not an LLM label. Do not add a location list to the prompt (explicitly cut — feature bloat + hallucination risk). If the prompt currently lists `deal_awaiting` anywhere as assignable, remove it.

---

# PART B — Sweep operations

Three operations that select a population of conversations and enqueue each into the **existing** `tag_assigner_queue` via the **existing** dedupe-guarded `queries.enqueue_tagassigner_run`. The queue drain worker then runs the full Router (including step 6.5) on each. No operation writes labels directly — they only enqueue.

## B.1 New query functions in `app/db/queries.py`

All three: `ORDER BY created_at ASC` (oldest first), `LIMIT` applied **after** the filter (limit caps count, never relaxes the filter). `limit=None` means no limit.

**Testing-mode allowlist:** all three must apply the same allowlist gate the existing `get_conversations_eligible_for_tagging` uses — when `settings.testing_limitations_mode` is true, add `AND contact_phone = ANY($allowlist::text[])`. This keeps sweeps consistent with the rest of TagAssigner. (Consequence for validation: see §D.)

```python
async def get_conversations_for_sweep(limit: Optional[int] = None) -> list[Conversation]:
    """sweep: any conversation, oldest first."""
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()
    base = "SELECT * FROM conversations c"
    where = ""
    params: list = []
    if settings.testing_limitations_mode:
        where = " WHERE c.contact_phone = ANY($1::text[])"
        params.append(list(TESTING_PHONE_ALLOWLIST))
    sql = f"{base}{where} ORDER BY c.created_at ASC"
    if limit is not None:
        params.append(limit)
        sql += f" LIMIT ${len(params)}"
    rows = await pool.fetch(sql, *params)
    return [Conversation(**dict(r)) for r in rows]


async def get_conversations_for_sweep_empty(limit: Optional[int] = None) -> list[Conversation]:
    """sweepEmpty: conversations with NO labels at all, oldest first."""
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()
    conds = ["(c.labels IS NULL OR cardinality(c.labels) = 0)"]
    params: list = []
    if settings.testing_limitations_mode:
        params.append(list(TESTING_PHONE_ALLOWLIST))
        conds.append(f"c.contact_phone = ANY(${len(params)}::text[])")
    sql = f"SELECT * FROM conversations c WHERE {' AND '.join(conds)} ORDER BY c.created_at ASC"
    if limit is not None:
        params.append(limit)
        sql += f" LIMIT ${len(params)}"
    rows = await pool.fetch(sql, *params)
    return [Conversation(**dict(r)) for r in rows]


async def get_conversations_for_sweep_safe(limit: Optional[int] = None) -> list[Conversation]:
    """
    sweepSafe: conversations with NO successful tag_assigner_runs row whose
    completed_at is within the last 24 hours. Oldest first.
    """
    from app.config import settings, TESTING_PHONE_ALLOWLIST
    pool = get_pool()
    conds = [
        """NOT EXISTS (
            SELECT 1 FROM tag_assigner_runs r
            WHERE r.conversation_id = c.id
              AND r.status = 'success'
              AND r.completed_at > now() - interval '24 hours'
        )"""
    ]
    params: list = []
    if settings.testing_limitations_mode:
        params.append(list(TESTING_PHONE_ALLOWLIST))
        conds.append(f"c.contact_phone = ANY(${len(params)}::text[])")
    sql = f"SELECT * FROM conversations c WHERE {' AND '.join(conds)} ORDER BY c.created_at ASC"
    if limit is not None:
        params.append(limit)
        sql += f" LIMIT ${len(params)}"
    rows = await pool.fetch(sql, *params)
    return [Conversation(**dict(r)) for r in rows]
```

**Verify before writing:** the `conversations.labels` column type. If it is `text[]`, `cardinality()` is correct. If it is `jsonb`, use `(c.labels IS NULL OR jsonb_array_length(c.labels) = 0)` instead. Confirm the column type in the DB first; do not guess.

## B.2 Shared sweep executor: `app/tagassigner/sweep.py` (new)

```python
"""
Manual sweep operations: enqueue a filtered population of conversations for
TagAssigner processing. Enqueue only — the existing queue drain runs the Router.
"""
from __future__ import annotations
import logging
from typing import Optional

from app.db import queries

logger = logging.getLogger(__name__)

VALID_OPERATIONS = ("sweep", "sweepEmpty", "sweepSafe")
SWEEP_TRIGGER_TYPE = "sweep"


async def run_sweep(operation: str, limit: Optional[int]) -> int:
    """
    Enqueue conversations matching the operation's filter. Returns the number
    actually enqueued (dedupe-guarded — already-queued conversations are skipped).
    Operation name is matched case-insensitively by the caller; pass canonical form.
    """
    if operation == "sweep":
        convos = await queries.get_conversations_for_sweep(limit)
    elif operation == "sweepEmpty":
        convos = await queries.get_conversations_for_sweep_empty(limit)
    elif operation == "sweepSafe":
        convos = await queries.get_conversations_for_sweep_safe(limit)
    else:
        raise ValueError(f"unknown sweep operation: {operation}")

    enqueued = 0
    for c in convos:
        # enqueue_tagassigner_run returns False if already pending/processing (dedupe)
        if await queries.enqueue_tagassigner_run(c.id, trigger_type=SWEEP_TRIGGER_TYPE):
            enqueued += 1
    logger.info("sweep '%s' (limit=%s): matched=%d enqueued=%d",
                operation, limit, len(convos), enqueued)
    return enqueued
```

## B.3 Daily caps — sweeps bypass them

Sweep-triggered runs must **not** be blocked by the daily auto/manual run caps (5/day), or a `sweepSafe 20` is impossible. In the queue-drain / run path, a run with `trigger_type='sweep'` skips the `auto_run_count` / `manual_run_count` cap checks. It still goes through the queue, the ~6 RPM throttle, and all Router logic normally. (Rationale: sweeps are deliberate operator actions, terminal or chat-capped; the daily cap exists to throttle automatic tagging, not operator backfills.)

Confirm the cap check lives in the trigger/queue logic and add a `trigger_type == 'sweep'` bypass there. Do not remove the caps for other trigger types.

---

# PART C — Triggers & gating

## C.1 Chat trigger — extend the existing private-note `tag` handler

In `app/webhooks/chatwoot.py`, the `message_created` handler already treats a private note `"tag"` as a manual single-conversation trigger. Extend that parsing:

**Parse rule** (applied to the trimmed private-note content):
1. Split on whitespace into tokens.
2. Token[0] must equal `tag` (case-insensitive) or it is not a command — ignore (existing non-command behavior).
3. **If exactly one token (`tag`)** → existing single-conversation manual trigger. **Unchanged behavior.** Do not alter this path.
4. **If two or more tokens** → sweep command: `tag <operation> [N]`.
   - `operation` = token[1], matched **case-insensitively** against `sweep` / `sweepempty` / `sweepsafe`, normalized to canonical form (`sweep`, `sweepEmpty`, `sweepSafe`).
   - `N` = token[2] if present, must parse as a positive integer.

**Chat gating (all failures emit the single rejection message in C.3 as a private note, then stop):**
- `operation == sweep` → **rejected** (terminal-only). Rejection message.
- `operation not in {sweepEmpty, sweepSafe}` (unrecognized) → rejection message.
- `N` present but not a positive integer → rejection message.
- `N` present and `> 20` → rejection message.
- `N` absent → **default to 20** (the chat cap for the allowed operations).
- Otherwise (`sweepEmpty`/`sweepSafe`, `N` ∈ [1,20] or defaulted to 20) → call `run_sweep(operation, N)`, then post a private-note confirmation: `"Sweep '<operation>' enqueued <count> conversation(s)."`

**Ordering of checks matters:** check `sweep`-from-chat rejection and unrecognized-operation before numeric parsing, so `tag sweep 5` from chat yields the rejection (terminal-only), not a cap pass.

## C.2 Terminal trigger — new script `scripts/tag_sweep.py`

```python
"""
Terminal sweep entry point. Unlimited, all operations.
Usage:
    python3 scripts/tag_sweep.py sweep              # all conversations, no limit
    python3 scripts/tag_sweep.py sweepSafe 50       # 50 oldest not-successfully-run-in-24h
    python3 scripts/tag_sweep.py sweepEmpty         # all unlabeled, no limit
Operation is case-insensitive. Limit optional (omit = unlimited).
"""
import asyncio
import sys

from app.db.client import init_pool, close_pool  # match actual pool lifecycle helpers
from app.tagassigner.sweep import run_sweep, VALID_OPERATIONS

_CANON = {op.lower(): op for op in VALID_OPERATIONS}


async def _main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: tag_sweep.py <{'|'.join(VALID_OPERATIONS)}> [limit]")
        sys.exit(2)
    op_raw = sys.argv[1].lower()
    if op_raw not in _CANON:
        print(f"unknown operation '{sys.argv[1]}'. valid: {', '.join(VALID_OPERATIONS)}")
        sys.exit(2)
    operation = _CANON[op_raw]
    limit = None
    if len(sys.argv) >= 3:
        try:
            limit = int(sys.argv[2])
            if limit <= 0:
                raise ValueError
        except ValueError:
            print("limit must be a positive integer")
            sys.exit(2)
    await init_pool()
    try:
        count = await run_sweep(operation, limit)
        print(f"sweep '{operation}' (limit={limit}) enqueued {count} conversation(s).")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
```

Match `init_pool`/`close_pool` (or equivalent) to the actual pool-lifecycle functions in `app/db/client.py`. Terminal has **no cap** and allows all three operations, including bare `sweep` with no limit.

## C.3 Rejection message (verbatim — use exactly this string)

```
You may only use "tag sweepSafe [limit]" or "tag sweepEmpty [limit]" from the chat, with a maximum limit of 20. Input a numeric limit where the examples say [limit]. Standart "tag sweep" operations and other operations with limit above 20 are guarded terminal operations, contact your developer if you need them.
```

Emit as a private note on the conversation where the command was issued. One message for every chat failure case (rejected op, unrecognized op, non-numeric N, N > 20). Never fail silently.

---

# PART D — Interactions & edge cases (state so Cursor doesn't guess)

- **Dedupe:** `enqueue_tagassigner_run` returns False if the conversation already has a `pending`/`processing`/`submitted`/`awaiting_results` queue item. Sweeps rely on this — overlapping sweeps, or a sweep overlapping the nightly batch, will not double-enqueue. Do **not** insert into the queue directly; always go through `enqueue_tagassigner_run`.
- **No flow_state filter on sweeps:** a `human_needed` / `stopped` / `completed` conversation can still be a `deal_awaiting` lead (that is the whole point of the safety net). Sweeps do not filter on `flow_state`. The Router step 6.5 applies `deal_awaiting` regardless of flow_state.
- **Null `university_id`:** `apply_deal_awaiting` no-ops. The conversation still gets full Gemini tagging for its other labels; it just cannot receive `deal_awaiting` (there is no university to check). This is correct — the safety net covers "university known, label missing," not "university never determined." Do not attempt to infer a university from message text.
- **Testing-mode allowlist:** sweeps respect it (B.1). During pre-launch testing (`testing_limitations_mode=true`), a sweep only touches allowlisted phones. See §E for validation implication.
- **`deal_awaiting` label existence in Chatwoot:** the label already exists (RecEngine callback uses it). No label-creation step needed.
- **Add-only everywhere:** neither the Router step nor `label_resolver` ever removes `deal_awaiting`. A conversation that has it keeps it even if `university_id` is later cleared or changed.

---

# Files touched (complete)

| File | Part | Change |
|---|---|---|
| `app/tagassigner/deal_awaiting.py` | A | **New.** `apply_deal_awaiting`. |
| `app/tagassigner/router.py` | A | Insert step 6.5 (call `apply_deal_awaiting`) after `apply_info_check`, before Chatwoot write. |
| `app/tagassigner/label_resolver.py` | A | Strip Gemini-proposed `deal_awaiting`; preserve existing `deal_awaiting` (never-remove). |
| `system_prompts/tagassigner_prompt.md` | A | Remove `deal_awaiting` if present as assignable; add nothing. |
| `app/db/queries.py` | B | Add `get_conversations_for_sweep`, `_sweep_empty`, `_sweep_safe`. (`is_deal_awaiting_university`, `enqueue_tagassigner_run` already exist.) |
| `app/tagassigner/sweep.py` | B | **New.** `run_sweep`. |
| `app/tagassigner/trigger.py` (or queue/run path) | B | `trigger_type='sweep'` bypasses daily caps. |
| `app/webhooks/chatwoot.py` | C | Extend private-note `tag` parsing to `tag <op> [N]`; chat gating; rejection message; confirmation note. Single-token `tag` unchanged. |
| `scripts/tag_sweep.py` | C | **New.** Terminal entry, unlimited, all ops. |
| `tests/test_deal_awaiting.py` | A | New. |
| `tests/test_sweep.py` | B/C | New. |

---

# PART E — Validation (10 Chatwoot conversations)

**Prerequisite:** the 10 test conversations must be processable under whatever mode you run in. Because sweeps respect the allowlist in testing mode, either (a) run the validation with `testing_limitations_mode=false` in a staging environment against these 10 specific conversations, or (b) ensure the 10 conversations' `contact_phone` values are on `TESTING_PHONE_ALLOWLIST`. State which you used.

**Setup:** pick 10 old Chatwoot conversations covering these states (at least one of each of the first three):
- **Qualifies + label missing:** `university_id` ∈ `deal_awaiting_universities`, no `deal_awaiting` label. → after sweep, label **added**.
- **Qualifies + label present:** same university, `deal_awaiting` already applied. → after sweep, label **untouched** (no double-write; verify via Chatwoot label set unchanged and `record_self_write` not looping).
- **Does not qualify:** `university_id` not on the list (or null). → after sweep, `deal_awaiting` **not added**.
- **Other labels preserved:** any conversation with existing human labels (e.g. `whatsapp`, `1-sinif`) → those remain after the run.

**Run:** `tag sweepSafe 10` (chat) or `python3 scripts/tag_sweep.py sweepSafe 10` (terminal). Confirm the enqueue count, wait for the queue to drain, then inspect Chatwoot labels on each of the 10.

**Pass criteria:**
1. Qualifying-missing conversations gain `deal_awaiting`.
2. Qualifying-present conversations are unchanged (no duplicate, no removal).
3. Non-qualifying conversations do not gain `deal_awaiting`.
4. Pre-existing labels on all conversations are preserved.
5. `deal_awaiting` never appears on a conversation whose `university_id` is not on the list — i.e. Gemini did not assign it (confirms the `label_resolver` strip).
6. No webhook loop from the label writes (feedback-loop guard holds).

---

# Acceptance criteria (build)

1. `apply_deal_awaiting` adds the label only for list-member universities, only when absent; no-ops on null university; never removes.
2. `label_resolver` strips any Gemini-proposed `deal_awaiting` and preserves an existing one.
3. Router step 6.5 runs after `apply_info_check`, before the Chatwoot write, using `conversation.university_id` (no new fetch).
4. Three sweep queries return oldest-first, filter-correct, limit-after-filter, allowlist-gated in testing mode.
5. `run_sweep` enqueues via the dedupe-guarded path only; returns accurate enqueued count.
6. `trigger_type='sweep'` bypasses daily caps; still throttled by the queue.
7. Chat: `sweepEmpty`/`sweepSafe` ≤ 20 (bare = 20); `sweep` and any op > 20 and malformed input → verbatim rejection note; single-token `tag` unchanged.
8. Terminal: all ops, unlimited.
9. Full `pytest` green.
10. §E validation passes on 10 conversations.

# Do NOT do (scope guard)

- No `deal_awaiting` location list (in prompt or DB) — cut.
- No LLM involvement in `deal_awaiting` — deterministic only.
- No query language / arbitrary filters — only the three fixed operations with an integer limit.
- No `sweep` from chat.
- No new webhook, no new queue, no new tagging pipeline, no direct queue inserts.
- No removal of `deal_awaiting` anywhere.
- No date-argument sweeps (deferred post-launch).
