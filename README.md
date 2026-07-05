# Univotel Chatbot

Automated WhatsApp lead handling for Univotel's student housing sales team. The bot receives leads through **Chatwoot**, runs a scripted conversation flow to identify university and gender, recommends the best matching dorm/hotel, sends canned property information, and (in V1) uses **Gemini** to assign Chatwoot labels and attributes. Anything outside the scripted path escalates to a human.

This README is the primary onboarding document for engineers new to the project. Detailed specs live in [`docs/`](docs/); this file synthesizes architecture, rules, data model, and operational guidance from those specs and the current codebase.

---

## Table of Contents

1. [What This System Does](#what-this-system-does)
2. [Tech Stack](#tech-stack)
3. [Architecture Overview](#architecture-overview)
4. [Quick Start](#quick-start)
5. [Environment Variables](#environment-variables)
6. [Project Structure](#project-structure)
7. [HTTP API & Webhooks](#http-api--webhooks)
8. [Layer 1: InfoGatherer](#layer-1-infogatherer)
9. [Layer 2: RecEngine](#layer-2-recengine)
10. [University Matching](#university-matching)
11. [Layer 3: TagAssigner (V1)](#layer-3-tagassigner-v1)
12. [Layer 4: FallBack (V2 — deferred)](#layer-4-fallback-v2--deferred)
13. [Database](#database)
14. [Migrations](#migrations)
15. [Background Jobs & Schedules](#background-jobs--schedules)
16. [Security](#security)
17. [Chatwoot Integration](#chatwoot-integration)
18. [Testing](#testing)
19. [Deployment](#deployment)
20. [Production Readiness](#production-readiness)
21. [Known Issues & Open Decisions](#known-issues--open-decisions)
22. [Documentation Index](#documentation-index)

---

## What This System Does

### Business problem

Univotel's Chatwoot inbox receives high-volume, repetitive leads: a student messages from a pre-filled website link, a salesperson asks university and gender, looks up a matching property, and pastes canned responses. This is scriptable work with no real judgment in the common case.

### What the bot automates

| Step | Automated by |
|------|--------------|
| Detect valid lead opener | InfoGatherer phrase gate |
| Match university (with typo/alias tolerance) | `matching.py` |
| Ask for campus when parent alias is ambiguous | InfoGatherer campus escalation |
| Ask for gender | InfoGatherer |
| Select best hotel for gender + university | RecEngine |
| Send ordered canned property messages | InfoGatherer + `response_schemas` |
| Assign CRM labels and attributes from chat | TagAssigner (Gemini) |
| Hand off edge cases | `human_needed` escalation (FallBack in V2) |

### What it deliberately does **not** do

- General conversation or free-text intent routing (deferred to FallBack V2)
- Post-completion "show me something else" without naming a hotel
- Sales-action labels (`aranacak`, `arandi`, etc.) — not chat-observable until V2
- Data deletion (KVKK: indefinite retention by policy)

### The four layers

| Layer | Module(s) | Status | Role |
|-------|-----------|--------|------|
| **InfoGatherer** | `app/layers/info_gatherer.py` | Production | Scripted state machine: phrase gate → university → gender → trigger RecEngine → send canned responses |
| **RecEngine** | `app/layers/rec_engine.py` | Production | Filter hotels by gender + university; tie-break by `priority_score` |
| **TagAssigner** | `app/tagassigner/*` | Production (V1) | Gemini proposes labels; router resolves conflicts and writes labels + attributes |
| **FallBack** | Not implemented | Deferred (V2) | LLM recovery for off-script cases; today → `human_needed` |

Until FallBack exists, every "call FallBack" in specs means **set `flow_state = human_needed`** and stop automated processing.

---

## Tech Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| Language | Python 3 (async) | |
| Web framework | FastAPI 0.115.5 | Entry: `app/main.py` |
| ASGI server | Uvicorn 0.32.1 | `Procfile`: binds `$PORT` |
| Database | PostgreSQL on **Supabase** | `asyncpg` pool (min 2, max 10) |
| ORM | None | Raw parameterized SQL in `app/db/queries.py` |
| Models | Pydantic `BaseModel` | DTOs in `app/db/models.py` |
| HTTP client | httpx | Chatwoot API, internal callbacks |
| Fuzzy matching | rapidfuzz | Levenshtein distance ≤ 2 |
| LLM | Google Gemini | Default: `gemini-2.5-flash-lite` via `google-genai` |
| Batch results | Google Cloud Storage | JSONL fetch from `gs://` URIs |
| Messaging CRM | Chatwoot | Webhooks in, REST API out |
| Testing | pytest (asyncio auto) | Integration tests excluded by default |
| Deployment | **Railway** (Hobby tier) | Single always-on web process |

### Why Railway, not serverless

The core pattern is **async request-reply**: webhook handlers return `200` immediately and detach work to background tasks (retry ladders, sweeps, queue drain). Serverless platforms tear down compute after the response, killing this pattern. Railway runs a persistent process so detached `asyncio` tasks behave as designed.

---

## Architecture Overview

### End-to-end lead flow

```
Student WhatsApp message
  → Chatwoot
  → POST /webhooks/chatwoot (HMAC verify, dedupe, upsert conversation)
  → InfoGatherer state machine (background)
      → matching.py (university)
      → canned responses OR campus question OR gender prompt
  → RecEngine (gender + university → hotel)
      → POST /internal/infogatherer/callback
      → send hotel canned responses + write Chatwoot attributes
  → [parallel] TagAssigner idle scan / manual "tag" / nightly batch
      → Gemini proposes labels
      → label_resolver + attribute_resolver
      → Chatwoot label + attribute writeback
```

### Core design patterns

| Pattern | Where | Why |
|---------|-------|-----|
| Async request-reply | All webhooks | Chatwoot timeout/redelivery safety |
| State machine + optimistic locking | InfoGatherer | Prevent race on concurrent messages |
| Idempotency keys | RecEngine, batch webhooks | Safe retries without duplicate work |
| Retry ladder | RecEngine (5s×3), send (1s/2s/4s), Gemini 429 | Resilience without infinite loops |
| Router/broker | TagAssigner `router.py` | Gemini never touches DB or Chatwoot directly |
| Pure function pipelines | `matching.py`, `label_resolver.py`, `conflict.py` | Unit-testable business logic |
| Durable Postgres queue | `tag_assigner_queue` | Survives Railway restarts |
| Feedback-loop guard | `record_self_write` + bot agent check | Prevent webhook loops from bot writes |
| Fail-fast integrity check | Boot + daily sweep | Catch misconfigured data before serving traffic |
| In-process scheduled sweeps | All background jobs | No external cron on Railway Hobby |

### Sync topology (TagAssigner)

```
                    ┌─────────────┐
   writes  ───────► │   CHATWOOT  │ ◄─────── writes (humans, CRM)
   (Router only)    │  (truth)    │
                    └──────┬──────┘
                           │ webhook (only sync direction)
                           ▼
                    ┌─────────────┐
                    │  CHATBOT DB │  (downstream replica)
                    └─────────────┘
```

- **Chatwoot is the single source of truth** for labels and custom attributes.
- **ChatBot DB is strictly downstream** — synced via webhooks; TagAssigner reads labels **live from Chatwoot** at run start (not from DB replica).
- **The TagAssigner router is the only path** by which the ChatBot system writes to Chatwoot.

---

## Quick Start

### Prerequisites

- Python 3.11+ recommended
- Access to the Supabase **ChatBot** database (not just the main Univotel website DB)
- Chatwoot account with webhook + API token configured
- For TagAssigner: Gemini API key with billing enabled

### Local setup

```bash
# 1. Clone and enter the repo
cd "Univotel Chatbot"

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with real values (see Environment Variables below)

# 5. Apply migrations (manual — see Migrations section)
# Run migrations/001 through migrations/014 in order via Supabase SQL editor.
# Also apply external seed files referenced in docs (parent universities, label maps).

# 6. Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. Verify health
curl http://localhost:8000/health
# → {"status":"ok"}
```

### First-run checklist

- [ ] `DATABASE_URL` points to the ChatBot Supabase project
- [ ] Migrations 001–014 applied; migrations 013 and 014 confirmed on production-like DB
- [ ] `INTEGRITY_CHECK_BYPASS=false` for a real boot test (app should start cleanly)
- [ ] `TESTING_LIMITATIONS_MODE=true` until production sign-off
- [ ] Chatwoot webhook URL points to your deployment's `/webhooks/chatwoot`
- [ ] Test phone numbers are on the allowlist when testing mode is on

### Running tests

```bash
# Unit tests only (default — integration tests excluded)
pytest

# Include integration tests (requires live DATABASE_URL)
pytest -m integration

# Run a specific module
pytest tests/test_matching.py -v
```

---

## Environment Variables

Copy `.env.example` to `.env`. All secrets live in environment variables only — never commit them.

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql://...`) |
| `CHATWOOT_BASE_URL` | Yes | Chatwoot instance URL |
| `CHATWOOT_API_TOKEN` | Yes | API access token for outbound calls |
| `CHATWOOT_ACCOUNT_ID` | Yes | Numeric account ID |
| `CHATWOOT_WEBHOOK_SECRET` | Yes | HMAC secret for inbound webhook verification |
| `CHATWOOT_BOT_AGENT_ID` | Yes | Numeric ID of the `ChatBot` agent (human-takeover detection) |
| `INTERNAL_SHARED_SECRET` | Yes | Shared secret for `/internal/*` routes |
| `GEMINI_API_KEY` | TagAssigner | Google Gemini API key |
| `MODEL_ID` | No | Default: `gemini-2.5-flash-lite` — keep as env constant, never hardcode |
| `GEMINI_WEBHOOK_SECRET` | Batch | Base64-encoded symmetric secret for batch webhook verification |
| `TAGASSIGNER_AUTO_RUNS` | No | `true`/`false` — idle scan + nightly batch (manual `tag` always works) |
| `LOG_LEVEL` | No | Default: `info` |
| `TESTING_LIMITATIONS_MODE` | No | When `true`, only process two allowlisted phone numbers |
| `INTEGRITY_CHECK_BYPASS` | No | When `true`, skip fatal boot integrity check |

### Testing mode allowlist

When `TESTING_LIMITATIONS_MODE=true`, only these phone numbers (digits only) are processed:

- `905551839644`
- `905445545244`

All other contacts are silently ignored — no DB writes, no messages. Defined in `app/config.py` as `TESTING_PHONE_ALLOWLIST`. TagAssigner is also gated by this allowlist.

### TagAssigner attribute keys

Configured in `app/config.py` as `TAGASSIGNER_ATTRIBUTE_KEYS` — sent to Gemini as read-only context:

- `ilgili_otel`
- `tasinma_tarihi`
- `kayip_nedeni`
- `oda_tiipi` (must match live Chatwoot key exactly — double-i)
- `butce`

---

## Project Structure

```
Univotel Chatbot/
├── app/
│   ├── main.py                      # FastAPI app, lifespan, route registration, background tasks
│   ├── config.py                    # Settings, allowlist, attribute keys, logging
│   ├── security.py                  # HMAC (Chatwoot), internal secret, Standard Webhooks
│   ├── chatwoot_client.py           # Outbound Chatwoot REST API wrapper
│   ├── db/
│   │   ├── client.py                # asyncpg connection pool
│   │   ├── models.py                # Pydantic DTOs mirroring tables
│   │   └── queries.py               # All SQL access (~1040 lines — single data layer)
│   ├── webhooks/
│   │   ├── chatwoot.py              # POST /webhooks/chatwoot — primary inbound entry
│   │   ├── internal.py              # RecEngine start + InfoGatherer callback
│   │   └── batch_results.py         # POST /webhooks/batch-results — Gemini batch callback
│   ├── layers/
│   │   ├── info_gatherer.py         # ContextRun state machine
│   │   ├── phrase_gate.py           # First-message gate (7 filters + pre-conditions A/B)
│   │   ├── rec_engine.py            # Hotel selection by gender + university
│   │   └── matching.py              # University matching (exact → alias → Levenshtein)
│   ├── background/
│   │   ├── rec_engine_ladder.py     # 3×5s retry ladder for RecEngine
│   │   ├── send_retry.py            # Chatwoot send retry (1s/2s/4s backoff)
│   │   └── reprompt_sweep.py        # 3-hour reprompt ladder
│   ├── health/
│   │   └── integrity_check.py       # Boot-time + daily referential integrity sweep
│   └── tagassigner/
│       ├── router.py                # Script Router — all I/O brokering (not HTTP)
│       ├── trigger.py               # Idle scan, midnight reset, nightly batch sweeps
│       ├── queue.py                 # Durable Postgres queue drain worker
│       ├── gemini_client.py         # Live Gemini API calls
│       ├── batch_client.py          # Nightly Gemini Batch API + GCS fetch
│       ├── payload_builder.py       # Builds Gemini prompt payload
│       ├── label_resolver.py        # 4-list taxonomy enforcement
│       ├── attribute_resolver.py    # Deterministic Chatwoot attribute writes
│       └── conflict.py              # Option-A timestamp conflict rule for ilgili_otel
├── migrations/                      # 14 SQL migrations (001–014), applied manually
├── tests/                           # Unit tests (8 modules + conftest)
├── docs/                            # Specs, audits, test plans, SQL audit scripts
├── system_prompts/
│   └── tagassigner_prompt.md        # Gemini system prompt for TagAssigner
├── scripts/
│   └── testclean.py                 # Test conversation cleanup utility
├── requirements.txt
├── Procfile                         # Railway: uvicorn app.main:app
├── pytest.ini
└── .env.example
```

### Key files to read first

| File | Why |
|------|-----|
| `app/main.py` | App entry, lifespan, all background task startup |
| `app/layers/info_gatherer.py` | Core business logic — state machine |
| `app/layers/phrase_gate.py` | First-inbound phrase gate — 7 filters + pre-conditions |
| `app/db/queries.py` | Every database operation |
| `app/webhooks/chatwoot.py` | Inbound message handling, dedupe, testing gate |
| `app/tagassigner/router.py` | TagAssigner pipeline orchestration |
| `docs/univotel-chatbot-spec.md` | V0 master spec |
| `docs/chatbot-phrase-gate-and-matching-spec.md` | Phrase gate, clarification, matching spec |
| `docs/matching-fixes-impl-spec.md` | Pending matching/clarification fixes (F6, F8) |
| `docs/tagassigner-v1-spec.md` | V1 TagAssigner spec |
| `docs/v1-audit.md` | Production readiness audit |

---

## HTTP API & Webhooks

### Application endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/health` | None | Liveness probe → `{"status":"ok"}` |
| `POST` | `/webhooks/chatwoot` | Chatwoot HMAC | Inbound Chatwoot events |
| `POST` | `/internal/recengine/start` | `X-Internal-Secret` | InfoGatherer triggers RecEngine |
| `POST` | `/internal/infogatherer/callback` | `X-Internal-Secret` | RecEngine completion callback |
| `POST` | `/webhooks/batch-results` | Standard Webhooks | Gemini `batch.succeeded` notification |

FastAPI also exposes `/docs`, `/redoc`, `/openapi.json` automatically.

### Chatwoot webhook behavior (`POST /webhooks/chatwoot`)

1. Verify HMAC (`X-Chatwoot-Signature` over `timestamp.body`) — failure → `401`
2. Return `200` immediately; process in `BackgroundTasks`
3. Dedupe on `chatwoot_message_id`
4. Upsert conversation on first sight
5. **Testing gate**: silently ignore non-allowlisted phones when testing mode is on

**Event: `message_created`**

- **Private note `"tag"`** → manual TagAssigner trigger (bypasses 5-message gate)
- **Outbound from human agent** (not bot) → `flow_state = stopped`
- **Inbound non-private** → store message → `info_gatherer.process_message()`

**Event: `conversation_updated`**

- Sync labels + custom attributes to DB (atomically update `_set_at`/`_set_by` companions)
- **Feedback-loop guard**: ignore bot-authored updates
- **`tag` label present** → manual TagAssigner trigger

### Internal RecEngine flow

```
InfoGatherer
  → POST /internal/recengine/start  {conversation_id, idempotency_key, university_id_override?, gender_override?}
    → asyncio.create_task(run_rec_engine)
      → DB hotel selection
      → POST /internal/infogatherer/callback  {conversation_id, hotel_rec, status}
        → send canned hotel responses
        → write_attributes_at_flow_completion (university, gender, ilgili_otel)
```

Internal calls loop through `http://localhost:{PORT}` with `X-Internal-Secret`. Default port: 8000.

---

## Layer 1: InfoGatherer

**Module:** `app/layers/info_gatherer.py` (phrase gate in `app/layers/phrase_gate.py`)

InfoGatherer is a **finite state machine** with optimistic locking via `update_conversation_state(expected_from_state)`. It does not attempt general conversation — every path terminates in `completed`, `human_needed`, `stopped`, or waits in an awaiting state.

### Flow states

| State | Meaning |
|-------|---------|
| `new` | First contact; phrase gate and university extraction |
| `awaiting_university` | Asked "hangi" — waiting for university name |
| `awaiting_university_clarification` | Ambiguous match — one clarification round |
| `awaiting_campus_clarification` | Parent alias matched — waiting for campus choice |
| `awaiting_gender` | University known — waiting for gender |
| `recengine_running` | RecEngine triggered — waiting for callback |
| `completed` | Hotel responses sent successfully |
| `human_needed` | Escalated to human (no further bot action) |
| `stopped` | Human agent took over |

**Terminal states:** `completed`, `human_needed`, `stopped`. Inbound messages are still logged but the bot takes no automatic action, except: a `completed` conversation naming a **different specific hotel** re-enters the direct hotel-name path.

### ContextRun steps (state `new`)

**Step 1 — Phrase gate** (`app/layers/phrase_gate.py`). Evaluated on every inbound message in `new`; see [`docs/chatbot-phrase-gate-and-matching-spec.md`](docs/chatbot-phrase-gate-and-matching-spec.md) for the full spec.

| Outcome | Behavior |
|---------|----------|
| **Pre-condition B — hotel match** | N-gram scan against `hotels.name` (exact or Levenshtein ≤ 2) fires on **any** message, even mid-conversation → direct hotel path |
| **Pre-condition A — first inbound** | Keyword filters run only on the conversation's first inbound message (`queries.is_first_inbound_message`) |
| **`GREETING`** | At least one filter matched → continue ContextRun below |
| **`IGNORE`** | No filter matched on first inbound → log only, **no state change**, no Chatwoot message; conversation stays in `new` |
| **`HOTEL_PATH`** | Pre-condition B matched → `_fire_hotel_path` (schemas + attributes, no RecEngine) |

**First-inbound filters** (any one passes → `GREETING`):

1. **Widget templates** — fixed Chatwoot pre-fill strings (exact substring or Levenshtein ≤ 2 on full message), plus wildcard `"Merhaba!" … "yakınında öğrenci konaklaması"`
2. **Entity n-gram** — 1–4 word windows scanned via `scan_entities_by_ngram()` (longest match first)
3. **Greetings** — `merhaba`, `merhabalar`, `selam`, `iyi günler`, `hello`, etc.
4. **Housing intent** — `konaklama`, `yurt`, `oda`, `öğrenci oteli`, …
5. **Staj/dönem** — `staj`, `yaz dönemi`, `güz dönemi`, …
6. **Proximity** — `yakınında`, `üniversiteme yakın`, `en yakın`, …
7. **Price/info** — at least 2 of `{fiyat, bilgi, icin}` in normalized text

**Step 2 — Direct hotel-name match (fallback).** If phrase gate did not already fire the hotel path, `match_hotel_by_ngram()` scans 1–4 word n-grams against `hotels.name` → send that hotel's `response_schemas`, state → `completed`. No gender/university, no RecEngine.

**Step 3 — `Üniversitem:` line match.** Search that line ±1 line for university match. Match → set `university_id`, proceed to gender or `deal_awaiting` check.

**Step 4 — Keyword-based match.** Search for `Üniversitesi`, `Üni`, `uni`, etc.; run matching on same line ±1 line.

**Step 5 — Direct ask.** Send canned `hangi`, state → `awaiting_university`.

**Ambiguous match (Levenshtein tie):** Send `clarify_uni` canned ("Tam ismi neydi efendim üniversitenizin, kısaltmadan çıkaramadım?"), state → `awaiting_university_clarification`. One clarification round — still ambiguous or no-match → silent `human_needed`.

**Campus escalation:** Parent-level alias (e.g. `"itü"`, `"bau"`) → ask campus question from `parent_universities.question` template, state → `awaiting_campus_clarification`. If the parent has **only one campus**, skip the question and resolve directly.

**Step 6 — Gender ask.** Send `kiz-erkek`, state → `awaiting_gender`. Gender may be extracted from the opening message and written to DB early, but the gender prompt is **always sent** after university resolution.

| Reply contains | Gender |
|----------------|--------|
| `kiz`, `kız`, `bayan`, `kadın` | `female` |
| `bay`, `erkek`, `oğlan` | `male` |
| No match | `human_needed` |

Once `university_id` and `gender` are confirmed → fire RecEngine (state → `recengine_running`).

### Invalid input handling (`awaiting_university`, `awaiting_university_clarification`, `awaiting_campus_clarification`)

Requires migration **014** (`clarification_attempt` column + `clarify_*` canned responses).

**University not matched** (`awaiting_university` or `awaiting_university_clarification`):

| Attempt | Behavior |
|---------|----------|
| First | Send `clarify_uni_name`, increment `clarification_attempt`. If input is **> 2 words** after normalize, also advance to `awaiting_university_clarification`. If **≤ 2 words**, stay in `awaiting_university`. |
| Second (`clarification_attempt >= 1`, or any failure in `awaiting_university_clarification`) | Silent `_escalate_human_needed()` — DB write only, no Chatwoot message |

**Levenshtein ambiguous tie** (any step): Send `clarify_uni`, state → `awaiting_university_clarification`. Second failure in that state → silent `human_needed`.

**Campus not matched** (`awaiting_campus_clarification`):

| Attempt | Behavior |
|---------|----------|
| First | Send `clarify_campus_name`, increment `clarification_attempt`, stay in `awaiting_campus_clarification` |
| Second (`clarification_attempt >= 1`) | Silent `_escalate_human_needed()` — DB write only, no Chatwoot message |

`clarification_attempt` resets on any successful university or campus match. Campus matching compares `campus_label` and campus-scoped aliases from `university_aliases` (e.g. `taşkışla` → İTÜ Maçka during campus clarification).

**Gender not matched** (`awaiting_gender`): Silent `human_needed`.

### `deal_awaiting` path (V0 amendment)

After a successful university match, **before** RecEngine:

```
university matched
  → is university_id in deal_awaiting_universities?
      → YES: set deal_awaiting label + send DEAL-AWAITING-STATE canned response → terminal
      → NO:  proceed to gender → RecEngine
```

| Outcome | Meaning | When |
|---------|---------|------|
| `GLOBAL-NULL-STATE` | No hotel for this gender/university profile | After RecEngine, 0 candidates |
| `DEAL-AWAITING-STATE` | University not served yet (inventory gap) | Before RecEngine, membership check |

Sentinel hotel UUIDs:
- `00000000-0000-0000-0000-000000000001` — GLOBAL-NULL-STATE
- `00000000-0000-0000-0000-000000000002` — DEAL-AWAITING-STATE

### Canned response resolution

**One path for all hotel outcomes:**

```
hotel_id determined
  → SELECT response_id FROM response_schemas WHERE hotel_id = :id ORDER BY sending_order
  → for each: send canned_responses.content via Chatwoot
  → zero rows: log fatal, human_needed
```

No string templating of short codes. Direct hotel match, RecEngine result, and sentinel hotels all use this path.

### Reprompt ladder (abandonment)

Every 3 hours (`reprompt_sweep.py`), for conversations waiting on a lead reply:

| Hours since last contact | Action |
|--------------------------|--------|
| 3h | Send "Efendim?" |
| 6h | Send "Orada mısınız?" |
| 9h | Send "Müsait olduğunuzda dönüşünüzü bekliyorum efendim." |
| Beyond | Nothing — no tag, no terminal state |

Tracked via `reprompt_count` and `last_reprompt_sent_at`.

### Human takeover

Outbound message where `sender_id ≠ CHATWOOT_BOT_AGENT_ID` → `flow_state = stopped`. No further bot action.

### Optimistic concurrency

```sql
UPDATE conversations SET flow_state = :new_state
  WHERE id = :id AND flow_state = :expected_state
-- rows_affected == 0 → another webhook won the race; log and stop
```

---

## Layer 2: RecEngine

**Module:** `app/layers/rec_engine.py`

Triggered by InfoGatherer after gender capture. Selects the best hotel for the lead's university and gender. The internal start endpoint also accepts optional `university_id_override` and `gender_override` for runtime parameter overrides (see `app/webhooks/internal.py`).

### Selection algorithm

```
1. gender_matches = hotels WHERE gender_scope IN (:gender, 'mixed') AND is_visible
2. university_matches = hotel_accessible_universities WHERE university_id = :id
3. candidates = intersection by hotel_id
4. len == 0 → GLOBAL-NULL-STATE (200 NOT FOUND)
5. len == 1 → that hotel (200 FOUND)
6. len > 1  → highest priority_score (200 FOUND)
7. abort before definitive result → 502
```

`priority_score` is the manually-tunable lever for capacity, quality, and business preference. Lower it to deprioritize without removing eligibility.

### Idempotency

On receipt, RecEngine writes a `processing` row to `rec_engine_logs` keyed on `idempotency_key` **before** query work. Retries with the same key find the row and no-op.

### Retry ladder

InfoGatherer fires RecEngine via `rec_engine_ladder.py`:

```
fire (idempotency_key generated once)
  → wait 5s → check rec_engine_logs
    → not found → fire again (same key)
      → wait 5s → check again
        → not found → fire again (same key)
          → wait 5s → check again
            → not found → human_needed
```

### Stale hotel reference

If resolved `hotel_id` no longer exists in `hotels`, RecEngine reruns selection **once**. Second failure → `human_needed`.

---

## University Matching

**Module:** `app/layers/matching.py`

Pure function pipeline used by InfoGatherer and phrase gate. Fully unit-tested.

### Algorithm

```
normalize(text)     # lowercase, strip Turkish diacritics, strip university suffixes
  → parent alias check FIRST (e.g. "itü" → parent_university_id for campus escalation)
  → Tier 1: exact match on universities.name / university_short_name
  → Tier 2: campus-level alias lookup (university_aliases)
  → Tier 3: Levenshtein distance ≤ 2 (rapidfuzz)
      → exactly one hit: done
      → multiple equidistant hits: AMBIGUOUS → one clarification round
      → zero hits: NONE → out-of-Istanbul or human_needed depending on context
```

**Parent alias hoisting:** Parent-level aliases (e.g. `"itü"`) are checked **before** Tier 1 exact match. This prevents a campus `short_name` collision from skipping campus escalation.

**Levenshtein cutoff:** Length-based via `_get_levenshtein_cutoff()` — ≤3 chars: 0 (Tier 3 disabled); 4–5 chars: 1; ≥6 chars: 2. Prevents short-input false positives (e.g. `"TÖÜ"` → `"tou"` no longer fuzzy-matches Koç `"ku"`). `LEVENSHTEIN_CUTOFF = 2` remains as a legacy reference for `phrase_gate.py` widget matching.

**N-gram helpers:** `tokenize()`, `scan_ngrams()`, `scan_entities_by_ngram()`, `match_hotel_by_ngram()`, and `word_count_after_normalize()` support phrase-gate entity detection, hotel-name paths, and invalid-input word-count logic.

**Empty input:** Whitespace-only after normalization = no-match (same as zero hits).

---

## Layer 3: TagAssigner (V1)

**Modules:** `app/tagassigner/*`

TagAssigner reads conversations and assigns Chatwoot labels. It uses a **three-layer split**:

1. **Database** — conversation state, message history
2. **Script Router** (`router.py`) — all I/O brokering
3. **Gemini** — classification only; never touches DB or Chatwoot

**Gemini's entire output surface is labels.** Custom attributes are written deterministically by the Router.

### Router pipeline (`run_tagging`)

```
1. Read current labels LIVE from Chatwoot (not DB replica)
2. Fetch messages (full history for manual/scheduled; since-last-run for message trigger)
3. payload_builder.build_payload → gemini_client.call_gemini
4. label_resolver.resolve_labels (4-list taxonomy)
5. Write labels to Chatwoot (full-set replace) with retry + record_self_write
6. attribute_resolver.resolve_and_write_attributes
7. Reset message counter; mark run success
```

### Deterministic attribute writes (Router, not Gemini)

| Attribute | Source |
|-----------|--------|
| `university` | `universities.name` from InfoGatherer's `university_id` |
| `ogrenci_cinsiyet` | `male → Erkek`, `female → Kız`, unset → `Bilinmiyor` |
| `ilgili_otel` | `hotel_chatwoot_label_map` lookup from RecEngine hotel; Option A conflict rule |

InfoGatherer also writes these three attributes immediately at flow completion (`write_attributes_at_flow_completion` on RecEngine callback). TagAssigner maintains them on subsequent runs.

### Option A — timestamp conflict rule

For `ilgili_otel` (and conflict-managed fields like `ziyaret`):

> TagAssigner may change the value **only if** chat evidence is timestamped **strictly newer** than `<field>_set_at`. Otherwise the existing value stands.

Requires `ilgili_otel_set_at` and `ilgili_otel_set_by` (`tagAssigner` / `human` / `crm`) updated **atomically with the value from any source**, including human/CRM changes via webhook.

### Trigger conditions

**Message-triggered run** (all must hold):

- ≥ 5 messages since last run (≥ 1 inbound)
- 15 minutes idle: `last_message_at < now() - 15 minutes` (NOT `last_updated_at`)
- Under daily automated cap (5/day)

**Manual `tag` trigger:**

- Private note `"tag"` OR label named `tag`
- Bypasses 5-message gate
- Separate cap: 5 manual runs/day
- Rejected if a run is already `processing`

**Nightly scheduled run (23:40 Istanbul / 20:40 UTC):**

- Submitted via Gemini Batch API (50% discount)
- Reads full message history
- Counts as 1 of the 5 automated runs

**Run caps reset** at Istanbul midnight (21:00 UTC) via `start_midnight_reset_sweep`.

### The four label lists

Enforced by `label_resolver.py` regardless of prompt content:

**LIST 1 — USABLE** (add and remove freely):

`pre-sinav`, `hazırlık`, `1-sinif`, `2-sinif`, `3-sinif`, `4-sinif`, `universitede`, `yerlesti`, `yeni-giris`, `erasmus`, `ogrenci`, `veli`, `ogrenci-degil`, `kyk-sonuc-bekliyor`, `ibb-yurdu-sonuc-bekliyor`, `universite-yurdu-sonuc-bekliyor`, `yatay_geçiş_bekliyor`, `univotelli`, `fiyat-soruyor`, `ilgilenmiyor`, `ziyaret`, `ziyaret-etti`, `ziyaret-etmedi`

**LIST 2 — ADD-ONLY / NEVER REMOVE** (hard Router guard):

`kapora-alindi`, `sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak`

**LIST 3 — NEVER TOUCH:**

- Source/channel (CRM-owned): `google-ads`, `google-maps`, `meta-ads`, `instagram`, `whatsapp`, `netgsm`, `sahibinden`, `manual`
- Sales-action (V2): `aranacak`, `arandi`, `arandi-acmadi`, `bizi-aradi-konustuk`

**LIST 4 — MUTUALLY-EXCLUSIVE GROUPS:**

| Group | Labels |
|-------|--------|
| Academic year | `pre-sinav` / `hazırlık` / `1-sinif` / `2-sinif` / `3-sinif` / `4-sinif` / `universitede` |
| Enrollment progression | `yerlesti` → `yeni-giris` (latest-wins) |
| Contact identity | `ogrenci` / `veli` / `ogrenci-degil` |
| Visit progression | `ziyaret` → `ziyaret-etti` / `ziyaret-etmedi` → `ziyaret-ama-almayacak` |
| Deal terminal | `sozlesme-imzalandi` / `kayıp` |

**ROUTER-COMPUTED** (never LLM-decided):

- `deal_awaiting` — set by InfoGatherer
- `university`, `ogrenci_cinsiyet`, `ilgili_otel` — written by Router

### Queue and throttle

All runs feed `tag_assigner_queue`. Worker drains at ~6 RPM with 429 backoff (5s / 30s / 120s). Durable table survives Railway restarts.

### Dual execution paths

| Path | When | Gemini call |
|------|------|-------------|
| Live | Daytime queue drain, manual `tag`, idle scan | `gemini_client.call_gemini` |
| Batch | Nightly 23:40 Istanbul | Batch API → GCS JSONL → `/webhooks/batch-results` |

**Note:** Batch submission in `batch_client.py` may be stubbed until GCP billing, GCS access, and public webhook URL are configured. Live tagging via queue drain is the day-one path.

### Feedback-loop guard

TagAssigner's own writes echo as `conversation_updated` webhooks. Without the guard, this would re-trigger runs in a loop.

1. **Primary:** If update author is `ChatBot` agent → ignore for triggering
2. **Fallback:** `record_self_write()` before each write; 30s in-memory TTL cross-check

`last_message_at` advances only on real message activity — never on label/attribute sync writes.

---

## Layer 4: FallBack (V2 — deferred)

LLM-based (Gemini 3 Flash planned) natural-language recovery. Every "call FallBack" in V0/V1 code and specs currently resolves to `human_needed`.

V2 will also unlock sales-action labels (`aranacak`, `arandi`, etc.) via NetGSM/CRM integration, and retire the `hotel_chatwoot_label_map` duplicate.

---

## Database

### Platform

- **PostgreSQL** on Supabase (ChatBot project)
- **asyncpg** connection pool — no ORM
- All SQL in `app/db/queries.py` (~1040 lines)
- Pydantic DTOs in `app/db/models.py`

### Table tiers

**Tier A — Pre-existing reference data** (from main Univotel website, must exist before migration 001):

| Table | Purpose |
|-------|---------|
| `hotels` | Properties; `gender_scope`, `priority_score` added in migration 002 |
| `universities` | Istanbul universities |
| `hotel_accessible_universities` | Junction: which hotels serve which universities |

**Tier B — Core chatbot** (migration 001+):

| Table | Purpose |
|-------|---------|
| `conversations` | Per-lead state machine, attributes, run counters |
| `messages` | All inbound/outbound messages; dedupe on `chatwoot_message_id` |
| `chatbot_logs` | Structured audit trail per layer |
| `rec_engine_logs` | Idempotent RecEngine run tracking |
| `canned_responses` | Message templates by `short_code` |
| `response_schemas` | Ordered message sequences per hotel |
| `university_aliases` | Normalized abbreviations for matching |

**Tier C — Deal-awaiting** (migration 006):

| Table | Purpose |
|-------|---------|
| `deal_awaiting_universities` | Universities not yet served |

**Tier D — TagAssigner** (migrations 007–010):

| Table | Purpose |
|-------|---------|
| `tag_assigner_runs` | Per-run idempotency + cached `gemini_result` |
| `tag_assigner_logs` | Per-request connection audit |
| `hotel_chatwoot_label_map` | `hotels.id` → exact Chatwoot `ilgili_otel` list value |
| `tag_assigner_queue` | Durable FIFO queue with dedupe |

**Tier E — Parent-university escalation** (migration 011+):

| Table | Purpose |
|-------|---------|
| `parent_universities` | Multi-campus parent entities + question template |
| `university_parent_map` | Campus → parent mapping with `campus_label` |
| `university_chatwoot_label_map` | `universities.id` → Chatwoot list value |

### Key `conversations` columns

| Column | Purpose |
|--------|---------|
| `flow_state` | InfoGatherer state machine position |
| `university_id`, `gender` | Captured lead profile |
| `contact_phone` | Testing mode filter |
| `last_message_at` | Idle trigger clock (separate from `last_updated_at`) |
| `messages_since_last_run` | TagAssigner 5-message gate |
| `auto_run_count`, `manual_run_count` | Daily run caps (reset at Istanbul midnight) |
| `ilgili_otel`, `ilgili_otel_set_at`, `ilgili_otel_set_by` | Conflict-managed attribute |
| `tasinma_tarihi`, `kayip_nedeni`, `oda_tiipi`, `butce` | Manual attributes (Gemini context) |
| `pending_parent_university_id` | Campus escalation in progress |
| `clarification_attempt` | Invalid campus reply retry counter (migration 014; reset on successful match) |
| `reprompt_count`, `last_reprompt_sent_at` | Abandonment ladder |

### Entity relationships (simplified)

```
hotels ←→ hotel_accessible_universities ←→ universities
hotels → response_schemas → canned_responses
hotels → hotel_chatwoot_label_map

universities → university_parent_map → parent_universities
universities → university_aliases
universities → deal_awaiting_universities

conversations → messages, rec_engine_logs, tag_assigner_runs, tag_assigner_queue
```

---

## Migrations

Migrations live in `migrations/` (001–014). **There is no automated migration runner** — apply manually via the Supabase SQL editor. Write migrations idempotently (`IF NOT EXISTS`) where possible.

| # | File | Changes |
|---|------|---------|
| 001 | `001_create_core_tables.sql` | Core chatbot tables |
| 002 | `002_alter_hotels_add_gender_and_priority.sql` | `gender_scope`, `priority_score` on hotels |
| 003 | `003_insert_global_null_state.sql` | GLOBAL-NULL-STATE sentinel + `henuz` wiring |
| 004 | `004_create_university_aliases.sql` | Alias table (redundant on fresh DB) |
| 005 | `005_add_contact_phone_to_conversations.sql` | `contact_phone` for testing filter |
| 006 | `006_deal_awaiting.sql` | `deal_awaiting_universities` + DEAL-AWAITING-STATE sentinel |
| 007 | `007_tagassigner_runs_and_logs.sql` | TagAssigner run tracking |
| 008 | `008_conversations_columns.sql` | `last_message_at`, run counters, attribute columns |
| 009 | `009_hotel_chatwoot_label_map.sql` | Hotel → Chatwoot label mapping |
| 010 | `010_tag_assigner_queue.sql` | Durable queue |
| 011 | `011_parent_university_escalation.sql` | Parent universities, campus maps, label maps |
| 012 | `012_fix3_orphan_universities.sql` | Data fix: Doğuş Kadıköy, Arel cleanup |
| 013 | `013_escalation_schema_fixes.sql` | `awaiting_campus_clarification` in CHECK; missed 011 fixes |
| 014 | `014_phrase_gate_and_clarification.sql` | `clarification_attempt` column; `clarify_*` canned responses |

### External seed files (referenced, may not be in repo)

Apply separately in Supabase:

- `hotels_rows.sql`, `universities_rows-2.sql`, `hotel_accessible_universities_rows.sql` — base reference data
- `session_migration.sql` — `parent_universities` + `university_parent_map`
- `university_map_seed.sql` — 92 `university_chatwoot_label_map` rows

### Pre-flight before RecEngine

- Migration 002 applied **and** every hotel's `gender_scope` manually verified
- Migration 003 applied (GLOBAL-NULL-STATE exists and is wired)
- Migration 006 applied (DEAL-AWAITING-STATE exists and is wired)
- Migration 013 applied on production (confirms `awaiting_campus_clarification` constraint)
- Migration 014 applied (`clarification_attempt` column; `clarify_uni`, `clarify_uni_name`, `clarify_campus_name` canned responses)

---

## Background Jobs & Schedules

All started in `lifespan()` in `app/main.py` as `asyncio.create_task` loops.

| Worker | Schedule | Module | Purpose |
|--------|----------|--------|---------|
| Reprompt sweep | Every 3h | `background/reprompt_sweep.py` | Abandonment ladder |
| Daily integrity sweep | Every 24h | `health/integrity_check.py` | Referential integrity |
| Queue drain | Every 10s | `tagassigner/queue.py` | Process `tag_assigner_queue` |
| Idle scan | Every ~90s | `tagassigner/trigger.py` | Enqueue 5-msg / 15-min idle conversations |
| Midnight reset | 21:00 UTC daily | `tagassigner/trigger.py` | Reset `auto_run_count` / `manual_run_count` |
| Nightly batch | 20:40 UTC daily | `tagassigner/trigger.py` | Submit Gemini Batch API job (23:40 Istanbul) |

On-demand (not scheduled):

| Worker | Trigger | Module |
|--------|---------|--------|
| RecEngine ladder | Gender captured | `background/rec_engine_ladder.py` |
| Send retry | Every Chatwoot outbound | `background/send_retry.py` |

---

## Security

**Model:** Shared-secret verification at every trust boundary, with loud failure. No rate limiting or IP allowlisting (avoids false-positive cost on genuine Chatwoot traffic).

### 1. Chatwoot webhook HMAC

```
HMAC-SHA256(CHATWOOT_WEBHOOK_SECRET, timestamp + "." + raw_body)
```

Headers: `X-Chatwoot-Signature` (`sha256={hex}`), `X-Chatwoot-Timestamp`

Mismatch or missing → `401`, logged fatal, dropped before parsing.

### 2. Internal shared secret

Header: `X-Internal-Secret` — constant-time compare against `INTERNAL_SHARED_SECRET`.

Used by `/internal/recengine/start` and `/internal/infogatherer/callback`.

### 3. Standard Webhooks (Gemini batch)

Headers: `webhook-id`, `webhook-timestamp`, `webhook-signature`

- Reject timestamps older than 5 minutes (replay protection)
- Dedupe on `webhook-id` (at-least-once delivery)
- Symmetric `v1` HMAC implemented; JWKS asymmetric (`v1a`) documented for dynamic webhooks

### General rules

- **Constant-time comparison always** (`hmac.compare_digest`, never `==`)
- **Secrets in env only** — never hardcoded or committed
- **Auth failures log at fatal level** — misconfigured secrets must scream on day one

---

## Chatwoot Integration

### Inbound

Single webhook: `POST /webhooks/chatwoot` — configure in Chatwoot admin.

### Outbound (`app/chatwoot_client.py`)

Auth: `api_access_token: CHATWOOT_API_TOKEN`, 10s timeout.

| Function | Purpose |
|----------|---------|
| `send_message()` | Outgoing bot messages |
| `get_labels()` | Live label snapshot (TagAssigner) |
| `set_labels()` | Replace full label set |
| `set_custom_attribute()` | Single attribute |
| `set_custom_attributes()` | Multiple attributes |
| `fetch_conversation()` | Full conversation fetch |

**Important:** Chatwoot label POST **replaces the full set** — TagAssigner merge logic computes the diff, then writes the complete desired state.

---

## Testing

### Test suite

| File | Covers |
|------|--------|
| `tests/test_matching.py` | University matching algorithm, n-gram helpers, alias normalization |
| `tests/test_phrase_gate.py` | Phrase gate filters and pre-conditions |
| `tests/test_info_gatherer.py` | InfoGatherer extraction helpers (`_extract_university_candidate`, gender regex) |
| `tests/test_info_gatherer_handlers.py` | Invalid-input handlers (university/campus clarification, two-strike escalation) |
| `tests/test_security.py` | HMAC / secret verification |
| `tests/test_testing_mode.py` | Phone allowlist behavior |
| `tests/test_label_resolver.py` | TagAssigner label taxonomy |
| `tests/test_conflict.py` | Option-A timestamp conflict rule |
| `tests/test_payload_builder.py` | Gemini payload assembly |

The `@pytest.mark.integration` marker is configured in `pytest.ini`, but **no integration tests are checked in yet** — `pytest -m integration` currently selects nothing.

### Pre-V1 audit suites

**Suite A — Hotel data-state audit** (`docs/hotel_data_state_audit.sql`):

Run entire file. **Pass = zero rows on every check (A1–A11).** A12 is a manual review report.

Key checks:
- A2: GK Regency class — visible hotels must not be hidden when wired
- A4: Every visible hotel has a `hotel_chatwoot_label_map` row
- A6: Every selectable hotel has `response_schemas` wiring

**Suite B — Alias collision check** (`docs/alias_collision_check.py`):

```bash
export DATABASE_URL='postgresql://...'
python3 docs/alias_collision_check.py
# Exit 0 = pass
```

**Suite F — Functional conversational tests** (`docs/wa_test_links.md`):

WhatsApp test links F1–F10 with pass/fail annotations. **Mandatory teardown between tests:**

```sql
UPDATE conversations
SET flow_state = NULL, university_id = NULL, gender = NULL,
    pending_parent_university_id = NULL, ilgili_otel = NULL,
    ilgili_otel_set_at = NULL, ilgili_otel_set_by = NULL,
    auto_run_count = 0, manual_run_count = 0,
    clarification_attempt = 0
WHERE chatwoot_conversation_id = <your_test_cw_id>;
```

Also clear Chatwoot labels/attributes in the UI before each fresh run.

### Test cleanup script

```bash
python3 scripts/testclean.py  # removes test conversation data in FK-safe order
```

---

## Deployment

### Railway

```
Procfile: web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Single web dyno. Database is external (Supabase). Set all env vars in Railway dashboard.

### Boot sequence

1. Create asyncpg pool
2. Run integrity check (fatal unless `INTEGRITY_CHECK_BYPASS=true`)
3. Start 6 background asyncio loops
4. Log "Univotel Chatbot started"

### Integrity check (`app/health/integrity_check.py`)

Validates at boot and daily:

- Every hotel has ≥1 `response_schemas` row
- GLOBAL-NULL-STATE and DEAL-AWAITING-STATE fully wired
- `hotel_chatwoot_label_map` completeness
- `university_parent_map` completeness (no orphan campuses)
- No duplicate campus labels
- Label map exact-string match against live Chatwoot (when configured)

Failure → fatal log, app refuses to start (unless bypassed).

### Staged go-live sequence

1. Run Suites A & B; fix every finding
2. Implement matching-fixes spec (F6/F8); re-run F-suite + conv-52 smoke test with `INTEGRITY_CHECK_BYPASS=off`
3. Widen allowlist → monitor logs → `TESTING_LIMITATIONS_MODE=off`
4. Monitor first week: RecEngine candidate logs, integrity sweep, TagAssigner error rate

---

## Production Readiness

See `docs/v1-audit.md` for the full audit. Summary of blockers before turning off `TESTING_LIMITATIONS_MODE`:

### Must complete

- [ ] F6 pass — `taşkışla` → İTÜ Maçka direct (re-verify live after matching fixes)
- [x] Phrase gate implemented — multi-filter gate in `phrase_gate.py` (natural greetings/housing/proximity pass)
- [x] F8 — invalid campus/university two-strike behavior (clarify once, silent `human_needed` on second failure)
- [ ] Suite A (A1–A11) — zero rows on every check
- [ ] Suite A12 — intended hotel at rank 1 for high-traffic campuses
- [ ] Suite B — alias collision check exits 0
- [ ] Migrations 013 and 014 applied on production DB
- [ ] `INTEGRITY_CHECK_BYPASS=off` — clean boot
- [ ] `deal_awaiting_msg` copy finalized

### Strongly recommended

- [ ] Conv-52 smoke test — `itü` → campus → gender → correct hotel → attributes in Chatwoot immediately
- [ ] Turkish label round-trip verified against live Chatwoot
- [ ] Silent `human_needed` audit — every escalation sends outbound OR is documented
- [ ] Fix stale HMAC unit test (timestamp in signed payload)

---

## Known Issues & Open Decisions

### Phrase gate — first unmatched opener (residual risk)

The multi-filter phrase gate (`app/layers/phrase_gate.py`) now accepts natural Turkish greetings, housing/proximity intent, widget templates, and entity n-grams on the **first inbound message**. F-suite step-1 failures from the July 2026 test run were addressed by this module.

**Residual risk:** If the first message matches **no** filter and is not a hotel n-gram match, the gate returns `IGNORE` — the conversation stays in `new` with **no outbound message** and no escalation. This is intentional (not `human_needed`) but can look like a broken bot to leads who open with unstructured text.

### Silent `human_needed`

`_escalate_human_needed` updates DB only — no Chatwoot message. Affects: second invalid campus reply, gender parse failures, post-completion free text, and (after matching-fixes) second invalid university reply. First invalid campus/university replies **do** send outbound clarification canned responses (migration 014).

### Open product decisions

| Item | Question |
|------|----------|
| RecEngine geography (F3) | Should `hotel_accessible_universities` be narrowed? Should `priority_score` encode district proximity? |
| Out-of-Istanbul vs silent handoff | Second invalid university reply → silent `human_needed` (implemented). National-university list still deferred for F10. |
| Out-of-Istanbul (F10) | Same path for nonsense vs real out-of-area universities — acceptable? |
| National university list | Deferred — see Fix 5 in `docs/matching-fixes-impl-spec.md` |

### Engineering gaps (not all V1 blockers)

| Gap | Detail |
|-----|--------|
| No CI | pytest exists but nothing runs on push/PR |
| In-memory feedback-loop guard | `_recent_self_writes` breaks with multiple Railway replicas |
| localhost internal HTTP | RecEngine callbacks via `http://localhost:{PORT}` — fragile multi-dyno |
| Full-table loads per message | `get_all_hotels()`, `get_all_universities()`, `get_all_university_aliases()` — needs caching at scale |
| Nightly batch stub | `batch_client._submit_batch()` may log warning until GCP wired |
| `.env.example` default | `INTEGRITY_CHECK_BYPASS=true` is risky for production templates |
| `deal_awaiting_msg` | Still `<TODO>` in migration 006 seed |

### F6 — campus alias `taşkışla`

Resolves via Tier-2 alias in `match_university()` (direct from `awaiting_university`) and via campus-scoped alias lookup in `awaiting_campus_clarification`. Re-verify against live DB with F-suite teardown between runs.

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [`docs/univotel-chatbot-spec.md`](docs/univotel-chatbot-spec.md) | V0 master spec — InfoGatherer, RecEngine, security, DB |
| [`docs/tagassigner-v1-spec.md`](docs/tagassigner-v1-spec.md) | V1 TagAssigner — triggers, 4 lists, conflict rule, batch |
| [`docs/tagassigner-build-brief.md`](docs/tagassigner-build-brief.md) | Governing build brief (wins conflicts over v1-spec) |
| [`docs/tagassigner-phase-plan.md`](docs/tagassigner-phase-plan.md) | Phase-by-phase implementation plan with exit criteria |
| [`docs/v0-amendment-deal-awaiting.md`](docs/v0-amendment-deal-awaiting.md) | `deal_awaiting` flow amendment to InfoGatherer |
| [`docs/v1-audit.md`](docs/v1-audit.md) | Production readiness audit — failures, decisions, checklist |
| [`docs/chatbot-phrase-gate-and-matching-spec.md`](docs/chatbot-phrase-gate-and-matching-spec.md) | Phrase gate, clarification flows, matching normalization |
| [`docs/matching-fixes-impl-spec.md`](docs/matching-fixes-impl-spec.md) | Pending matching/clarification fixes (F6, F8, dynamic Levenshtein) |
| [`docs/wa_test_links.md`](docs/wa_test_links.md) | WhatsApp functional test links F1–F10 with annotations |
| [`docs/test_plan_flags_1_and_2.md`](docs/test_plan_flags_1_and_2.md) | Suite A/B/F definitions and exit criteria |
| [`docs/test-and-fix-1.md`](docs/test-and-fix-1.md) | Conv-52 root-cause analysis and fix list |
| [`docs/hotel_data_state_audit.sql`](docs/hotel_data_state_audit.sql) | Suite A SQL audit queries |
| [`docs/alias_collision_check.py`](docs/alias_collision_check.py) | Suite B alias collision script |
| [`system_prompts/tagassigner_prompt.md`](system_prompts/tagassigner_prompt.md) | Gemini system prompt for TagAssigner |

---

## Contributing

When making changes:

1. Read the relevant spec in `docs/` before modifying layer logic
2. Run `pytest` before opening a PR
3. For InfoGatherer/RecEngine changes, re-run conv-52 smoke test and relevant F-suite cases
4. For schema changes, add a new numbered migration file — do not edit applied migrations
5. Keep `MODEL_ID` as an env constant; never hardcode Gemini model names
6. Never commit secrets; verify `.env` is gitignored
7. Migrations are handed over for manual Supabase application — do not auto-apply from app code

For questions about scope, the V0 spec's §10 ("Things deferred, not rejected") documents features intentionally left for FallBack V2: post-completion re-recommendation and general intent routing.
