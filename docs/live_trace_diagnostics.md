# Live trace diagnostics (live test)

Structured tracing for webhook → debounce → InfoGatherer → RecEngine → Chatwoot outbound.

## Enable

- **`LIVE_TRACE_ENABLED=true`** in `.env`, **or**
- **`LIVE_TESTING_MODE=true`** (trace turns on automatically on startup)

Optional: **`LIVE_TRACE_JSONL_PATH=logs/live_trace.jsonl`** (default) — append-only log for post-mortem.

Restart **uvicorn** after changing env.

## Screens

| URL | Purpose |
|-----|---------|
| `http://localhost:8000/diagnostics` | **Live stream** — SSE event tail, filters, detail pane |
| `http://localhost:8000/diagnostics/flow` | **Pipeline view** — per Chatwoot conversation event path |
| `http://localhost:8000/diagnostics/api/events?limit=2000` | Raw JSON export |
| `http://localhost:8000/diagnostics/api/stats` | Ring buffer stats |

Through **ngrok**: `https://<your-host>/diagnostics` (same app port).

## Layers

- **http** — request start/end on `/webhooks`, `/internal`
- **webhook** — Chatwoot events, takeover, abstain, debounce schedule
- **debounce** — buffer, flush, immediate (window=0)
- **infoGatherer** — `process_message`, terminal/bot_disabled
- **recEngine** — FOUND / selection
- **internal** — RecEngine start/callback
- **chatwoot** — send attempts, API results, OUTBOUND_BLOCK

## Diagnosing “no outbound”

Watch for this sequence on a **new** conversation:

1. `webhook:inbound_scheduled_debounce`
2. `debounce:inbound_buffered` → `debounce:flush_start`
3. `webhook:process_inbound_start` → `backfill_fresh_thread` or `abstain_prior_history`
4. `infoGatherer:process_message_start` (not `bot_disabled` / `terminal_no_action`)
5. `chatwoot:send_attempt` → `send_ok`

If you see **`inbound_scheduled_debounce`** but **never `debounce:flush_start`**, the background/debounce path did not run.

If you see **`human_takeover`** or **`outbound_first_abstain`** before step 4, an agent replied first.

**Healthy debounce path:** `inbound_buffered` → `flush_start` → `process_inbound_start` → `process_message_start` (or `abstain_*`).

**Historical failure (fixed):** stop right after `process_inbound_start` with **no inbound DB rows** and no `process_message_start` — the debounce timer cancelled itself inside `_pop_debounce_state` mid-flush. Guard: skip `task.cancel()` when `state.task is asyncio.current_task()`.

## Persistence

- In-memory ring: last **8000** events (lost on restart)
- JSONL: `logs/live_trace.jsonl` — safe to `tail -f` in another terminal
