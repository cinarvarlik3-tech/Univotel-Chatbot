# Spec 031 — InfoGatherer live-test readiness

Status: proposed
Date: 2026-07-22
Scope: InfoGatherer + inbound webhook only. TagAssigner behavior is unchanged except
where a shared helper's signature changes.

## 1. Purpose

Two independent defects make live testing meaningless in the current build:

1. The Chatwoot automation message is misread as human takeover, which kills the bot
   on every conversation the automation fires in, and silently drops the lead's
   triggering message.
2. InfoGatherer has no idea whether a conversation is new or already in progress. It
   restarts its scripted flow from the top on any conversation it sees for the first
   time, including ones a human has been handling for days.

This spec covers the minimum change set to make live testing produce trustworthy data.

## 2. Findings

### F1 — The automation is classified as human takeover (blocker)

[`app/webhooks/chatwoot.py:501`](../app/webhooks/chatwoot.py#L501) treats any outbound
message whose `sender.id` != `CHATWOOT_BOT_AGENT_ID` as an agent takeover. A Chatwoot
automation-sent message does not carry the bot agent's sender id, so it takes that
branch and produces three effects:

| Effect | Call | Consequence |
| --- | --- | --- |
| Conversation marked terminal | `set_conversation_stopped` | `flow_state='stopped'`, which returns early in [`process_message`](../app/layers/info_gatherer.py#L699). InfoGatherer is dead for the rest of the conversation. |
| Buffered inbound discarded | `_cancel_debounce` | The lead's triggering message is **only** in the in-memory debounce buffer at this point. Cancelling drops it: never persisted, never processed, invisible to TagAssigner. |
| Bot disabled | `set_conversation_bot_enabled(False)` | `conversation_has_messages` is False at T+0.5 (the lead's fragment is still buffered), so the outbound-first guard also fires. |

Timeline for a conversation where the automation triggers:

```
T+0.0  lead message      → _enqueue_debounced_inbound → buffered, 3s timer, NOT persisted
T+0.5  automation fires  → synchronous outbound path  → stopped + debounce cancelled + bot_enabled=false
T+3.0  flush             → never runs; fragments discarded
T+8    lead answers      → process_message returns immediately (state='stopped')
```

### F2 — `_cancel_debounce` drops unpersisted fragments generally

F1's second effect is not automation-specific. Any agent outbound landing inside the
debounce window discards the lead's in-flight message. This is a pre-existing latent
bug; it is in scope here only because the fix is the same code path.

### F3 — First-seen conversations always restart the flow

[`upsert_conversation`](../app/db/queries.py#L71) creates a row with `flow_state='new'`
and never consults Chatwoot history. [`is_first_inbound_message`](../app/db/queries.py#L229)
computes `MIN(chatwoot_message_id)` over **our** `messages` table, which contains only
the message we just inserted, so it returns `True` for any conversation we have not
seen before. The phrase gate then treats a mid-negotiation message as an opening
message and [`_activate_flow`](../app/layers/info_gatherer.py#L337) sends `hangi`.

### F4 — Backfill cannot distinguish "no history" from "fetch failed"

[`backfill_conversation_messages`](../app/tagassigner/context_backfill.py#L77) returns
`0` both when Chatwoot has no prior messages and when the fetch fails. Reusing it as
the abstention discriminator would fail open: a Chatwoot timeout would read as "fresh
lead, start the script" on a live negotiation.

## 3. Design decisions (settled)

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | Recognize the automation by **text match only**, no sender identity | The automation is slated for removal once the bot proves out; a sender allowlist is throwaway work. |
| D2 | A single module-level constant, **no mapping table** | Exactly one automation exists. |
| D3 | InfoGatherer **suppresses its own `hangi`** when the automation already asked, and sends it normally when the automation did not fire | The automation is exact-match triggered and fails on a single-character mismatch. InfoGatherer covers the gap. |
| D4 | Abstention and escalation must occupy **separate buckets** | Otherwise "bot escalated" and "bot never had a chance" are indistinguishable in accuracy analysis. |
| D5 | Backfill fails **closed** | A missed lead is human-recoverable; a bot barging into a live negotiation is not. |
| D6 | Abstained conversations still count toward `LIVE_TESTING_LIMIT` | Accepted: a smaller effective test group is fine for this round. |

## 4. Database changes

### Migration `030_infogatherer_live_test_readiness.sql`

```sql
-- Explicit first-sight marker. Order-independent: the automation's outbound can
-- create the conversation row before the lead's debounced inbound flushes, so
-- "row was just inserted" is not a usable signal.
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS history_backfilled_at timestamptz;

-- Separates "InfoGatherer declined to run" from "InfoGatherer escalated" (D4).
-- NULL = InfoGatherer was free to run.
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS infogatherer_abstain_reason text
        CHECK (infogatherer_abstain_reason IN (
            'prior_history',
            'backfill_failed',
            'outbound_first'
        ));

-- Optional (D4 of §3 in spec review, low priority): distinguish automation-authored
-- outbound from human-agent outbound in the transcript.
ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS messages_sender_type_check;
ALTER TABLE messages
    ADD CONSTRAINT messages_sender_type_check
        CHECK (sender_type IN ('user','contact','infoGatherer','fallBack','automation'));
```

`Conversation` in [`app/db/models.py`](../app/db/models.py) gains
`history_backfilled_at: Optional[datetime] = None` and
`infogatherer_abstain_reason: Optional[str] = None`.

## 5. Code changes

### C1 — Automation recognition (new module)

New file `app/layers/automation_gate.py`.

```python
_AUTOMATION_CORE = normalize("hangi üniversite ve hangi kampüsteydeniz")

def is_automation_message(content: str | None) -> bool:
    """True when an outbound message is the Chatwoot university/campus automation."""
```

Match on **normalized substring containment of a distinctive core fragment**, not on
the full string. Reasons:

- [`normalize`](../app/layers/matching.py#L66) folds case, Turkish diacritics, and
  punctuation, so `univotel.com'u` versus `univotel.com'u` (straight versus curly
  apostrophe) stops mattering — but only if the apostrophe is not inside the fragment
  being compared. The chosen core fragment sits entirely before it.
- Full-string Levenshtein ≤2 is a very tight budget on a ~110-character message and
  would break on any Chatwoot-side whitespace or entity rendering difference.
- The fragment is distinctive enough that a human agent will not produce it by hand.

Full automation text for reference:

```
Size daha iyi yardımcı olabilmem için hangi üniversite ve hangi kampüsteydeniz
efendim? O sırada univotel.com'u incelemiş miydiniz?
```

Because of D1 there is no sender check: if the automation copy is edited in Chatwoot
without updating this constant, the message reverts to being read as human takeover
(F1). That is the accepted failure mode. Add a comment in the module saying so.

### C2 — Webhook outbound branch

In [`app/webhooks/chatwoot.py`](../app/webhooks/chatwoot.py#L501), before the
`is_bot` takeover logic:

```
if our_message_type == "outbound" and is_automation_message(content):
    → persist with sender_type='automation' (or 'user' if the enum change is skipped)
    → do NOT call set_conversation_stopped
    → do NOT call _cancel_debounce
    → do NOT call set_conversation_bot_enabled(False)
    → return 200
```

The lead's buffered fragments then flush normally at T+3 and InfoGatherer runs.

**F2 fix, same branch:** when a genuine human takeover is detected, flush the debounce
buffer before cancelling it, so the lead's in-flight message is persisted rather than
discarded. It must be persisted without being processed — the conversation is stopped.
Split `_flush_debounce` into "persist fragments" and "run the turn", and call only the
former on takeover.

### C3 — Backfill on first sight

In [`_process_inbound`](../app/webhooks/chatwoot.py#L616), after the fragment inserts
and before `process_message`:

1. Skip entirely if `conversation.history_backfilled_at is not None`.
2. Call `backfill_conversation_messages(conversation.id, chatwoot_conversation_id)`.
3. Set `history_backfilled_at = now()`.
4. Decide:
   - `ok and inserted == 0` → no prior history → proceed to `process_message`.
   - `ok and inserted > 0` → prior history → abstain:
     `bot_enabled=False`, `infogatherer_abstain_reason='prior_history'`, log at info
     with `internal_class='abstain_prior_history'`, skip `process_message`.
   - `not ok` → abstain: `infogatherer_abstain_reason='backfill_failed'`,
     `internal_class='abstain_backfill_failed'`, log at **error**, skip `process_message`.

Ordering is what makes `inserted` a correct discriminator. At the point of the call,
`messages` already holds this burst's fragments and any automation outbound from C2,
so `message_exists` skips them and `inserted` counts only genuinely prior messages.

Note that `history_backfilled_at` is set even on the abstain paths, so a conversation
is never re-fetched. On the `backfill_failed` path this means the abstention is
permanent for that conversation — acceptable under D5, but it is why the log is at
error level.

**F3 resolves for free.** Because the backfill persists what it fetched,
`is_first_inbound_message` now computes `MIN` over the true Chatwoot history. No
change to that query or to the phrase gate is required.

### C4 — Fail-closed backfill signature

[`backfill_conversation_messages`](../app/tagassigner/context_backfill.py#L77)
currently returns `int`, with `0` on fetch failure. Change to:

```python
@dataclass(frozen=True)
class BackfillResult:
    ok: bool          # False = Chatwoot fetch failed
    inserted: int
```

Update the one existing caller, [`app/tagassigner/router.py:114`](../app/tagassigner/router.py#L114),
to read `.inserted` and ignore `.ok`, preserving TagAssigner's current
"never blocks a run" behavior. Update `tests/test_context_backfill.py` (4 assertions)
and `tests/test_router_context.py` (2 mock return values).

### C5 — `hangi` suppression (D3)

In [`_activate_flow`](../app/layers/info_gatherer.py#L337), `flow_state == "new"` branch:
before sending `CANNED_HANGI`, check whether this conversation already contains an
outbound message matching `is_automation_message`. If so, advance state to
`awaiting_university` **without** sending.

This is observation-based rather than predictive — it checks whether the automation
actually fired, instead of trying to replicate Chatwoot's trigger matching. That
satisfies D3 in both directions: automation fired → suppress; automation failed on a
one-character mismatch → no automation message exists → InfoGatherer sends `hangi`.

Needs a new query:

```python
async def has_automation_outbound(conversation_id: uuid.UUID) -> bool
```

Implement as a content match in SQL against the same core fragment, or fetch recent
outbound rows and run `is_automation_message` in Python. The Python route keeps one
definition of the match and is preferred.

The same suppression applies on the backfill path: a conversation whose history
contains only the automation message (no other prior traffic) has `inserted == 1` and
would abstain under C3. That is correct only if the automation message is the
conversation's opener. See R2.

## 6. Known residual risks

**R1 — Slow-automation race.** C5 observes state at flush time (T+3). If the
automation fires later than that, InfoGatherer has already sent `hangi` and the lead
receives both questions. Expected to be rare given a 3s debounce against an
event-triggered automation. Not mitigated. If it shows up in testing, the fix is a
short grace window before the `hangi` send, defaulted to 0.

**R2 — Automation-only history.** A conversation created before the bot went live
whose sole prior message is the automation will abstain via `prior_history`, even
though InfoGatherer could legitimately resume at `awaiting_university`. Whether to
special-case `inserted == 1 and the single message is the automation` → resume rather
than abstain is a judgment call; this spec abstains, because such a conversation also
has a lead message that preceded the automation, which means `inserted >= 2` in
practice. Verify against real data before adding the special case.

**R3 — Automation copy drift.** Per D1, editing the automation text in Chatwoot
without updating `_AUTOMATION_CORE` silently reverts to F1 behavior.

**R4 — The compound question.** The automation asks three things (university, campus,
and whether the lead browsed univotel.com). A lead who answers only the website half
("evet baktım") lands at `awaiting_university`, whose fallback is
`escalate_off_script`, and will be escalated to `human_needed`. Expect some false
escalations in the results; they are an artifact of the automation's phrasing, not an
InfoGatherer defect. The campus half is a net positive — `match_campus` in the
deterministic extraction already handles "İTÜ Ayazağa".

## 7. Test plan

Unit:
- `is_automation_message` — exact text, curly versus straight apostrophe, leading and
  trailing whitespace, a human message containing "hangi üniversite" alone (must not
  match), empty and None input.
- C3 decision matrix — `(ok=True, inserted=0)`, `(ok=True, inserted>0)`, `(ok=False)`.
- C5 — automation present → no send, state advances; absent → `hangi` sent.

Integration (webhook-level, via `scripts/replay_chatwoot_webhooks.py`):
- Automation arrives mid-debounce → conversation NOT stopped, fragments survive,
  InfoGatherer runs, no duplicate `hangi`.
- Human agent outbound arrives mid-debounce → conversation stopped, fragments
  persisted but not processed (F2).
- First-sight conversation with prior Chatwoot history → abstains, `bot_enabled=false`,
  reason `prior_history`, TagAssigner still able to run on it.
- First-sight conversation with no history → runs from `new`.
- Chatwoot fetch failure → abstains with reason `backfill_failed`, error logged.

Regression:
- `bot_enabled` is read only by InfoGatherer ([`info_gatherer.py:703`](../app/layers/info_gatherer.py#L703)),
  so confirm TagAssigner still processes abstained conversations.

## 8. Pre-flight (manual, before code)

1. **Capture one real `message_created` payload for an automation-sent message.**
   Even though D1 drops the sender check, confirm the payload's `message_type` is 1
   (outgoing) and not 3 (template) — [`_map_message_type`](../app/tagassigner/context_backfill.py#L50)
   maps both to outbound, but the webhook's `mtype_raw` branch only recognizes
   `(1, "outgoing", "outbound")` and would fall through to `inbound` for type 3,
   which would break every assumption in this spec.
2. **Confirm the exact automation copy** character-for-character from the Chatwoot
   automation config, not from memory.
3. **Confirm `CHATWOOT_BOT_AGENT_ID=9`** is still the ChatBot agent.
4. **Confirm no other automations are active** on the account (D2 assumes exactly one).

## 9. Environment

No new variables. Current `.env` is already correct for this round:

```
TESTING_LIMITATIONS_MODE=false
LIVE_TESTING_MODE=true
LIVE_TESTING_LIMIT=100
OUTBOUND_BLOCK=false
TAGASSIGNER_AUTO_RUNS=false
```

`DEBOUNCE_WINDOW_SECONDS` is unset and defaults to 3
([`app/config.py:60`](../app/config.py#L60)); C3 and C5 assume a non-zero window.

Runbook order: apply migration → `tag sweepclean --confirm` → start uvicorn → start
ngrok → point the Chatwoot webhook at the ngrok URL.
