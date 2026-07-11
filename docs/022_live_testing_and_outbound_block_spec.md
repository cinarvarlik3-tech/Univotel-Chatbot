# Spec 022 — Live Testing Mode, Live Testing Limit, Outbound Block

**Status:** Build-ready. Hand to Claude Code (Cursor). Independent of Specs 020.1 / 021 — can build in parallel. This is the config layer that lets TagAssigner (Spec 021) be validated against a bounded set of real conversations without messaging leads.

**Goal:** three new env-level configs that let the bot run on live traffic, label conversations, and NOT send any message to a lead — bounded to a fixed number of conversations.

**Scope discipline:** only these three configs. The three layer on/off kill-switches (InfoGatherer/RecEngine/TagAssigner) and the `AC`/`DC`/`LTC` response-code taxonomy are **explicitly deferred** to the future settings-UI work. Do not build them. Do not build a structured internal-response-code system — use plain log lines + existing drop behavior.

---

## The three configs

| Config | Type | Default | Purpose |
|---|---|---|---|
| `LIVE_TESTING_MODE` | bool | `false` | Enables the live-testing DB ingestion cap. Mutually exclusive with `TESTING_LIMITATIONS_MODE`. |
| `LIVE_TESTING_LIMIT` | int | unset/null | Max conversations admitted to the DB while live testing is on. Required when `LIVE_TESTING_MODE=true`. |
| `OUTBOUND_BLOCK` | bool | `false` | When true, suppresses all lead-facing messages (labels/attributes/private-notes still write). Independent of the other two. |

Add all three to `app/config.py` `settings` and to `.env.example` with comments. `LIVE_TESTING_LIMIT` must be nullable (distinguish "unset" from "0").

---

## PART A — Boot-time validation (fail fast, like the integrity check)

These are validated **once at startup** in `lifespan()` (or wherever the integrity check runs), NOT per-request. A misconfiguration must refuse to start the app with a fatal log — it must scream on day one, not fail silently at request time.

**Rule 1 — mutual exclusion:**
```
if LIVE_TESTING_MODE and TESTING_LIMITATIONS_MODE:
    fatal log "LIVE_TESTING_MODE and TESTING_LIMITATIONS_MODE cannot both be enabled"
    refuse to start
```

**Rule 2 — mode requires limit:**
```
if LIVE_TESTING_MODE and LIVE_TESTING_LIMIT is None:
    fatal log "LIVE_TESTING_MODE is on but LIVE_TESTING_LIMIT is not set"
    refuse to start
```

**Non-rules (explicitly, so nothing extra is built):**
- `LIVE_TESTING_LIMIT` set while `LIVE_TESTING_MODE=false` → **no effect, no error.** The limit is simply inert.
- `OUTBOUND_BLOCK` has no interaction with the other two — no validation, valid in any combination.

Follow the existing fatal-boot-check pattern (same mechanism as `INTEGRITY_CHECK_BYPASS`/integrity check). If the app already has a startup-validation function, add these there; otherwise add a small `validate_config()` called in `lifespan()` before background tasks start.

---

## PART B — `LIVE_TESTING_LIMIT` ingestion cap

**Behavior:** when `LIVE_TESTING_MODE=true`, only the first `LIVE_TESTING_LIMIT` conversations are admitted to the DB. Once the DB holds that many, the next *new* conversation is rejected at ingestion — not processed, not stored.

### B.1 Where the gate lives

In `app/webhooks/chatwoot.py`, at the point where a **new** conversation would be created (the `upsert_conversation` path for a first-seen `chatwoot_conversation_id`). This is the same location as the existing `TESTING_LIMITATIONS_MODE` phone-allowlist gate — put the live-testing cap right alongside it.

### B.2 Exact logic

```
on inbound webhook, before creating a NEW conversation:
    if settings.live_testing_mode:
        # Only gate NEW conversations. Existing ones always pass.
        if conversation does not already exist (first-seen chatwoot_conversation_id):
            current = await queries.count_live_testing_conversations()
            if current >= settings.live_testing_limit:
                log info "LIVE_TESTING_LIMIT reached (N); rejecting new conversation <cwid>"
                return 200 (ack the webhook, do nothing)   # do NOT 4xx/5xx — Chatwoot would retry
```

- **Only new conversations are gated.** A conversation already in the DB continues to be processed normally even after the limit is reached — otherwise an in-progress test conversation would suddenly stop mid-flow. The cap limits *how many distinct conversations enter*, not *how many messages the admitted ones can send*.
- **Return 200 and drop**, same as the testing-allowlist silent-ignore — never return an error status, or Chatwoot redelivers.

### B.3 The count definition (decide precisely — do NOT guess)

`count_live_testing_conversations()` must count the conversations that occupy the live-testing budget. **Define it as: total rows in `conversations`.**

```python
async def count_live_testing_conversations() -> int:
    pool = get_pool()
    row = await pool.fetchrow("SELECT count(*) AS n FROM conversations")
    return int(row["n"]) if row else 0
```

**Rationale + caveat to surface to the operator:** the cap is on total conversation rows. This means live testing should be started against an **empty or known-count `conversations` table** — if there is pre-existing backlog, that backlog counts against the limit and the effective new-conversation headroom is `LIVE_TESTING_LIMIT − existing_rows`. Document this in `.env.example` next to `LIVE_TESTING_LIMIT`: *"Cap is on total conversations rows. Start live testing from a clean/known table; existing rows count toward the limit."* (A "created since mode enabled" definition would need a marker column and timestamp tracking — deferred as unnecessary complexity; total-rows is the agreed definition.)

---

## PART C — `OUTBOUND_BLOCK`

**Behavior:** when true, no message is sent to a lead. Labels, custom attributes, and private notes still write normally. The bot's flow logic runs unchanged — it advances state as if messages were sent.

### C.1 Where the guard lives

Gate at the **top of `send_with_retry`** in `app/background/send_retry.py` — NOT in `chatwoot_client.send_message`.

**Why `send_with_retry` and not `send_message`:** the outbound audit confirmed `send_with_retry` is the sole caller of `send_message`, and every lead-facing path funnels through it. Gating at `send_with_retry` short-circuits **above** the retry loop, so a deliberate block wastes zero retry attempts and the retry ladder never interacts with a synthetic result. (`send_message` remains the raw API call; leave it unguarded, or add a defensive secondary check there, but the functional guard is in `send_with_retry`.)

### C.2 Exact logic

```python
async def send_with_retry(chatwoot_id: int, content: str) -> <ResultType>:
    if settings.outbound_block:
        logger.info("OUTBOUND_BLOCK: suppressed message to conversation %s", chatwoot_id)
        return <ResultType>(ok=True)   # synthetic success — no API call, no retries
    # ... existing retry logic unchanged ...
```

- **Return `ok=True`** (synthetic success). Callers (InfoGatherer) branch on `.ok` to advance flow state; returning success makes the flow proceed exactly as in production, silently. Returning failure would trigger retry ladders / escalations and distort the flow being tested — do NOT return failure.
- Match `<ResultType>` to whatever `send_with_retry` currently returns (the result object with `.ok`). Construct the minimal success instance.
- **No API call is made** when blocked.

### C.3 What OUTBOUND_BLOCK must NOT touch

Confirmed distinct from `send_with_retry`/`send_message` by the audit — these continue to work normally when `OUTBOUND_BLOCK=true`:
- `chatwoot_client.set_labels` / `get_labels` (labels — incl. `deal_awaiting`, `human_needed`)
- `chatwoot_client.set_custom_attributes` (attributes)
- `chatwoot_client.send_private_note` (sweep confirmations/rejections)

Do NOT add the guard to the Chatwoot client broadly, to `set_labels`, to `set_custom_attributes`, or to `send_private_note`. The whole point is that labeling works while messaging is silenced.

---

## Files touched

| File | Part | Change |
|---|---|---|
| `app/config.py` | all | Add `live_testing_mode` (bool), `live_testing_limit` (Optional[int]), `outbound_block` (bool) to settings. |
| `.env.example` | all | Add the three vars with comments (incl. the count caveat for the limit). |
| `app/main.py` (`lifespan`) or startup validator | A | Boot-time mutual-exclusion + mode-requires-limit checks; refuse to start on failure. |
| `app/webhooks/chatwoot.py` | B | New-conversation ingestion cap alongside the existing testing-allowlist gate. |
| `app/db/queries.py` | B | `count_live_testing_conversations()`. |
| `app/background/send_retry.py` | C | `OUTBOUND_BLOCK` guard at top of `send_with_retry`, synthetic `ok=True`. |
| `tests/test_config_validation.py` | A | Boot validation: both-modes-on → fail; mode-on-no-limit → fail; limit-without-mode → ok. |
| `tests/test_live_testing_limit.py` | B | New conversation rejected at limit; existing conversation still processed; count = total rows. |
| `tests/test_outbound_block.py` | C | Block on → `send_with_retry` returns ok=True, no API call; `set_labels`/`set_custom_attributes`/`send_private_note` still call through. |

---

## Acceptance criteria

1. `LIVE_TESTING_MODE=true` + `TESTING_LIMITATIONS_MODE=true` → app refuses to start (fatal log).
2. `LIVE_TESTING_MODE=true` + `LIVE_TESTING_LIMIT` unset → app refuses to start (fatal log).
3. `LIVE_TESTING_LIMIT` set + `LIVE_TESTING_MODE=false` → starts normally, limit inert.
4. With mode on and limit N: conversation N+1 (new) is dropped with a 200 + info log; conversations 1..N and all their subsequent messages process normally.
5. Existing conversations are never blocked by the cap, even past N.
6. `OUTBOUND_BLOCK=true`: a flow that would send messages sends zero (no `/messages` API calls), `send_with_retry` returns ok=True, flow state still advances.
7. `OUTBOUND_BLOCK=true`: `set_labels`, `set_custom_attributes`, `send_private_note` still execute and write to Chatwoot.
8. Full `pytest` green.

## Do NOT do (scope guard)

- No InfoGatherer/RecEngine/TagAssigner on/off kill-switches (deferred to settings UI).
- No `AC`/`DC`/`LTC` response-code taxonomy — plain log lines only.
- No "created since mode enabled" tracking for the limit — total-rows count is the definition.
- No guard on labels/attributes/private-notes.
- No per-request re-validation of the mutual-exclusion/limit rules — boot-time only.
- No `chatbot on/off` master switch (deferred).

---

## After this ships

The config layer is done and TagAssigner (Spec 021) can be validated against real conversations safely: set `LIVE_TESTING_MODE=true`, `LIVE_TESTING_LIMIT=10`, `OUTBOUND_BLOCK=true`, let 10 real conversations in, run `tag sweepSafe 10`, and verify labels (incl. `deal_awaiting`) land in Chatwoot with zero messages sent to any lead.
