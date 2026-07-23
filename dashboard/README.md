# Chatbot Dashboard

Read-only operations UI for the Univotel Chatbot. Full design rationale and the
derivation rules live in [`../DASHBOARD_SPEC.md`](../DASHBOARD_SPEC.md).

Served by the same FastAPI process as the bot — no second service, no second
connection pool. The dashboard never writes to the database.

## Routes

| Path | What |
|---|---|
| `/` | 307 → `/infogatherer` |
| `/infogatherer` | Overview: KPI row + 10 most recent conversations |
| `/infogatherer/conversations` | Conversation table, filters, both panels |
| `/infogatherer/statistics` | KPI row, three pies, trigger table, two case lists |
| `/infogatherer/logs` | Standalone log browser |
| `/api/dashboard/*` | JSON API (§5 of the spec) |

`/diagnostics` is untouched and keeps its own live-trace UI.

## Configuration

```bash
DASHBOARD_USER=admin           # required
DASHBOARD_PASSWORD=...         # required
DASHBOARD_STALE_HOURS=24       # optional, default 24
```

Auth **fails closed**: with either credential unset every dashboard route returns
`503`, including in local development. The dashboard serves lead phone numbers and
full chat transcripts, so an unconfigured deployment must not be an open one.

`DASHBOARD_STALE_HOURS` is the window after which a conversation still sitting in
an `awaiting_*` state is classified `failed` (stalled). It is surfaced in the UI
next to the failure count so the number is never mistaken for a hard error count.

## Layout

```
dashboard/
  api/          FastAPI router, SQL, derivations (Python)
    sql.py        canonical SQL — one definition per rule
    derive.py     pure functions: signatures, origin state, slices, bubbles
    queries.py    asyncpg calls, reusing the bot's pool
    router.py     endpoints
    auth.py       HTTP Basic, fail-closed
    static.py     SPA mount + catch-all
  web/          Vite + React + TypeScript + Tailwind source
  dist/         committed build output (see below)
```

## Building the frontend

Railway runs a Python-only buildpack and will **not** execute npm, so
`dashboard/dist/` is committed to the repository. After changing anything under
`dashboard/web/src`, rebuild and commit the result:

```bash
cd dashboard/web
npm ci
npm run build      # writes ../dist
```

Forgetting this is the one easy mistake here: the server keeps serving the old
`dist/` and the change appears to have done nothing.

## Local development

Two processes, with the Vite dev server proxying the API:

```bash
# terminal 1 — the bot + API
DASHBOARD_USER=admin DASHBOARD_PASSWORD=dev uvicorn app.main:app --port 8000

# terminal 2 — hot-reloading UI on http://localhost:5174
cd dashboard/web && npm run dev
```

The proxy forwards `/api/dashboard` to port 8000. The browser will prompt for the
Basic credentials on the first API call.

To run against the built assets instead, just start uvicorn and open
`http://localhost:8000/infogatherer`.

## Tests

```bash
pytest tests/dashboard                      # derivations, API, route preservation
pytest -m integration tests/dashboard       # STATUS_EXPR against a real Postgres
cd dashboard/web && npm test                # panel state machine, formatting
```

`tests/dashboard/test_routes_preserved.py` is the guard on the single edit made to
existing code (two additive blocks in `app/main.py`). It asserts `/diagnostics`,
`/health`, and the webhooks still resolve to their original handlers, and that an
unknown `/webhooks/*` path 404s rather than receiving the SPA shell.

The integration suite writes inside a transaction that is always rolled back; it
never leaves rows behind.

## Indexes

`migrations/032_dashboard_indexes.sql` is additive and optional at current volume.
Apply it before the tables grow — it also adds the missing index on
`messages.conversation_id`, which the running bot joins on and had no index for.

## Known limits

- **Log payloads are not captured.** `chatbot_logs` has no request/response
  columns, so the Details panel says so rather than rendering an empty block.
  §12 of the spec defines the additive capture; it is not implemented.
- **`from_state` / `to_state` are never populated** by any call site, so the
  "human needed by flow state" pie reconstructs the originating state from a
  signature lookup (`derive._SIGNATURE_ORIGIN`). Escalations reachable from
  several states are honestly reported as `unknown`. §12.1 makes this exact with
  a two-line change.
- **RecEngine escalations write no log row**, so their reason and timestamp are
  inferred. Every such value carries a `reason_source` other than `log`, and the
  UI marks it.
