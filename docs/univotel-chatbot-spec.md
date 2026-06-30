# Univotel Chatbot — Project Specification (V0)

**Status:** Ready for implementation
**Scope:** InfoGatherer + RecEngine, full error handling, security, deployment
**Out of scope (V1/V2, documented for context only):** TagAssigner, FallBack

---

## 1. Project Summary & Goal

Univotel's Chatwoot inbox handles a high volume of repetitive, scriptable lead conversations: a student messages in from a pre-filled website link, the salesperson asks which university and gender, looks up a matching dorm/hotel, and pastes a few canned responses. This consumes salesperson time on a task that has no real judgment calls in the common case.

The Univotel Chatbot automates this specific, bounded flow. It does **not** try to handle general conversation — it handles exactly the "lead arrives with a preset message → we identify them → we recommend a property → we send the property info" path, and hands off anything outside that path to a human.

**Goal for V0:** fully automate the InfoGatherer (scripted info-gathering) and RecEngine (recommendation) layers, with TagAssigner and FallBack explicitly deferred. Every path in V0 must resolve to a clean, observable end state — either a successful canned-response send, or an explicit `human_needed` handoff. Nothing should silently hang or silently fail.

**The four layers (V0 builds the first two only):**

| Layer | Job | Status |
|---|---|---|
| **InfoGatherer** | Scripted info-gathering: detect context, ask for missing university/gender, send recommendation | **Build now (V0)** |
| **RecEngine** | Given gender + university, find the best-matching property | **Build now (V0)** |
| **TagAssigner** | LLM-based reading of conversations to set Chatwoot labels/attributes | Deferred (V1) |
| **FallBack** | LLM-based natural-language recovery when the script fails | Deferred (V2) |

Until FallBack exists, every place this document says "call FallBack" should be read as **"tag the conversation `human_needed`."** This is intentional — it's the same escalation target, just without the LLM doing the disambiguation work yet. When FallBack is built, those call sites should be revisited (see §9).

---

## 2. Tech Stack

| Component | Choice |
|---|---|
| Backend language/framework | Python + FastAPI |
| Database | Supabase Postgres (existing project — `hotels`, `universities`, `hotel_accessible_universities` already live there) |
| Messaging platform | Chatwoot (webhook-driven) |
| LLM (FallBack, V2) | Gemini 3 Flash |
| LLM (TagAssigner, V1) | Gemini 1.5 Flash *(see §9 — deprecation risk, reconfirm at build time)* |
| Deployment | **Railway, Hobby tier** |
| Process model | Single always-on FastAPI process (no serverless) |
| Background work | In-process async tasks (FastAPI `BackgroundTasks` / `asyncio`) for retry ladders and sweeps |
| Scheduled jobs | In-process interval loop or Railway Cron for the 3-hour reprompt sweep and daily integrity check |

**Why Railway, and why not serverless (Vercel/Cloudflare):** This system's core reliability pattern is the **async request-reply pattern** — a webhook handler returns `200` immediately and the actual work (RecEngine's retry ladder, send retries, the 3-hour reprompt sweep) runs in a detached background task afterward. Serverless platforms tear down compute when the response is sent, which kills exactly this pattern. Railway runs the app as a normal persistent process — like a small VPS — so detached background tasks behave exactly as designed, with no architectural workaround needed. Railway Hobby ($5/mo included usage, billed by actual consumption) is expected to comfortably cover this workload since the database is external (Supabase) — Railway only ever runs the lightweight, mostly-idle FastAPI service itself.

---

## 3. Folder Structure

```
univotel-chatbot/
├── app/
│   ├── main.py                      # FastAPI app, route registration
│   ├── config.py                    # env var loading (secrets, DB url, etc.)
│   ├── security.py                  # HMAC verification, internal shared-secret check, constant-time compare
│   ├── db/
│   │   ├── client.py                 # Postgres/Supabase connection
│   │   ├── models.py                 # Pydantic models mirroring tables
│   │   └── queries.py                # Query functions (matching, hotel lookup, log writes)
│   ├── webhooks/
│   │   └── chatwoot.py               # POST /webhooks/chatwoot — entrypoint, dedupe, upsert-on-race
│   ├── layers/
│   │   ├── info_gatherer.py          # ContextRun state machine + response resolution
│   │   ├── rec_engine.py             # Gender/university filter + priority_score tie-break
│   │   └── matching.py               # normalize → exact → alias → Levenshtein matching
│   ├── background/
│   │   ├── rec_engine_ladder.py      # 3-attempt retry ladder (5s/5s/5s) with shared idempotency key
│   │   ├── send_retry.py             # canned-response send retry with exponential backoff
│   │   └── reprompt_sweep.py         # 3h reprompt ladder (Efendim? / Orada mısınız? / Müsait olduğunuzda...)
│   ├── health/
│   │   └── integrity_check.py        # boot-time + daily referential-integrity sweep
│   └── chatwoot_client.py            # wrapper: send message, set custom attribute, fetch conversation
├── migrations/
│   ├── 001_create_core_tables.sql
│   ├── 002_alter_hotels_add_gender_and_priority.sql
│   ├── 003_insert_global_null_state.sql
│   └── 004_create_university_aliases.sql
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

---

## 4. API & Webhook Documentation

### 4.1 Inbound — Chatwoot Webhook

```
POST /webhooks/chatwoot
```

- **Auth:** Chatwoot HMAC signature, verified against a shared webhook secret (see §6.5). Invalid/missing signature → `401`, request dropped before parsing, logged `fatal`.
- **Behavior:** Always returns `200` immediately after cheap bookkeeping (dedupe check, conversation upsert, state read). All actual processing — matching, RecEngine calls, sends — happens in a detached background task. This is non-negotiable; see §6.1.
- **Dedupe:** Incoming payload's `chatwoot_message_id` is checked against `messages` before any processing. If it already exists, the webhook is a no-op (handles Chatwoot's redelivery-on-timeout behavior).
- **Unknown conversation:** If no `conversations` row exists for the given `chatwoot_conversation_id`, one is created on the fly in state `new` (`INSERT ... ON CONFLICT (chatwoot_conversation_id) DO NOTHING` to handle the race where two webhooks for a brand-new conversation arrive close together).
- **Malformed payload:** If `chatwoot_conversation_id` cannot be extracted at all → log `400`, fatal, drop (nothing else is possible). If the conversation ID is present but the rest of the payload is junk → log `400`, tag `human_needed` so a person can look.

### 4.2 Internal — InfoGatherer → RecEngine

```
POST /internal/recengine/start
Headers: X-Internal-Secret: <shared secret>
Body: { "conversation_id": "<uuid>", "idempotency_key": "<uuid>" }
```

- `idempotency_key` is generated **once** when InfoGatherer first decides to call RecEngine, and **reused across all retry attempts** in the ladder (see §6.2). RecEngine's first action on receiving a request is to write a `processing` row to `rec_engine_logs` keyed on that idempotency key — *before* running any query — so a retry that arrives mid-processing finds the row and no-ops rather than running twice.
- Auth failure (wrong/missing internal secret) → `401`, logged fatal, request dropped.

### 4.3 Internal — RecEngine → InfoGatherer (callback)

```
POST /internal/infogatherer/callback
Headers: X-Internal-Secret: <shared secret>
Body: { "conversation_id": "<uuid>", "hotel_rec": "<uuid> | null", "status": "200_FOUND | 200_NOT_FOUND | 502" }
```

Primary completion path. If this callback never arrives, InfoGatherer's retry ladder (§6.2) is the fallback: it polls `rec_engine_logs` for the idempotency key at the 5s/10s/15s checkpoints.

### 4.4 Response payload shapes (RecEngine → InfoGatherer, conceptual)

```json
// 200 FOUND
{ "hotelName": "<name>", "status": "200 OK", "errorClass": null }

// 200 NOT FOUND
{ "hotelName": null, "status": "200 OK", "errorClass": null }
// → resolves to the GLOBAL-NULL-STATE hotel_id internally, canned response via response_schemas

// 502 FAILED
{ "hotelName": null, "status": "502 Bad Gateway", "errorClass": "system_failure" }
```

Canned responses are **never** derived from these payloads directly — see §8.2. Whatever `hotel_id` is determined (by RecEngine, or by a direct hotel-name match in InfoGatherer), the *only* path to sending messages is: look up `response_schemas` for that `hotel_id`, order by `sending_order`, send each `canned_responses.content` in sequence.

---

## 5. Operation Layers

### 5.1 InfoGatherer — ContextRun

**Step 1 — Phrase gate.** Message must contain at least one exact phrase (including punctuation): `"Üniversitem:"`, `"Merhaba!"`, `"My University:"`, `"Hello!"`, `"Başvuru Kodu:"`. No match → call FallBack (→ `human_needed` in V0).

**Step 2 — Direct hotel-name match.** Message matched against `hotels.name`. If found: resolve and send that hotel's `response_schemas` (ordered), set state → `completed`. No gender/university capture, no RecEngine call — this is a fast, self-contained path, and it's intentional: if a lead asks about a hotel by name, they get its info, even if it doesn't match their gender/university profile (see §5.2's note on `priority_score` for the contrast with how RecEngine's own matching works).

**Step 3 — `Üniversitem:` line match.** If that label exists, search that line ±1 line for a university match (full matching algorithm, §8.1). Match → set `university_id`, proceed to Step 6 (gender). No match → Step 4.

**Step 4 — Keyword-based match.** Search for `"Üniversitesi"`, `"Üni"`, `"uni"`, `"universitesi"` or similar; on a hit, run the matching algorithm against the same line ±1 line. Match → set `university_id`, proceed to Step 6. No match → Step 5.

**Out-of-Istanbul check (applies to both Step 3 and Step 4 paths):** if a university keyword is found but resolves to no match anywhere, first check the narrower 1–4-words-before-keyword window; if that also yields nothing, check the wider same-line-±1 window. If neither window produces a match, the university is treated as outside Istanbul's service area: send `/istanbul`, stop. This is a clean terminal stop — not a FallBack/`human_needed` escalation.

**Step 5 — Direct ask.** Send canned response `hangi`, set state → `awaiting_university`. On reply, run the matching algorithm against the reply text.

**Ambiguous match (Levenshtein tie, any step):** send a neutral clarification ("Tam ismi neydi efendim üniversitenizin, kısaltmadan çıkaramadım?"), set state → `awaiting_university_clarification`. One clarification attempt only — if the clarified reply is still ambiguous or no-match, call FallBack (→ `human_needed`).

**Step 6 — Gender ask.** Always asked — never inferred from the prefill. Send `kiz-erkek`, set state → `awaiting_gender`. Reply containing "kiz"/"kız"/"bayan"/"kadın" → female. Reply containing "bay"/"erkek"/"oğlan" → male. No match → call FallBack (→ `human_needed`).

Once both `university_id` and `gender` are confirmed set, fire the RecEngine start event (state → `recengine_running`).

**Pre-flight check before firing RecEngine:** InfoGatherer verifies `university_id` and `gender` are actually persisted (catches a silent custom-attribute write failure). If missing: re-check the message history to recover them. If state isn't yet at the point where they should exist, ask normally. If state says they *should* exist and they don't, call FallBack (→ `human_needed`); log with `status_code: 500`, `internal_class: attr_write_failed`, explanation `"Custom attribute write failed, retried to parse but failed; aborted after retry. FallBack call, [success/fail]."`

**Non-text replies while awaiting an answer:** keep waiting, do not consume a reprompt. When a text reply eventually arrives, re-evaluate it against the current state; if it resolves, continue the flow; if not, call FallBack (→ `human_needed`).

**Abandonment (no reply at all, in any awaiting state — including clarification):** see §6.4 — reprompt ladder, no escalation, no terminal state. The conversation simply waits; resuming normally whenever the lead replies, however late.

**Post-completion re-engagement:** if a lead in `completed` names a *different specific hotel*, InfoGatherer re-runs the Step 2 path (no RecEngine). Any other post-completion message (general question, "show me something else" without naming a hotel) is **deferred to FallBack** (→ `human_needed` in V0) — deliberately not built into the script, since it's a free-text intent-routing problem.

### 5.2 RecEngine

Triggered by the start event. Pulls `university_id` and `gender` from the conversation:

1. Query `hotels` for `gender_scope` match (`male`/`female`/`mixed`).
2. Query `hotel_accessible_universities` for `university_id` match.
3. Filter (1) by hotel IDs from (2).
4. Result count = 1 → `200 FOUND`. Result count = 0 → `200 NOT FOUND` (resolves to `GLOBAL-NULL-STATE`). Result count > 1 → pick the highest `priority_score`, `200 FOUND`.
5. Anything that aborts the operation before reaching a definitive FOUND/NOT FOUND → `502`.

`priority_score` is the single manually-tunable lever for everything outside gender/university match — capacity, quality, anything else. Lower it manually to deprioritize a hotel without removing it from eligibility.

### 5.3 TagAssigner (V1 — deferred, documented for context)

LLM-based (**`gemini-2.5-flash-lite`**, an env constant — see `tagassigner-v1-spec.md` §2), reads conversation state on a 15-minute-idle **in-process asyncio sweep** (not `pg_cron`) and sets labels/attributes. Max 5 automated runs/day per lead, final run always at **23:40 Istanbul**. Runs **independently of InfoGatherer/RecEngine** and is not gated by their state — it always runs unless deliberately turned off, regardless of what the other layers are doing with a given conversation. Out of scope for V0 build. **For current V1 detail this paragraph is superseded by `tagassigner-v1-spec.md` + `tagassigner-build-brief.md`.**

### 5.4 FallBack (V2 — deferred, documented for context)

LLM-based (Gemini 3 Flash) natural-language recovery layer. Every "call FallBack" instruction in this document currently resolves to `human_needed` until this is built.

---

## 6. Backend

### 6.1 Async Request-Reply (core architectural pattern)

No webhook handler ever blocks waiting on a downstream call. The handler does its cheap bookkeeping and returns `200` immediately; anything that involves waiting — a retry ladder, a timed sweep — runs as a detached background task. This is the standard pattern for exactly this situation (sometimes called the "webhook ack" pattern), and it's also why Railway (persistent process) was chosen over serverless platforms that kill background work once the response is sent.

### 6.2 RecEngine Retry Ladder

```
fire (idempotency_key generated here, reused below)
  → wait 5s → check rec_engine_logs for idempotency_key
    → not found → fire again (same key)
      → wait 5s → check again
        → not found → fire again (same key)
          → wait 5s → check again
            → not found → human_needed
```

RecEngine writes a `processing` row to `rec_engine_logs` **immediately on receipt**, before doing any query work — this is what makes the shared idempotency key actually prevent duplicate runs; a retry that arrives while the first attempt is still mid-query finds the existing row and no-ops.

### 6.3 Send Retry (canned responses & custom attribute writes)

Retryable errors (timeouts, 5xx, connection resets) get **exponential backoff**, not immediate retry: ~1s → ~2s → ~4s, 3 attempts, then fatal. Non-retryable errors (4xx — malformed request, auth failure) skip straight to fatal; retrying an identical bad request three times wastes the attempts. Timeouts are logged as `TIMEOUT`; network/HTTP failures log the actual code received.

### 6.4 Reprompt Ladder (abandonment handling)

Applies uniformly to every state where the bot is waiting on a lead reply — `awaiting_university`, `awaiting_university_clarification`, and `awaiting_gender` all use the same ladder. Tracked via `conversations.reprompt_count` and `conversations.last_reprompt_sent_at`. A 3-hour sweep job checks elapsed time since the last reprompt (or since `last_updated_at` if `reprompt_count = 0`):

| Hours since last contact | Action |
|---|---|
| 3h | Send "Efendim?", `reprompt_count → 1` |
| 6h | Send "Orada mısınız?", `reprompt_count → 2` |
| 9h | Send "Müsait olduğunuzda dönüşünüzü bekliyorum efendim.", `reprompt_count → 3` |
| beyond | Nothing further. No tag, no terminal state — conversation simply sits. |

If the lead replies at any point, InfoGatherer resumes from the current `flow_state` using the matching algorithm; if it can't resolve, call FallBack (→ `human_needed`).

### 6.5 Bot Identity & Human Takeover Detection

The bot posts to Chatwoot through its own dedicated agent account, named `ChatBot` — a distinct identity from any human salesperson's account. Every outbound message webhook is checked against this identity before being logged:

- If the outbound message's `sender_id` matches the `ChatBot` agent's ID → it's the bot's own send. Tag `messages.sender_type` as `infoGatherer` (or `fallBack`, once that layer exists) and continue normally.
- If `sender_id` does **not** match → a human agent has taken over. Tag `messages.sender_type = 'user'`, and immediately set `conversations.flow_state = 'stopped'`. No further automatic action is taken on this conversation from that point on.

**Terminal is terminal.** Once a conversation reaches `completed`, `stopped`, or `human_needed`, inbound messages are still logged normally — so a lead messaging into an apparently-dead conversation remains visible for review — but the bot takes **no automatic action** on them. The one explicit exception: a `completed` conversation naming a different specific hotel by name re-enters the Step 2 direct-match path (§5.1). Every other post-terminal message is left for a human, or eventually FallBack.

### 6.6 Security

The mandate here was: protect against realistic threats, add no setup burden, never slow down or break a genuine connection. The model is **shared-secret verification at every trust boundary, with loud failure** — nothing more elaborate, because anything heavier (rate limiting, IP allowlisting) risks exactly the false-positive cost the mandate excludes.

1. **Chatwoot → bot webhook:** Chatwoot signs every webhook with an HMAC computed from a shared secret. The endpoint recomputes the signature and compares; mismatch or missing → `401`, dropped before parsing. One-time setup (generate one secret, paste into Chatwoot's webhook config and the app's env). Adds a single hash computation per request — no measurable latency.
2. **InfoGatherer ↔ RecEngine internal calls:** a shared secret token in a header, checked the same way.
3. **Constant-time comparison, always.** Secret/signature comparisons must use a constant-time compare (e.g. Python's `hmac.compare_digest`), never `==`. A normal equality check leaks timing information that lets an attacker guess a secret byte by byte.
4. **Secrets live in environment variables only** — never hardcoded, never committed. Same discipline as everything else in the Univotel codebase.
5. **Auth failures log loudly** (`fatal` level, distinct status) rather than failing silently. This directly mirrors the `cron_secret` mismatch that silently broke production crons for weeks — a misconfigured secret here should scream on day one, not three weeks later.

This protects against the realistic threats (forged webhooks, endpoint discovery, service spoofing) without adding any friction to genuine Chatwoot traffic.

### 6.7 KVKK / Data Retention

No deletion flow. Data (messages, lead attributes, sender identity) is retained indefinitely by policy. This is already disclosed via the public KVKK notice on the website and social accounts — no additional in-app notice needed.

---

## 7. Database Structure

### 7.1 Existing tables (live in Supabase, copied from univotel.com)

These already exist and are populated via the provided exports (`hotels_rows.sql`, `universities_rows-2.sql`, `hotel_accessible_universities_rows.sql`). The `CREATE TABLE` statements below mirror their actual current structure — confirmed directly from the exports, not assumed — so this section also serves as a structural reference.

```sql
-- Mirrors live structure exactly. Do not recreate if already present in the target DB;
-- this is the reference for anyone setting up a fresh environment.

CREATE TABLE hotels (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    slug text,
    sub_header text,
    description text,
    address text,
    city text,
    latitude numeric,
    longitude numeric,
    map_embed_url text,
    google_maps_link text,
    representative_name text,
    representative_photo_url text,
    representative_email text,
    representative_phone text,
    representative_suggestion text,
    payment_details text,
    instagram_group_link text,
    video_url text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    district text,
    neighborhood text,
    postal_code text,
    nearby_landmarks text,
    nearby_transport_stations text,
    local_keywords text,
    parking_info text,
    public_transport_info text,
    is_visible boolean DEFAULT true,
    description_en text,
    sub_header_en text,
    property_type text  -- 'dormitory' | 'hotel'
);

CREATE TABLE universities (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    address text,
    city text,
    latitude numeric,
    longitude numeric,
    website_url text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    maps_url text,
    slug text,
    logo_url text,
    university_short_name text,   -- e.g. "İKÜ" — useful seed for the alias table, §8.1
    campus_url text,
    university_type text          -- 'vakif' | 'devlet'
);

CREATE TABLE hotel_accessible_universities (
    hotel_id uuid REFERENCES hotels(id),
    university_id uuid REFERENCES universities(id),
    commute_time_car_minutes int4,
    commute_time_public_transport_minutes int4,
    commute_time_walk_minutes int4,
    route_image_url text,
    route_link_url text,
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (hotel_id, university_id)
);
```

> **⚠️ Confirmed gap, not a design choice:** as exported, `hotels` has **no gender field** (gender is only readable from free text in `name`, e.g. "Erkek"/"Kız") and **no `priority_score` field**. RecEngine cannot function against the live schema until migration 002 below runs.

### 7.2 Migrations (new, required before RecEngine can run)

**`002_alter_hotels_add_gender_and_priority.sql`**

```sql
ALTER TABLE hotels
    ADD COLUMN gender_scope text CHECK (gender_scope IN ('male', 'female', 'mixed')),
    ADD COLUMN priority_score int4 DEFAULT 100;

-- Backfill gender_scope from existing name text as a starting point — must be
-- manually reviewed, this is a one-time heuristic pass, not a permanent strategy:
UPDATE hotels SET gender_scope = 'male'   WHERE name ILIKE '%erkek%';
UPDATE hotels SET gender_scope = 'female' WHERE name ILIKE '%kız%' OR name ILIKE '%kiz%';
-- Any hotel left with gender_scope IS NULL after this needs manual classification
-- before it can ever be returned by RecEngine.
```

**`003_insert_global_null_state.sql`**

```sql
-- Reserved fixed UUID so application code can reference it directly.
INSERT INTO hotels (id, name, is_visible, gender_scope, priority_score)
VALUES ('00000000-0000-0000-0000-000000000001', 'GLOBAL-NULL-STATE', false, NULL, NULL);

INSERT INTO canned_responses (id, short_code, content)
VALUES (gen_random_uuid(), 'henuz', '<TODO: insert actual "sorry, no matching hotel" copy>');

INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000001', id, 1
FROM canned_responses WHERE short_code = 'henuz';
```

> This sentinel is selected via an explicit code branch in RecEngine (result count = 0), not via a query match — so unlike the original draft note, it does **not** need a row in `hotel_accessible_universities`. It only needs to exist in `hotels` and have its `response_schemas` wired, since canned-response resolution always goes through that table regardless of path (§5.1, §8.2).

**`004_create_university_aliases.sql`**

```sql
CREATE TABLE university_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id uuid REFERENCES universities(id) NOT NULL,
    alias text UNIQUE NOT NULL,   -- normalized, lowercase, unambiguous abbreviations only
    created_at timestamptz DEFAULT now()
);
-- Seed opportunistically from real lead messages as abbreviations are observed.
-- Deliberately exclude ambiguous shortcuts (e.g. "ibü") — those route through
-- the clarification flow instead (§5.1, §8.1).
```

### 7.3 New tables (this project)

```sql
CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chatwoot_conversation_id int4 UNIQUE NOT NULL,
    created_at timestamptz DEFAULT now(),
    last_updated_at timestamptz DEFAULT now(),
    last_processed_at timestamptz,
    last_processed_log_id uuid REFERENCES chatbot_logs(id),
    flow_state text NOT NULL DEFAULT 'new'
        CHECK (flow_state IN (
            'new', 'awaiting_university', 'awaiting_university_clarification',
            'awaiting_gender', 'recengine_running', 'completed',
            'human_needed', 'stopped'
        )),
    labels text[] DEFAULT '{}',
    university_id uuid REFERENCES universities(id),
    gender text CHECK (gender IN ('male', 'female')),
    custom_attributes jsonb DEFAULT '{}',  -- flexible slot for any other Chatwoot attribute
    messages_since_last_run int4 DEFAULT 0,   -- inert in V0, used by TagAssigner (V1)
    time_since_last_run interval,             -- inert in V0
    daily_run_count int4 DEFAULT 0,           -- inert in V0
    reprompt_count int4 DEFAULT 0,
    last_reprompt_sent_at timestamptz
);

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid REFERENCES conversations(id) NOT NULL,
    created_at timestamptz DEFAULT now(),
    last_processed_at timestamptz,
    log_id uuid REFERENCES chatbot_logs(id),
    chatwoot_message_id int4 UNIQUE NOT NULL,   -- enforces dedupe, §4.1
    content text,
    message_type text CHECK (message_type IN ('inbound', 'outbound')),
    sender_type text CHECK (sender_type IN ('user', 'contact', 'infoGatherer', 'fallBack')),
    sender_id text,     -- Chatwoot agent/contact id — drives human-takeover detection, §6.5
    sender_name text,
    is_private boolean DEFAULT false
);

CREATE TABLE chatbot_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz DEFAULT now(),
    conversation_id uuid REFERENCES conversations(id),
    operation_layer text CHECK (operation_layer IN ('infoGatherer', 'recEngine', 'tagAssigner', 'fallBack')),
    which_run text CHECK (which_run IN ('contextRun', 'outputRun')),
    from_state text,   -- drawn from the same flow_state vocabulary as conversations.flow_state
    to_state text,
    log_level text CHECK (log_level IN ('info', 'warn', 'error', 'fatal')),
    is_success boolean,
    status_code text,        -- real HTTP codes only
    internal_class text,     -- non-HTTP internal error classes, e.g. 'attr_write_failed'
    network_status text CHECK (network_status IN ('success','timeout','econnrefused','enotfound','econnreset','ssl_err')),
    database_status text CHECK (database_status IN ('success','db_conn_fail','db_dup_key','db_lock_timeout','disk_full','out_of_memory')),
    explanation text
);

CREATE TABLE rec_engine_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz DEFAULT now(),
    conversation_id uuid REFERENCES conversations(id) NOT NULL,
    idempotency_key uuid UNIQUE NOT NULL,
    status text NOT NULL CHECK (status IN ('processing', 'success', 'failed')),
    hotel_rec uuid REFERENCES hotels(id),
    status_code text,
    network_status text,
    database_status text
);

CREATE TABLE canned_responses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz DEFAULT now(),
    last_updated_at timestamptz DEFAULT now(),
    short_code text UNIQUE NOT NULL,
    content text NOT NULL
);

CREATE TABLE response_schemas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id uuid REFERENCES hotels(id) NOT NULL,   -- renamed from original draft's "rec_engine_outcome";
                                                      -- same column now serves both RecEngine results
                                                      -- and direct hotel-name matches (§5.1 Step 2)
    response_id uuid REFERENCES canned_responses(id) NOT NULL,
    sending_order int4 NOT NULL,
    UNIQUE (hotel_id, sending_order)
);
```

---

## 8. Algorithms

### 8.1 University Matching

```
normalize(text)               # lowercase, strip Turkish diacritics, strip
                               # "Üniversitesi"/"University" suffixes, trim
  → exact match against universities.name / university_short_name
    → hit: done
    → miss: check university_aliases (known unambiguous abbreviations)
      → hit: done
      → miss: Levenshtein distance ≤ 2 against normalized university names
        → exactly one hit within cutoff: done
        → multiple hits tied within cutoff: ambiguous → one clarification round (§5.1) → FallBack
        → zero hits: no match → out-of-Istanbul check (§5.1) or FallBack, depending on entry point
```

Deliberately **not** a continuous similarity score — a fixed edit-distance cutoff avoids the tuning/maintenance overhead of a scoring layer while still catching the typo class that normalization and aliasing can't. The cutoff (2) is a constant to revisit empirically if it proves too loose or too strict in practice, but the *mechanism* doesn't change.

An empty or whitespace-only message, after normalization, is treated identically to a no-match — it is not a separate case requiring its own branch.

### 8.2 Canned Response Resolution

```
hotel_id determined (via direct name match OR RecEngine FOUND OR GLOBAL-NULL-STATE)
  → SELECT response_id FROM response_schemas
     WHERE hotel_id = :hotel_id ORDER BY sending_order
  → for each: send canned_responses.content
  → if zero rows returned: log 404, "No matching row in response_schemas",
     log_level fatal, tag conversation human_needed
```

One resolution path, used identically regardless of how `hotel_id` was determined. There is no string-templating of short codes anywhere in the flow.

### 8.3 Optimistic Concurrency (per-conversation)

```
read flow_state
... do work ...
UPDATE conversations SET flow_state = :new_state
  WHERE id = :conversation_id AND flow_state = :expected_state
if rows_affected == 0:
  # another webhook already advanced this conversation — this is expected
  # under concurrency, not an error
  log info "lost optimistic lock race"
  stop — do not re-read or re-process
```

### 8.4 RecEngine Selection

```
gender_matches = hotels WHERE gender_scope = :gender (or 'mixed')
university_matches = hotel_accessible_universities WHERE university_id = :university_id
candidates = gender_matches ∩ university_matches (by hotel_id)

if len(candidates) == 0: return GLOBAL-NULL-STATE (200 NOT FOUND)
if len(candidates) == 1: return candidates[0]   (200 FOUND)
if len(candidates) > 1: return max(candidates, key=priority_score)   (200 FOUND)
if aborted at any point: return 502
```

**Stale hotel reference.** If the `hotel_id` ultimately resolved no longer exists in `hotels` (e.g. deleted between recommendation and response resolution), RecEngine reruns its selection **once** against the current `hotels` table. If that rerun *also* resolves to a hotel that doesn't exist, stop — log fatal and tag `human_needed` rather than looping indefinitely.

---

## 9. Things to Look Out For

**Before anything goes live:**
- `hotels` is missing `gender_scope` and `priority_score` in production right now (§7.1, §7.2) — RecEngine cannot run correctly until migration 002 is applied **and** every hotel's `gender_scope` is manually verified (the name-text backfill heuristic is a starting point, not a guarantee).
- `GLOBAL-NULL-STATE` does not exist as a row anywhere yet — migration 003 must run before the no-match path works.
- Webhook HMAC verification is the single most important missing piece architecturally — without it, anyone who finds the endpoint URL can forge Chatwoot events and drive the bot.

**Operational risks:**
- Every "call FallBack" in this document is currently `human_needed`. Once FallBack ships, each of those call sites should be revisited — some (like the ambiguous-university clarification) are specifically things an LLM resolves far better than a script ever could.
- Gemini 1.5 Flash (TagAssigner, V1) is on a deprecation track across Google's platforms — reconfirm model availability when TagAssigner is actually built, don't assume the name in this document is still valid.
- The Levenshtein cutoff (2) is a fixed constant chosen to avoid a tunable scoring layer — but it's still worth a periodic sanity check against real false-positive/false-negative matches once there's live data to look at.
- Run the daily referential-integrity health check (and a boot-time check) covering: every hotel has ≥1 `response_schemas` row; every `response_schemas.response_id` points to a live `canned_responses` row; every `response_schemas.hotel_id` points to a live hotel; `GLOBAL-NULL-STATE` is fully wired end to end. Fail loudly (fatal log) on any orphan found — this converts a class of silent runtime 404s into a loud, actionable startup/cron failure.
- Railway billing is usage-metered, not flat. Monitor actual first-month usage against the $5 included credit — expected to land comfortably under it given the lightweight, external-DB workload, but worth confirming rather than assuming.
- KVKK: retention is indefinite by policy, already publicly disclosed — no deletion flow exists or is planned for V0. Revisit only if policy changes.

---

## 10. Notes on Scope & Process

This spec deliberately excludes two features that came up during planning and were consciously deferred rather than overlooked:

- **Post-completion "show me something else" (excluding the previously-shown hotel and re-running RecEngine).** This requires new per-conversation state (which hotels have already been shown) and a new query branch, and it's a natural fit for FallBack's intent-routing once that layer exists. Building it into the script now would mean hand-rolling logic that the LLM layer will do better and more generally later.
- **A general "InfoGatherer always listens for any message" router.** This would turn InfoGatherer from a finite, auditable state machine into an open-ended intent classifier on free text — which is exactly what FallBack is for. V0 deliberately keeps every state path finite and terminating.

Both are explicitly *deferred*, not rejected — they're the natural first features to build once FallBack exists.
