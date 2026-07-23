# Chatbot Dashboard — Implementation Spec

**Status:** Ready to implement. No code written yet.
**Location:** all dashboard code lives in `/dashboard` at repo root.
**Constraint:** no existing behaviour changes. Exactly one line-level edit to an existing
file is required (`app/main.py`, two additive lines) — called out in §3.4. `/diagnostics`
is untouched.

---

## 0. Decisions taken (confirmed with the developer)

| # | Decision | Chosen |
|---|---|---|
| 1 | What counts as a red "failed" conversation | Errors **+** stalled; abstains get a 6th `not_run` class excluded from percentage denominators |
| 2 | Log input/output JSON payloads | Phase 1 read-only against existing columns; Phase 2 capture specced in §12, gated on separate approval |
| 3 | Stack | React + Vite + TypeScript + Tailwind + Recharts, static build served by FastAPI |
| 4 | Auth | HTTP Basic, env-gated, fail-closed |

---

## 1. What the data actually supports

Read directly from the live Supabase database on 2026-07-23. This section is the
foundation for every algorithm below — the gaps here are why §4 exists.

### 1.1 Tables in play

| Table | Rows today | Role in the dashboard |
|---|---|---|
| `conversations` | 22 | Row source for the Conversations table; `flow_state` drives 4 of 5 colors |
| `messages` | 133 | Transcript, lead name, human-takeover timestamp, trigger messages |
| `chatbot_logs` | 9 | Log rows, failure reasons, escalation timestamps |
| `rec_engine_logs` | 1 | RecEngine failure attribution (escalations that write no `chatbot_logs` row) |
| `tag_assigner_runs` / `_logs` / `_queue` | 0 | Out of scope — future TagAssigner nav item |

### 1.2 `flow_state` — the live CHECK constraint

```
'new' | 'awaiting_university' | 'awaiting_university_clarification'
| 'awaiting_campus_clarification' | 'awaiting_gender' | 'recengine_running'
| 'completed' | 'human_needed' | 'stopped'
```

Current distribution: `stopped` 14, `new` 5, `human_needed` 1, `completed` 1,
`awaiting_university` 1.

### 1.3 The five statuses, traced to their write sites

| Status | Source of truth | Verified write sites |
|---|---|---|
| **success** (green) | `flow_state = 'completed'` | `info_gatherer.py` `_fire_hotel_path`, `_fire_out_of_city`; `internal.py` RecEngine callback |
| **human_needed** (purple) | `flow_state = 'human_needed'` | `queries.set_conversation_human_needed()` — 4 call sites: `info_gatherer.py:106,192,584`, `rec_engine_ladder.py:61`, `internal.py:111,130` |
| **human_interruption** (chatwoot blue) | `flow_state = 'stopped'` | `queries.set_conversation_stopped()` — **exactly one** call site: `chatwoot.py:730`, the human-agent-takeover branch. This mapping is unambiguous. |
| **in_progress** (gray) | any `awaiting_*` / `new` / `recengine_running` state, recently active | — |
| **failed** (red) | **not represented in the schema — derived**, see §4.1 | — |

### 1.4 Gaps that shape the design

These are findings, not blockers. Each has a stated mitigation.

- **G1 — No lead name column.** `conversations` stores `contact_phone` only. Names
  live on `messages.sender_name` for `sender_type='contact'` (verified: "Cansu Deniz",
  "Meral", "ENES", …). → derived in §4.2.
- **G2 — No failure state.** See §4.1.
- **G3 — `chatbot_logs` has no payload columns.** Columns are `id, created_at,
  conversation_id, operation_layer, which_run, from_state, to_state, log_level,
  is_success, status_code, internal_class, network_status, database_status,
  explanation`. No JSON input/output, no sender/receiver. → §4.6 defines what the
  Details panel shows in Phase 1; §12 defines the Phase 2 capture.
- **G4 — `from_state` / `to_state` exist but are never populated.** No `write_log()`
  call site passes them. This is why "human needed broken down by flow_state" can't be
  read directly — a `human_needed` conversation has overwritten the state it escalated
  *from*. → §4.5 reconstructs it from a lookup table; §12.1 makes it exact with a
  two-line change.
- **G5 — RecEngine escalations write no log row.** `rec_engine_ladder.py:61` and
  `internal.py:111,130` set `human_needed` without calling `write_log()`. Those
  conversations have no explanation. → §4.4 fallback chain + `reason_source` field.
- **G6 — Unhandled exceptions are invisible in the DB.** `_process_inbound` catches
  exceptions and emits a trace event only (`chatwoot.py:858`). Not persisted.
  → §12.2.
- **G7 — No index on `messages.conversation_id` or `chatbot_logs.conversation_id`.**
  Confirmed against `pg_indexes`. Fine at 133 rows, a problem at 10⁵. → §11.2.
- **G8 — `logs/live_trace.jsonl` is not a durable source.** It is gitignored,
  written only when `LIVE_TRACE_ENABLED=true`, and Railway's filesystem is ephemeral.
  Not used as a dashboard data source.

---

## 2. Scope

### In scope
Four routes under a single-page app: `/infogatherer`, `/infogatherer/conversations`,
`/infogatherer/statistics`, `/infogatherer/logs`. Left nav (collapsible), center content,
conditional right panel. Read-only.

### Out of scope
Writing to `conversations` / `messages` / Chatwoot. TagAssigner and RecEngine nav items
(the nav is built to accept them; only InfoGatherer is populated). Real-time streaming —
`/diagnostics` already covers that; this dashboard polls.

### Preserved verbatim
`/diagnostics`, `/diagnostics/flow`, `/diagnostics/api/*`, `/webhooks/*`, `/internal/*`,
`/health`.

---

## 3. Architecture

### 3.1 Layout

```
/dashboard
  __init__.py
  api/
    __init__.py
    router.py         FastAPI APIRouter, prefix /api/dashboard
    auth.py           HTTP Basic dependency (§3.5)
    sql.py            canonical SQL fragments — single source of truth for derivations
    queries.py        asyncpg calls, reusing app.db.client.get_pool()
    schemas.py        pydantic response models
    derive.py         pure Python: failure signatures, origin-state map, name normalisation
    static.py         StaticFiles mount + SPA catch-all
  web/
    package.json  vite.config.ts  tsconfig.json  tailwind.config.ts  index.html
    src/
      main.tsx  App.tsx  routes.tsx
      api/client.ts  api/types.ts        generated from schemas.py shapes
      components/
        AppShell.tsx  LeftNav.tsx  RightPanel.tsx
        ConversationTable.tsx  StatusChip.tsx  StatusLegend.tsx
        LogTable.tsx  LogRow.tsx  LogDetail.tsx
        Transcript.tsx  MessageBubble.tsx  FlowMarker.tsx
        StatCard.tsx  RankedPie.tsx  TriggerTable.tsx  FullMessageModal.tsx
        Filters.tsx  Pagination.tsx  EmptyState.tsx  ErrorState.tsx
      pages/
        InfoGathererOverview.tsx  Conversations.tsx  Statistics.tsx  Logs.tsx
      state/panel.ts  state/filters.ts
      lib/format.ts  lib/colors.ts
  dist/                 committed build output (see §3.3)
  README.md             build + deploy instructions
```

`dashboard` is importable as a top-level package because uvicorn runs from repo root
(`Procfile`: `uvicorn app.main:app`).

### 3.2 Runtime

Same uvicorn process, same asyncpg pool (`app.db.client.get_pool()`). No new connection
pool, no new process, no new Railway service. The dashboard is strictly a reader.

### 3.3 Build & deploy

Railway runs a Python-only buildpack; it will not run `npm`. Therefore
**`dashboard/dist/` is committed to the repo** and `dashboard/web/node_modules` is
gitignored. Build is a local/CI step:

```bash
cd dashboard/web && npm ci && npm run build   # emits ../dist
```

`dashboard/README.md` documents this and the `.gitignore` additions:
```
dashboard/web/node_modules/
dashboard/web/.vite/
```
`dist/` is deliberately **not** ignored. A CI check (§13.4) fails the build if `dist/` is
stale relative to `src/`.

Vite config: `base: '/'`, `build.outDir: '../dist'`, `build.emptyOutDir: true`.

### 3.4 Mounting — the one edit to existing code

At the end of `app/main.py`, after the existing `app.include_router(...)` block:

```python
from dashboard.api.router import router as dashboard_router   # noqa: E402
from dashboard.api.static import mount_dashboard              # noqa: E402

app.include_router(dashboard_router)
mount_dashboard(app)      # must be LAST — registers the SPA catch-all
```

Ordering is load-bearing. FastAPI matches routes in registration order, so the catch-all
only sees paths no existing router claimed. `mount_dashboard` additionally hard-excludes
`/webhooks`, `/internal`, `/health`, `/diagnostics`, `/api` by prefix and returns 404 for
them rather than serving `index.html`, so a future router registered after it can never be
shadowed.

Route table after mounting:

| Path | Served by |
|---|---|
| `/` | 307 → `/infogatherer` |
| `/infogatherer`, `/infogatherer/*` | `index.html` (SPA handles routing) |
| `/assets/*` | `StaticFiles` from `dashboard/dist/assets` |
| `/api/dashboard/*` | `dashboard.api.router` |
| `/diagnostics*`, `/webhooks/*`, `/internal/*`, `/health` | unchanged |

### 3.5 Auth

```python
# dashboard/api/auth.py
DASHBOARD_USER / DASHBOARD_PASSWORD  →  two new optional settings on app.config.Settings
```

- `HTTPBasic` dependency applied to **both** the API router and the static mount.
- Comparison via `hmac.compare_digest` on both fields; compare both even when the
  username already mismatched, so timing does not leak which field was wrong.
- **Fail closed:** if either env var is unset or empty, every dashboard route returns
  `503 {"detail": "Dashboard auth not configured"}`. The dashboard never serves lead PII
  unauthenticated, including in local dev — set the vars in `.env`.
- 401 responses carry `WWW-Authenticate: Basic realm="Univotel Dashboard"`.
- Adding two optional fields to `Settings` is additive; no existing validator changes.

`.env.example` additions:
```
# Dashboard (/infogatherer). Both required — unset means the dashboard refuses to serve.
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=change_me
# Hours of inactivity before a mid-flow conversation is classified 'failed' (stalled).
DASHBOARD_STALE_HOURS=24
```

---

## 4. Derivations — the algorithms

All of these live in `dashboard/api/sql.py` (SQL) and `dashboard/api/derive.py` (Python)
as **one definition each**, imported by every endpoint. No endpoint re-implements a rule.

### 4.1 `status` — the six-way classification

Evaluated in strict order; first match wins.

```sql
-- dashboard/api/sql.py :: STATUS_EXPR   ($1 = stale_hours)
CASE
  WHEN c.flow_state = 'completed'                       THEN 'success'
  WHEN c.flow_state = 'human_needed'                    THEN 'human_needed'
  WHEN c.flow_state = 'stopped'                         THEN 'human_interruption'
  WHEN c.bot_enabled = false
       AND c.infogatherer_abstain_reason = 'backfill_failed'
                                                        THEN 'failed'
  WHEN EXISTS (SELECT 1 FROM chatbot_logs l
               WHERE l.conversation_id = c.id
                 AND l.log_level IN ('error','fatal'))   THEN 'failed'
  WHEN c.flow_state IN ('new','awaiting_university',
                        'awaiting_university_clarification',
                        'awaiting_campus_clarification',
                        'awaiting_gender','recengine_running')
       AND COALESCE(c.last_message_at, c.created_at)
           < now() - make_interval(hours => $1)          THEN 'failed'
  WHEN c.bot_enabled = false
       AND c.infogatherer_abstain_reason = 'prior_history'
                                                        THEN 'not_run'
  ELSE 'in_progress'
END
```

Rationale for the ordering:

- `completed` / `human_needed` / `stopped` are terminal and win over everything. A
  conversation that hit an error and *then* got escalated is purple, not red — the
  escalation is the outcome that matters. Its error is still visible in its log rows.
- `outbound_first` abstains need no branch: `chatwoot.py:730` sets `stopped` **before**
  `chatwoot.py:733` sets the abstain reason, so they already classify as
  `human_interruption` — which is semantically right, a human agent sent the first message.
- `prior_history` abstains are the bot *correctly declining* a pre-existing thread. They
  are 6 of the 22 current rows; counting them red would make the headline failure rate
  meaningless. They get `not_run`.
- Stalled = the bot asked a question and nobody ever answered. Window is
  `DASHBOARD_STALE_HOURS`, default 24, surfaced in the UI as "stale after 24h" next to
  the failure count so the number is never mistaken for a hard error count.

`not_run` is the sixth class beyond the five specified. It is styled deliberately
recessively (§6.2) and **excluded from every percentage denominator** (§8.1), with the
excluded count shown as a footnote so it is never silently dropped.

### 4.2 `lead_name`

```sql
COALESCE(
  (SELECT m.sender_name FROM messages m
    WHERE m.conversation_id = c.id
      AND m.sender_type = 'contact'
      AND m.is_private = false
      AND m.sender_name IS NOT NULL AND btrim(m.sender_name) <> ''
    ORDER BY COALESCE(m.sent_at, m.created_at) DESC
    LIMIT 1),
  NULLIF(c.contact_phone, ''),
  'Conversation #' || c.chatwoot_conversation_id
)
```

`is_private = false` matters: non-tag private notes are inserted with
`sender_type='contact'` at `chatwoot.py:757`, and their `sender_name` is the agent's, not
the lead's. Most-recent-wins because Chatwoot contact names get corrected over time.
When the fallback fires, the UI renders the value in muted italic so a phone number is
never mistaken for a name.

### 4.3 `conversation_identifier`

`chatwoot_conversation_id` (int), displayed as `#1704`. The UUID `conversations.id` is
carried in API responses as `id` for joins but is never the user-facing identifier. All
dashboard URLs key on the int.

### 4.4 `failure_reason` — resolution chain

First non-null wins:

1. Latest `chatbot_logs` row for the conversation with `log_level IN ('error','fatal')`,
   ordered by `created_at DESC` → `explanation`, `reason_source = 'log'`.
2. Latest `rec_engine_logs` row with `status = 'failed'` → synthesised
   `"RecEngine failed (status_code=<code>, network=<network_status>)"`,
   `reason_source = 'rec_engine'`. Covers G5's `internal.py:111` path.
3. `flow_state = 'human_needed'` with no log and no failed RecEngine row, but a
   `rec_engine_logs` row still `processing` → `"RecEngine ladder exhausted — 3 attempts,
   no resolution"`, `reason_source = 'inferred'`. Covers G5's `rec_engine_ladder.py:61`.
4. Status is `failed` via the stale branch → `"Stalled — no activity for <N>h in state
   <flow_state>"`, `reason_source = 'stale'`.
5. Otherwise `null`, `reason_source = 'unknown'`.

`reason_source` ships in every API response and renders as a small chip, so an inferred
reason is never presented as a logged fact.

### 4.5 `origin_flow_state` — what state it escalated from

Needed for two of the three pie charts. `human_needed` overwrites `flow_state`, so the
originating state must be reconstructed (G4).

Resolution chain:
1. `chatbot_logs.from_state` when non-null. Always null today; becomes the exact answer
   after §12.1.
2. Static lookup keyed on the failure signature (§4.6). Every escalation call site in the
   codebase has a distinct explanation string:

   | Signature | Origin |
   |---|---|
   | `post_completion_no_hotel` | `completed` |
   | `university_clarification_twice` | `awaiting_university_clarification` |
   | `gender_set_university_missing` | `awaiting_gender` |
   | `missing_pending_parent` | `awaiting_campus_clarification` |
   | `parent_no_campus_rows` | `awaiting_campus_clarification` |
   | `campus_question_build_failed` | `awaiting_campus_clarification` |
   | `no_response_schema_for_hotel` | `completed` |
   | `no_schema_messages_sent` | `completed` |
   | `abstain_backfill_failed` | `new` |
   | `recengine_*` (any) | `recengine_running` |
   | `divergence_unhandled`, `off_script_no_answer` | `unknown` — reachable from four states |

3. For non-escalated failures (stalled), `flow_state` is intact → use it directly.
4. Otherwise `'unknown'`.

`unknown` is always rendered as its own slice, never hidden or merged, so the
reconstruction's coverage is visible.

### 4.6 `failure_signature` — normalising explanations for grouping

Raw `explanation` strings interpolate message content and UUIDs
(`"University clarification reply 'xyz' failed twice"`), so grouping raw text yields a
useless long tail. Ordered rules, in `derive.py`:

1. `internal_class` non-null → use it, with `divergence:<intent>` collapsed to
   `divergence`.
2. Else normalise `explanation`:
   a. replace UUIDs (`[0-9a-f]{8}-…`) → `<id>`
   b. replace `'…'` single-quoted spans → `'…'`
   c. replace standalone integer runs → `<n>`
   d. collapse whitespace, trim
   e. match against the known-signature table below; on hit use the slug
   f. on miss, truncate to 120 chars and use as the signature verbatim
3. Else `status_code` non-null → `http_<code>`
4. Else `unclassified`

Known-signature table (seeded from every current `write_log` call site, with the display
label used in legends):

| Normalised explanation | Slug | Label |
|---|---|---|
| `Post-completion message did not name a specific hotel — deferred to human` | `post_completion_no_hotel` | Post-completion, no hotel named |
| `No response schema messages could be sent for eligible hotels` | `no_schema_messages_sent` | No hotel schema messages sent |
| `No matching row in response_schemas for hotel_id=<id>` | `no_response_schema_for_hotel` | Missing response schema |
| `University clarification reply '…' failed twice — FallBack stub` | `university_clarification_twice` | University clarification failed twice |
| `Divergence routing escalate (missing row or persistence cap)` | `divergence_unhandled` | Divergence unhandled |
| `Divergence classifier failed for '…'` | `off_script_no_answer` | Divergence classifier failed |
| `Gender set but university missing after gender slot reply` | `gender_set_university_missing` | Gender set, university missing |
| `awaiting_campus_clarification with no pending_parent_university_id — data inconsistency` | `missing_pending_parent` | Missing pending parent |
| `No campus rows for pending parent <id>` | `parent_no_campus_rows` | Parent has no campuses |
| `Parent university <id> has no campus rows — cannot escalate` | `parent_no_campus_rows` | Parent has no campuses |
| `Failed to build campus question for parent <id>` | `campus_question_build_failed` | Campus question build failed |
| `InfoGatherer abstained: Chatwoot transcript fetch failed` | `abstain_backfill_failed` | Backfill failed |
| *(derived, no log)* | `recengine_ladder_exhausted` | RecEngine ladder exhausted |
| *(derived, no log)* | `recengine_502` | RecEngine 502 |
| *(derived, no log)* | `recengine_invalid_found` | RecEngine invalid payload |
| *(derived, stale)* | `stalled` | Stalled — no reply |

Unknown signatures render with their truncated text as the label. The table is data, not
control flow — adding a row is a one-line change.

### 4.7 `takeover_at` — when the human interrupted

```sql
(SELECT MIN(COALESCE(m.sent_at, m.created_at)) FROM messages m
  WHERE m.conversation_id = c.id
    AND m.message_type = 'outbound'
    AND m.sender_type = 'user'
    AND m.is_private = false)
```

`sender_type='user'` on an outbound message is written at exactly one place —
`chatwoot.py:731`, the takeover branch — so this is exact. `is_private=false` excludes tag
command notes, which `chatwoot.py:671` also writes as `sender_type='user'`. `automation`
and `infoGatherer` are correctly excluded.

### 4.8 `escalated_at` — when it went human_needed

```sql
COALESCE(
  (SELECT MAX(l.created_at) FROM chatbot_logs l
    WHERE l.conversation_id = c.id AND l.log_level = 'fatal' AND l.is_success = false),
  c.last_updated_at)
```

Every `_escalate_human_needed` writes `log_level='fatal', is_success=false` before
setting the state, so the log timestamp is the tight bound. `last_updated_at` is the
fallback for the RecEngine paths (G5) — looser, since any later write moves it; flagged
in the response as `escalated_at_exact: false`.

### 4.9 `log_status` — color class for a log row

The spec asks for log rows color-coded "the same as the conversation rows". Four of the
five classes map naturally; blue does not, because human interruption produces no log
row. Ordered rules:

| Rule | Class |
|---|---|
| `is_success = true` | success (green) |
| `log_level = 'fatal'` | human_needed (purple) — every `fatal` in this codebase is an escalation |
| `log_level = 'error'` | failed (red) |
| `log_level = 'warn'` and `is_success = false` | failed (red) |
| otherwise (`info` / `is_success IS NULL`) | in_progress (gray) |

Blue is reached only via §4.10.

### 4.10 Derived log events — filling the timeline

Three conversation-level events produce no `chatbot_logs` row, which would leave gaps in
the per-conversation log list. The API synthesises them, always flagged
`derived: true` and rendered with a "derived" chip so they are never mistaken for
persisted rows:

| Event | Condition | Timestamp | Class |
|---|---|---|---|
| `human_takeover` | `flow_state='stopped'` and `takeover_at` is non-null | `takeover_at` (§4.7) | human_interruption (blue) |
| `recengine_escalation` | `human_needed` with no `fatal` log | `escalated_at` (§4.8) | human_needed (purple) |
| `stalled` | status `failed` via the stale branch | `last_message_at + stale_hours` | failed (red) |

Derived events have `id = "derived:<kind>:<conversation_uuid>"` so the UI can key them,
and their Details panel shows the derivation inputs rather than a fake log row.

---

## 5. API contract

All endpoints are `GET`, prefix `/api/dashboard`, all behind Basic auth. All responses
are JSON. Timestamps are ISO-8601 UTC with `Z`; the client renders in
`Europe/Istanbul` (the business timezone) with a UTC tooltip.

Shared error envelope: `{"detail": "<message>"}` with 400 / 401 / 404 / 503.

### 5.1 `GET /meta`

Static config the client needs to render without hardcoding server truth.

```jsonc
{
  "stale_hours": 24,
  "flow_states": ["new", "awaiting_university", "...", "stopped"],
  "statuses": ["success","failed","in_progress","human_needed","human_interruption","not_run"],
  "log_levels": ["info","warn","error","fatal"],
  "operation_layers": ["infoGatherer","recEngine","tagAssigner","fallBack"],
  "which_runs": ["contextRun","outputRun"],
  "server_time": "2026-07-23T11:02:00Z"
}
```

### 5.2 `GET /infogatherer/conversations`

Query params: `status` (repeatable), `flow_state` (repeatable), `q` (free text),
`from` / `to` (ISO date, filters `created_at`), `sort` (`last_activity|created|name|cwid`,
default `last_activity`), `dir` (`asc|desc`, default `desc`), `limit` (default 50,
max 200), `offset`.

`q` matches, case-insensitively: derived `lead_name`, `contact_phone` (digits stripped
from the query first), and `chatwoot_conversation_id` when the query is all digits.

```jsonc
{
  "total": 22,
  "limit": 50,
  "offset": 0,
  "rows": [{
    "id": "f2a1baa2-…",
    "chatwoot_conversation_id": 1708,
    "lead_name": "Cansu Deniz",
    "lead_name_is_fallback": false,
    "flow_state": "completed",
    "status": "success",
    "origin_flow_state": "completed",
    "failure_reason": null,
    "reason_source": "unknown",
    "message_count": 12,
    "log_count": 2,
    "created_at": "2026-07-22T21:57:47Z",
    "last_activity_at": "2026-07-22T21:58:01Z",
    "takeover_at": null,
    "escalated_at": null
  }]
}
```

`last_activity_at` = `COALESCE(last_message_at, last_updated_at, created_at)`.

### 5.3 `GET /infogatherer/conversations/{cwid}`

Single row, same shape as §5.2 plus `university_id`, `university_name`, `gender`,
`ilgili_otel`, `labels`, `bot_enabled`, `infogatherer_abstain_reason`,
`reprompt_count`, `clarification_attempt`, `auto_run_count`, `manual_run_count`.
404 if no conversation has that `chatwoot_conversation_id`.

### 5.4 `GET /infogatherer/conversations/{cwid}/logs`

Persisted `chatbot_logs` rows plus derived events (§4.10), merged and sorted by
timestamp ascending.

```jsonc
{
  "conversation": { "chatwoot_conversation_id": 1704, "lead_name": "Meral", "status": "human_interruption" },
  "rows": [{
    "id": "0c8f…",
    "derived": false,
    "created_at": "2026-07-22T21:30:25Z",
    "operation_layer": "infoGatherer",
    "which_run": "contextRun",
    "operation_label": "infoGatherer · contextRun",
    "log_level": "fatal",
    "is_success": false,
    "log_status": "human_needed",
    "status_code": null,
    "internal_class": null,
    "signature": "post_completion_no_hotel",
    "signature_label": "Post-completion, no hotel named",
    "from_state": null,
    "to_state": null,
    "network_status": null,
    "database_status": null,
    "explanation": "Post-completion message did not name a specific hotel — deferred to human"
  }]
}
```

`operation_label` is the "operation name" the spec asks for: `operation_layer` +
`which_run`, with `internal_class` appended when present.

### 5.5 `GET /infogatherer/logs/{log_id}`

Full detail for the right panel. `log_id` accepts a UUID or a `derived:…` id.

```jsonc
{
  "log": { /* every column, unabridged */ },
  "conversation": { "chatwoot_conversation_id": 1704, "lead_name": "Meral",
                    "status": "human_interruption", "flow_state": "stopped" },
  "context": {
    "preceding_messages": [ /* up to 3 messages before log.created_at */ ],
    "following_messages": [ /* up to 3 after */ ]
  },
  "payload": {
    "available": false,
    "note": "Request/response payloads are not captured for this log. See DASHBOARD_SPEC.md §12.",
    "input": null,
    "output": null,
    "source": null,
    "target": null
  },
  "raw": { /* the log row as a flat dict, for the JSON viewer */ }
}
```

`payload.available` is `false` for every Phase 1 row. The panel renders the note in place
of an empty JSON block rather than showing `null` — the absence is explained, not hidden.
After §12, `available` flips to `true` for newly written rows with no client change.

Message-bracketing uses `messages.created_at` (pipeline persist time), **not** `sent_at`,
because `chatbot_logs.created_at` is also a persist-time clock. Ordering two different
clocks would misplace rows by seconds. Displayed times remain `sent_at`.

### 5.6 `GET /infogatherer/conversations/{cwid}/messages`

```jsonc
{
  "conversation": { "chatwoot_conversation_id": 1704, "lead_name": "Meral", "status": "human_interruption" },
  "messages": [{
    "id": "…", "chatwoot_message_id": 13812,
    "direction": "inbound",
    "bubble": "inbound",            // inbound | bot | human | private
    "sender_type": "contact",
    "sender_name": "Meral",
    "content": "Bu sene ıstanbulda…",
    "is_private": false,
    "sent_at": "2026-07-22T21:20:03Z",
    "created_at": "2026-07-22T21:20:09Z"
  }],
  "markers": [{
    "kind": "failure",              // failure | human_needed | human_interruption
    "at": "2026-07-22T21:35:17Z",
    "after_message_id": "…",
    "label": "Human agent took over",
    "detail": "Çınar Varlık sent an outbound message; InfoGatherer stopped.",
    "log_id": null
  }]
}
```

`bubble` mapping — the single rule the transcript renders from:

| `message_type` | `sender_type` | `is_private` | `bubble` |
|---|---|---|---|
| inbound | contact | false | `inbound` |
| outbound | infoGatherer, fallBack | false | `bot` |
| outbound | user, automation | false | `human` |
| any | any | true | `private` |

Messages sort by `COALESCE(sent_at, created_at)` ascending. Markers are positioned by
finding the last message whose `created_at <= marker.at` and attaching to it via
`after_message_id`; a marker earlier than every message attaches to the top with
`after_message_id: null`.

### 5.7 `GET /infogatherer/logs`

Global log list. Params: `conversation` (cwid), `log_level` (repeatable),
`is_success` (`true|false`), `operation_layer`, `which_run`, `signature`,
`q` (substring of `explanation` / `internal_class`), `from`, `to`, `limit`, `offset`,
`include_derived` (default `false` — the global page shows persisted rows by default so
counts are honest; the per-conversation view always includes them).

Rows are §5.4 rows plus `chatwoot_conversation_id` and `lead_name`.

### 5.8 `GET /infogatherer/stats/summary`

```jsonc
{
  "stale_hours": 24,
  "total_conversations": 22,
  "denominator": 16,
  "counts": { "success": 1, "failed": 2, "human_needed": 1,
              "human_interruption": 14, "in_progress": 1, "not_run": 6 },
  "percentages": { "failed": 12.5, "human_needed": 6.3,
                   "success": 6.3, "clean_interruption": 81.3, "in_progress": 6.3 },
  "clean_interruption_count": 13,
  "dirty_interruption_count": 1
}
```

`denominator = total − not_run`. Percentages are one decimal place, computed server-side
so the cards and any export agree. When `denominator = 0`, percentages are `null` and the
cards render an em-dash, not `0.0%`.

**`clean_interruption`** implements "successful until interruption": conversations with
status `human_interruption` that have **no** `chatbot_logs` row with
`log_level IN ('error','fatal')` and `created_at < takeover_at`. That is, the bot was
running correctly right up to the moment a human stepped in. `dirty_interruption_count`
(interrupted *after* the bot had already errored) is returned so the two always
reconcile against `counts.human_interruption`, and appears as a sub-line on the card.

### 5.9 `GET /infogatherer/stats/breakdowns`

```jsonc
{
  "failures_by_flow_state":   { "total": 2, "slices": [{"key":"awaiting_gender","label":"awaiting_gender","count":1,"pct":50.0}] },
  "failures_by_signature":    { "total": 2, "slices": [{"key":"post_completion_no_hotel","label":"Post-completion, no hotel named","count":1,"pct":50.0}] },
  "human_needed_by_flow_state": { "total": 1, "slices": [{"key":"unknown","label":"Unknown origin","count":1,"pct":100.0}] }
}
```

Slice construction, identical for all three (`derive.build_slices`):
1. Count by key, sort by count descending, then key ascending for stable ties.
2. Keep the top 6. If ≥ 2 remain, fold them into `{"key":"__other__","label":"Other (N categories)"}`
   carrying `members: [{key,label,count}]` so the tooltip and table can expand it. A single
   remaining category is kept as itself rather than folded — an "Other" of one is noise.
3. `pct` is of `total`, one decimal, and the largest slice absorbs any rounding residue so
   slices always sum to exactly 100.0.

`failures_by_flow_state` and `human_needed_by_flow_state` key on `origin_flow_state`
(§4.5), not raw `flow_state` — otherwise the human-needed pie would be a single slice
labelled "human_needed", which carries no information.

### 5.10 `GET /infogatherer/stats/human-needed-triggers`

Params: `limit` (default 20).

```jsonc
{
  "total_human_needed": 1,
  "with_trigger": 1,
  "rows": [{
    "normalized": "tamam cok saolun",
    "display_text": "Tamam cok saolun",
    "count": 1,
    "conversations": [{"chatwoot_conversation_id": 1704, "lead_name": "Meral",
                       "sent_at": "2026-07-22T21:30:18Z"}]
  }]
}
```

Algorithm:
1. For each conversation with status `human_needed`, compute `escalated_at` (§4.8).
2. Trigger message = the last inbound, non-private message with
   `COALESCE(sent_at, created_at) <= escalated_at`. Conversations with no such message
   are counted in `total_human_needed − with_trigger` and reported in the UI as
   "N escalations had no preceding inbound message" — never silently dropped.
3. Group by `normalized`: Turkish-aware lowercase (map `İ→i`, `I→ı` **before**
   `casefold()`, otherwise `İstanbul` and `istanbul` split into two groups), collapse
   internal whitespace, trim.
4. `display_text` = the most frequent original casing in the group; ties broken by the
   most recent occurrence.
5. Sort by `count` descending, then most-recent occurrence descending.

---

## 6. Design system

Dark-only. The transcript spec fixes a black background, and a light mode alongside it
would be a second full palette to validate for no stated benefit.

### 6.1 Surfaces and ink

| Token | Hex | Use |
|---|---|---|
| `--bg-page` | `#0A0C10` | app background |
| `--bg-surface` | `#12161C` | cards, panels, table container |
| `--bg-surface-2` | `#171C24` | table header, nav, hover |
| `--bg-transcript` | `#000000` | transcript background (spec: "background is black") |
| `--border` | `#242C38` | dividers, card borders |
| `--text-primary` | `#FFFFFF` | 18.15:1 on surface |
| `--text-secondary` | `#A9B4C4` | labels, timestamps |
| `--text-muted` | `#6B7787` | placeholders, fallback lead names |

### 6.2 Status palette — fixed, never reused for series

Contrast measured against `--bg-surface` `#12161C`.

| Status | Hex | Contrast | Tint (row bg) | Chip label | Icon |
|---|---|---|---|---|---|
| success | `#22C55E` | 7.96 | `rgba(34,197,94,.10)` | Completed | ✓ |
| failed | `#EF4444` | 4.82 | `rgba(239,68,68,.10)` | Failed | ✕ |
| in_progress | `#8B9CB3` | 6.48 | `rgba(139,156,179,.07)` | In progress | ◔ |
| human_needed | `#A855F7` | 4.59 | `rgba(168,85,247,.10)` | Human needed | ⚑ |
| human_interruption | `#1F93FF` | 5.77 | `rgba(31,147,255,.10)` | Interrupted | ⇄ |
| not_run | `#4B5563` rail / `#94A3B8` text | 2.40 / 5.6 | none | Not run | ⊘ |

Every status color ships with **icon + text label**, never color alone — a colorblind
reader and a greyscale print both still read the table. `not_run`'s rail color is
deliberately sub-3:1 (it is a recessive 2px left border, not text); its chip uses
`#94A3B8` for the text so the label itself stays legible.

Row treatment: 3px left border in the status color + the tint as row background. Full
saturated fills across a whole row would fight the text.

### 6.3 Transcript bubbles

| Bubble | Background | Text | Contrast | Align |
|---|---|---|---|---|
| `inbound` (lead) | `#2B3137` chatwoot grey | `#FFFFFF` | 13.15 | left |
| `bot` (infoGatherer, fallBack) | `#1B5FA8` chatwoot dark blue | `#FFFFFF` | 6.46 | right |
| `human` (agent, automation) | `#5B21B6` dark purple | `#FFFFFF` | 8.98 | right |
| `private` | `#2B2718` with `#EAB308` left rail | `#F5E9C8` | 11.2 | right |

Bubble geometry follows Chatwoot: max-width 78%, 12px radius with the corner nearest the
sender squared to 4px, 8px vertical gap, sender name above the first bubble of each run,
timestamp bottom-right inside the bubble in `--text-secondary` at 11px.

Private notes are included because the spec says "exactly as it is in chatwoot" and
Chatwoot shows them. A "Hide private notes" toggle sits in the panel header, default off.
`automation` messages share the `human` purple (they are non-chatbot outbound per the
spec) but carry an "Automation" chip so the distinction stays available.

### 6.4 Flow markers

A full-width horizontal rule at the failure point, 2px in the status color, with a
centered pill carrying an icon, a label, and the explanation:

```
──────────────  ✕  Failed — Post-completion message did not name a specific hotel  ──────────────
```

The spec asks only for the red failure line; purple (`human_needed`) and blue
(`human_interruption`) markers use the identical component, because a transcript that
explains a red stop but silently drops a purple one is harder to read, not simpler.
Clicking a marker with a `log_id` opens that log's Details panel.

### 6.5 Chart palette — computed, not chosen

The three pie charts are an **all-pairs** form: a reader compares any two slices, not just
neighbours. Running the skill validator against the dark surface `#12161C`:

```
3 slots  #199e70,#d95926,#9085e9        → ALL CHECKS PASS (CVD ΔE 9.4, normal 24.6)
4 slots  every subset tried              → FAIL (best case normal-vision ΔE 10.6, floor 15)
6 slots  reference dark categorical      → FAIL (CVD ΔE 1.6)
```

No 4+ slot categorical subset clears the floors all-pairs, and the normal-vision floor is
a hard gate that direct labels do not excuse. So the pies do **not** use a categorical
palette.

**Resolution: a single-hue sequential ramp assigned by rank.** Failures-by-flow-state is a
magnitude question, not an identity question — the reader wants "which is biggest", and
rank order is exactly what a sequential ramp encodes. Adjacent slices then differ in
*lightness*, which every CVD type preserves.

```
rank 1 (largest) #cde2fb   rank 4  #3987e5
rank 2           #9ec5f4   rank 5  #256abf
rank 3           #6da7ec   rank 6  #184f95
"Other"          #4B5563   (neutral gray — outside the ramp, reads as "not a rank")
```

Validated: `--ordinal --mode dark --surface #12161C` → lightness monotone PASS, adjacent
ΔL all ≥ 0.06 PASS, dark-end contrast 2.24:1 PASS, hue spread 4° PASS.

Because color encodes rank rather than identity, every slice is **direct-labelled** with
category, count, and percent on a leader line, plus a legend in rank order, plus a
"Table" toggle under each chart showing the same numbers as rows. Identity is carried by
text; color carries only magnitude.

This palette is entirely separate from §6.2 — a chart slice never wears a status color, so
a blue slice is never misread as "interrupted".

### 6.6 Type

System stack (`ui-sans-serif, -apple-system, Segoe UI, Roboto, …`). Numerals
`font-variant-numeric: tabular-nums` in every table and card so digits align.
Sizes: 11px meta, 13px body/table, 15px section titles, 48px hero numbers on stat cards.
Turkish text is common in this data — no font substitution that lacks `ı`, `ğ`, `ş`, `İ`.

---

## 7. Shell, navigation, and the right panel

### 7.1 Grid

```
┌──────────┬───────────────────────────────┬────────────────┐
│ LeftNav  │  center content               │  RightPanel    │
│ 248px    │  flex-1, min-width 480px      │  480px         │
│ (56px    │                               │  (unmounted    │
│ collapsed)│                              │   when null)   │
└──────────┴───────────────────────────────┴────────────────┘
```

CSS grid, `grid-template-columns: var(--nav-w) minmax(480px,1fr) var(--panel-w)`.
When the panel is closed, `--panel-w: 0` and the component is unmounted, not hidden —
"if it's not displaying information it does not appear", including in the DOM.

Below 1280px the panel overlays the center at 440px with a scrim. Below 900px the nav
auto-collapses to the icon rail. No mobile layout — this is a desk tool.

### 7.2 Left nav

- Header: "Univotel" wordmark + collapse toggle (`⟨` / `⟩`). Collapsed state persists in
  `localStorage['dash.nav.collapsed']`. Collapsed shows icons only with tooltips on hover;
  the active sub-item's parent icon keeps an accent rail so location is never lost.
- Primary item **InfoGatherer** → `/infogatherer`, always expanded, with sub-items
  **Conversations** → `/infogatherer/conversations`, **Statistics** →
  `/infogatherer/statistics`, **Logs** → `/infogatherer/logs`.
- The primary/sub structure is data-driven (`NAV: NavItem[]`), so adding RecEngine or
  TagAssigner later is one array entry.
- Footer: connection status dot, last-refreshed relative time, manual refresh button.

### 7.3 Right panel state machine

```ts
type PanelState =
  | null
  | { kind: 'conversationLogs';  cwid: number }
  | { kind: 'conversationChat';  cwid: number }
  | { kind: 'logDetail';  logId: string; parent: PanelState | null }
  | { kind: 'messageDetail'; cwid: number; messageId: string; parent: PanelState };
```

- Back arrow renders **iff `state.parent !== null`**. Opening a log from the Logs page has
  no parent, so no arrow — matching the spec's "this arrow is only there when the details
  is opened on the panel [from the logs list]".
- Close (`✕`) always present, top-right; sets state to `null`.
- Header text is per-kind, and `conversationLogs` uses the exact wording specified:
  `Conversation (1704)'s Logs`. Others: `Conversation (1704)`, `Log detail`, `Message detail`.
- Panel state is mirrored into the URL query so a panel survives refresh and can be
  shared: `?panel=logs&cwid=1704`, `?panel=log&logId=<uuid>&cwid=1704`,
  `?panel=chat&cwid=1704`. `parent` is reconstructed from the presence of `cwid`.
- Width is drag-resizable 360–840px (persisted), plus an expand toggle that takes the
  panel to `50vw` for reading long transcripts.
- `Esc` closes; `←` (when a parent exists) goes back. Focus moves into the panel on open
  and returns to the invoking button on close.

---

## 8. Pages

### 8.1 `/infogatherer` — overview

Not specified; the route was listed, so it gets content rather than a bare redirect.
Renders the four stat cards from §5.8, the status legend, and the 10 most recent
conversations using the same table component, with "View all →" to
`/infogatherer/conversations`. No new endpoints.

### 8.2 `/infogatherer/conversations`

**Header:** title, total count, status legend strip (all six classes with icon + label —
without it the color coding is undocumented), refresh control.

**Filters** (one row, per the interaction guidance): search box (`q`), status multi-select
chips, flow-state select, date range, "Clear". Filters are URL-synced. *(Addition — the
spec didn't ask for filters, but a table with no way to isolate the failures is unusable
once row counts pass a screenful. Removable without touching anything else.)*

**Table columns** — exactly as specified:

| Lead's name | Conversation | Flow state | *(actions)* |
|---|---|---|---|
| `lead_name`, fallback muted italic | `#1708` | `flow_state` in mono | `[ Logs ] [ Conversation ]` |

- Row color coding per §6.2 (3px left rail + tint). Status chip with icon sits inline
  after the flow state so the color is never the only carrier.
- The two buttons are identical in size and shape (`h-7 min-w-[104px]`, same radius,
  same weight), sitting flush right with an 8px gap, per the spec.
- `Logs` → panel `conversationLogs`. `Conversation` → panel `conversationChat`. The active
  row is highlighted while its panel is open.
- Clicking anywhere else in the row also opens `conversationChat` — the spec's "the
  message content explains on the right side bar when a row on the conversation list is
  clicked".
- Sort on Lead's name, Conversation, Flow state. Pagination 50/page with total.
- Empty state distinguishes "no conversations yet" from "no rows match these filters"
  (the latter offers "Clear filters").

**Panel — `conversationLogs`:** header `Conversation (1708)'s Logs`. Rows carry the same
color coding (§4.9), each showing timestamp, `operation_label`, status chip, and a
truncated explanation, with a right-aligned `Details` button. Derived events carry a
"derived" chip.

**Panel — `logDetail`:** back arrow → the logs list. Sections: Summary (operation, level,
success, status code, internal class, state transition), Explanation (full text,
selectable), Payload (§5.5 — the "not captured" note in Phase 1), Context (3 messages
either side), Raw JSON (collapsible, monospace, with a copy button).

**Panel — `conversationChat`:** the transcript per §6.3, black background, newest at the
bottom, auto-scrolled to the bottom on open, with flow markers inline (§6.4). A
`Hide private notes` toggle and the expand-width control sit in the header. Clicking a
bubble opens `messageDetail` (ids, sender, both timestamps, full content, raw row).

### 8.3 `/infogatherer/statistics`

**Row 1 — four stat cards**, in the spec's colors:

| Failed | Human needed | Successfully completed | Successful until interruption |
|---|---|---|---|
| red `#EF4444` | purple `#A855F7` | green `#22C55E` | blue `#1F93FF` |

Each card: 48px hero percentage, `N of M runs` beneath, a hairline accent bar in the
status color. The blue card carries the sub-line
`13 clean · 1 after an error` so the split from §5.8 is explicit.
Beneath the row: a slim 100%-wide stacked bar of all six classes with a caption
`16 runs · 6 not run (excluded)` — the four cards don't sum to 100 because in-progress
exists, and the bar makes that visible instead of leaving a silent gap.

**Row 2 — three pie charts** (§6.5): Failures by flow state · Failures by error message ·
Human needed by flow state. Each in its own card with title, slice count, a `Table`
toggle, and an empty state (`No failures in this period`) rather than an empty circle.
Hover tooltip gives category, count, percent, and — for `Other` — the folded members.
Clicking a slice navigates to `/infogatherer/conversations` pre-filtered to that
category.

**Row 3 — top human-needed message triggers** (§5.10). Columns: rank, message
(single-line, `text-overflow: ellipsis`), count, `Full Message` button. The button opens a
centered modal with the full text (preserving newlines, `dir="auto"` for Turkish), the
occurrence count, and the list of conversations, each linking to its transcript panel.
Modal closes on `Esc`, backdrop click, and an explicit close button; focus is trapped
while open and restored on close. A footnote reports any escalations with no preceding
inbound message.

**Row 4 — two tables**, identical component to §8.2, pre-filtered and not
user-refilterable: **Human needed cases** (`status=human_needed`) and **Failed cases**
(`status=failed`). Both open the same right panel.

### 8.4 `/infogatherer/logs`

Standalone log browser over `chatbot_logs`.

**Columns:** Time · Conversation (`#1704`, links to its transcript panel) · Lead ·
Operation (`operation_label`) · Level · Success · Status code · Internal class ·
State transition (`from → to`, em-dash while §12.1 is unimplemented) · Explanation
(truncated) · `Details`.

Row color coding per §4.9. Filters: conversation, level, success, layer, which_run,
signature, free text, date range. Default sort `created_at DESC`, 100/page.
`Details` opens `logDetail` with **no back arrow** (no parent).

---

## 9. Client behaviour

- **Data layer:** TanStack Query. `staleTime` 15s, `refetchInterval` 30s on list/stat
  endpoints, `refetchOnWindowFocus: true`. Detail endpoints do not auto-refetch — a panel
  must not mutate under the reader's cursor. A manual refresh button invalidates
  everything.
- **Loading:** skeleton rows matching final geometry, so tables don't reflow.
- **Errors:** 401 → full-page "Session expired, reload to sign in". 503 → "Dashboard auth
  is not configured on the server" with the env var names. 5xx → inline retry, no crash.
- **Never invent a value.** Nulls render as `—`. Derived values carry their
  `reason_source` / `derived` chip. `escalated_at_exact: false` renders the timestamp with
  a `~` prefix and a tooltip explaining the bound.
- **Accessibility:** keyboard-reachable rows and buttons, visible focus rings, table
  headers as `<th scope="col">`, `aria-live="polite"` on the refresh status, modal and
  panel focus management as in §7.3/§8.3.

---

## 10. Response shapes ↔ SQL

One query per endpoint wherever possible; no N+1. `STATUS_EXPR` (§4.1) is injected as a
CTE column, never duplicated per call site.

Conversations list, in outline:

```sql
WITH base AS (
  SELECT c.*,
         <LEAD_NAME_EXPR>       AS lead_name,
         <TAKEOVER_AT_EXPR>     AS takeover_at,
         <ESCALATED_AT_EXPR>    AS escalated_at,
         <STATUS_EXPR>          AS status,
         COALESCE(c.last_message_at, c.last_updated_at, c.created_at) AS last_activity_at
  FROM conversations c
),
counted AS (
  SELECT b.*,
    (SELECT count(*) FROM messages m
      WHERE m.conversation_id = b.id AND m.is_private = false) AS message_count,
    (SELECT count(*) FROM chatbot_logs l
      WHERE l.conversation_id = b.id)                          AS log_count
  FROM base b
)
SELECT *, count(*) OVER () AS total_count
FROM counted
WHERE (<filters>)
ORDER BY <sort> <dir>
LIMIT $n OFFSET $m;
```

Stats endpoints aggregate over the same `base` CTE, so a conversation cannot be `failed`
on one page and `in_progress` on another.

---

## 11. Performance

### 11.1 Now
22 conversations, 133 messages, 9 logs. Every query is a sub-millisecond seq scan.
Correlated subqueries in `STATUS_EXPR` are fine at this size.

### 11.2 Indexes — apply before volume grows

`migrations/032_dashboard_indexes.sql`, purely additive, safe to run any time:

```sql
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
  ON messages (conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_sent
  ON messages (conversation_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_chatbot_logs_conversation_created
  ON chatbot_logs (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chatbot_logs_level
  ON chatbot_logs (log_level) WHERE log_level IN ('error','fatal');
CREATE INDEX IF NOT EXISTS idx_conversations_flow_state
  ON conversations (flow_state);
CREATE INDEX IF NOT EXISTS idx_conversations_last_message_at
  ON conversations (last_message_at DESC);
```

`idx_messages_conversation_id` benefits the running bot too — `has_automation_outbound`,
`conversation_has_messages`, and `get_messages_for_conversation` all filter on it and none
has an index today (G7).

### 11.3 Beyond ~50k conversations
Rewrite the correlated subqueries in `STATUS_EXPR` as `LEFT JOIN LATERAL`, and materialise
`conversation_status` as a view refreshed on read. Not needed now; noted so the SQL is
written in a shape that permits it.

---

## 12. Phase 2 — payload capture (specced, NOT in this build)

Do not implement without separate approval. Every change here is additive; nothing
existing changes behaviour.

### 12.1 Populate `from_state` / `to_state`
The columns already exist and are always null (G4). Passing them at the ~6
`_escalate_human_needed` / `write_log` call sites makes §4.5's origin-state
reconstruction exact and removes the lookup table. Smallest change with the largest
accuracy gain.

### 12.2 Payload columns
```sql
-- migrations/033_dashboard_log_payloads.sql
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS request_payload  jsonb;
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS response_payload jsonb;
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS source           text;
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS target           text;
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS duration_ms      integer;
```
`ChatbotLog` gains five optional fields; `write_log` gains five defaulted params. Existing
callers are unaffected. `payload.available` in §5.5 flips to `true` automatically.

### 12.3 Persisted trace events
A `trace_events` table plus an optional DB sink in `TraceHub.emit`, gated on
`LIVE_TRACE_PERSIST=true`. This captures the rich `detail` dicts the diagnostics stream
already produces — including the LLM classifier calls and the unhandled exceptions that
are currently invisible in the DB (G6). Needs a retention policy (30-day rolling delete)
before it is switched on in production.

### 12.4 Exception logging
`chatwoot.py:858`'s `except Exception` handler currently emits a trace event only. Adding a
`write_log(... log_level='fatal', internal_class='unhandled_exception' ...)` alongside it
would make crash-driven failures visible to §4.1 rather than leaving them as stalls.

---

## 13. Testing

### 13.1 Derivation unit tests — `tests/dashboard/test_derive.py`
Pure functions, no DB. `failure_signature()` against all 12 known explanation strings plus
UUID/quote/integer interpolation cases; `origin_flow_state()` coverage of the lookup;
Turkish normalisation (`İstanbul` / `istanbul` / `ISTANBUL` collapse to one group);
`build_slices()` top-6 folding, the single-leftover rule, and the rounding residue rule.

### 13.2 SQL tests — `tests/dashboard/test_status_sql.py`
Fixture rows exercising every branch of `STATUS_EXPR` in order, including the precedence
cases: an errored-then-escalated conversation must be `human_needed`, not `failed`; an
`outbound_first` abstain must be `human_interruption`, not `not_run`; a `prior_history`
abstain must be `not_run`; a conversation exactly at the stale boundary must not flip.

### 13.3 API tests — `tests/dashboard/test_api.py`
FastAPI `TestClient`: auth 401/503 paths, filter and pagination correctness, 404s, and the
invariant that `counts` sums to `total_conversations` and `denominator = total − not_run`.

### 13.4 Route-preservation test — `tests/dashboard/test_routes_preserved.py`
Asserts `/diagnostics`, `/diagnostics/flow`, `/diagnostics/api/stats`, `/health`, and the
webhook routes still resolve to their original handlers after `mount_dashboard(app)`, and
that the SPA catch-all returns 404 (not `index.html`) for `/webhooks/unknown`. This is the
guard on the one edit to existing code.

### 13.5 Build freshness — CI
Fails if `dashboard/dist` is older than any file in `dashboard/web/src`.

### 13.6 Frontend
Vitest + Testing Library on the panel state machine (back-arrow visibility per parent),
the bubble-mapping table, and URL ↔ filter/panel round-tripping.

---

## 14. Implementation order

| Step | Deliverable | Verification |
|---|---|---|
| 1 | `dashboard/api/sql.py` + `derive.py` + tests | §13.1, §13.2 green |
| 2 | `queries.py`, `schemas.py`, `router.py`, `auth.py` | §13.3 green; endpoints return real data via curl |
| 3 | `static.py` + `main.py` mount | §13.4 green; `/diagnostics` verified by hand |
| 4 | Vite scaffold, `AppShell`, `LeftNav`, routing, `RightPanel` | nav collapse, panel open/close/back, URL sync |
| 5 | `ConversationTable`, `StatusChip`, `StatusLegend`, filters | `/infogatherer/conversations` fully usable |
| 6 | `LogTable`, `LogDetail`, both panel modes | Logs panel + Details + back arrow |
| 7 | `Transcript`, `MessageBubble`, `FlowMarker` | transcript against conversation 1704, which has a real takeover at 21:35 |
| 8 | `StatCard`, `RankedPie`, `TriggerTable`, `FullMessageModal` | statistics page |
| 9 | `/infogatherer` overview, empty/error states, a11y pass | screenshot review at 1280px and 1600px |
| 10 | `migrations/032_dashboard_indexes.sql`, README, CI check | migration applied, build documented |

Steps 1–3 are shippable on their own (a working API with no UI). Step 7 is the highest-risk
piece — the clock-mixing rule in §5.5/§5.6 is easy to get wrong and produces
plausible-looking but misordered transcripts.

---

## 15. Assumptions made where the spec was silent

Each is cheap to reverse; none is buried.

1. **`/infogatherer` gets an overview page** rather than redirecting to Conversations
   (§8.1) — the route was listed explicitly, so it should render something.
2. **A sixth `not_run` class exists** for `prior_history` abstains and is excluded from
   percentage denominators (§4.1). The alternative — counting the bot's correct refusal to
   barge into a pre-existing thread as a failure — would put 27% of current rows in the red
   card.
3. **"Successful until interruption" means clean interruptions** — interrupted with no
   prior error (§5.8). The dirty count is shown alongside so the definition is auditable.
4. **Both buttons open the right panel** (§8.2), rather than "Conversation" opening a
   full-width page. The panel is widened and drag-resizable to compensate.
5. **Purple and blue flow markers** exist in the transcript alongside the specified red one
   (§6.4).
6. **Filters, search, sorting, pagination, and a status legend** were added to the tables
   (§8.2) — not requested, but the color coding is undocumented without a legend and the
   tables don't scale without filters.
7. **Pies use a rank-ordered sequential ramp, not categorical colors** (§6.5). This is the
   one place the design deviates from a naive reading of "pie chart", and it is forced:
   the validator shows no 4+ slot categorical palette clears the colorblind floors for this
   form. The charts are still pies.
8. **Private notes are shown** in the transcript with a toggle to hide (§6.3), since
   Chatwoot shows them and the spec asks for the Chatwoot view.
9. **Dark mode only** — the transcript is specified black, and a validated second palette
   buys nothing here.
10. **Polling, not streaming** (§9). `/diagnostics` already owns the real-time view.
