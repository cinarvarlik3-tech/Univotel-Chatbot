# Univotel Chatbot — TagAssigner Specification (V1)

**Status:** Ready for implementation
**Scope:** TagAssigner (LLM-based label/attribute assignment), full error handling, security, deployment
**Builds on:** V0 (InfoGatherer + RecEngine, already shipped)
**Out of scope (V2, documented for context only):** FallBack, sales-action awareness (NetGSM/CRM integration)
**Companion document:** *V0 Amendment Note* (covers the `deal_awaiting` flow added to InfoGatherer during V1 planning)

---

## 1. Project Summary & Goal

TagAssigner has one job: read a conversation, understand it, and assign the appropriate Chatwoot labels and custom attributes. Today salespeople do this by hand — reading a chat and manually tagging the lead's academic year, who they are, what stage they're at, and so on. It's judgment work, but bounded, repetitive judgment work — exactly the kind an LLM does well.

Unlike V0's InfoGatherer/RecEngine (deterministic scripts), TagAssigner is **LLM-powered**. It uses a three-layer split for clean separation and security: the database holds conversation state, a Script Router brokers all I/O, and Gemini provides the judgment. **Gemini never touches the database or Chatwoot directly** — it only ever receives a structured payload from the Router and returns a structured response to the Router. Everything else (reading state, writing to Chatwoot, deterministic field resolution) is the Router's job.

**The LLM's entire output surface is the label set.** Gemini writes no custom attributes. Of the three attributes TagAssigner manages, two (`university`, `ogrenci_cinsiyet`) are resolved deterministically by the Router from InfoGatherer's existing DB columns, and one (`ilgili_otel`) is written by the Router under a timestamp-based conflict rule (§6.7). Gemini *sees* all attributes as read-only context to inform its labelling, but decides only labels. This is what keeps the design clean — the LLM has exactly one kind of output to reason about.

**Goal for V1:** automate label assignment for everything chat-observable, while safely abstaining from anything the LLM cannot know (sales actions taken offline — calls, phone-booked visits). Every label TagAssigner touches must be one it can justify from conversation content; everything else is left to humans or deferred to V2.

---

## 2. Tech Stack

| Component | Choice |
|---|---|
| Router language/framework | Python + FastAPI |
| LLM | **Gemini 2.5 Flash-Lite** (`gemini-2.5-flash-lite`) |
| LLM billing | Pay-as-you-go (billing-enabled project, Tier 1) — **no subscription** |
| Model ID | **Single env constant** — never hardcoded; Google's retirement cadence makes any fixed ID a liability |
| Database | Supabase Postgres (the ChatBot DB — same instance as V0) |
| Messaging platform | Chatwoot (webhook-driven) |
| Deployment | Railway, Hobby tier (same always-on process as V0) |
| Nightly batch | Gemini Batch API (50% discount, paid-tier feature) |

**Why Flash-Lite:** TagAssigner's job is classification/extraction — read a conversation, output labels. That's precisely the workload Flash-Lite is built for, at the lowest cost tier. Full Flash's extra reasoning isn't needed; if label accuracy proves insufficient in practice, stepping up to `gemini-2.5-flash` is the documented quality lever (one env-constant change).

**Model deprecation note:** Gemini's retirement cadence is aggressive (the entire 1.5 generation already returns 404s; 2.5-flash itself has an Oct 16 2026 shutdown). 2.5-flash-lite clears the V1 sales-cycle timeline, but the model ID must stay an env constant so a future migration is a one-line change. Reconfirm model availability before any future redeploy.

**Why no subscription:** higher Gemini rate limits come from *enabling billing* (pay-per-token), not a flat fee. Tier 1 (billing on) provides 150–300 RPM — far above anything TagAssigner's volume plus its queue/throttle design will ever demand. The earlier-considered "Google AI Pro/Ultra" subscription is a *consumer* product that does not raise API limits and is irrelevant here.

---

## 3. Folder Structure

```
univotel-chatbot/
├── app/
│   ├── ... (V0 InfoGatherer/RecEngine modules unchanged)
│   ├── config.py                     # env constants incl. MODEL_ID, TESTING_LIMITATIONS_MODE,
│   │                                 #   INTEGRITY_CHECK_BYPASS, secrets, allowlist
│   ├── security.py                   # HMAC verify, internal secret check, constant-time compare
│   ├── tagassigner/
│   │   ├── router.py                 # the Script Router — all I/O brokering
│   │   ├── trigger.py                # idle-scan cron, 5-message gate, manual `tag` trigger
│   │   ├── payload_builder.py        # assembles Gemini payload (MODULAR — V2 CRM block slots here)
│   │   ├── gemini_client.py          # live API calls (daytime triggers)
│   │   ├── batch_client.py           # Batch API submit + results-webhook handling (nightly)
│   │   ├── label_resolver.py         # 4-list enforcement, mutex groups, terminal hard-guard, merge
│   │   ├── attribute_resolver.py     # deterministic Router writes: university/gender/ilgili_otel
│   │   ├── conflict.py               # Option A timestamp precedence rule
│   │   └── queue.py                  # durable queue table drain (FIFO, dedupe)
│   ├── webhooks/
│   │   ├── chatwoot.py               # V0 inbound + conversation-update handler (feedback-loop guard)
│   │   └── batch_results.py          # Gemini batch-completion webhook (HMAC-secured)
│   └── health/
│       └── integrity_check.py        # boot + daily; extended for TagAssigner (see §10)
├── migrations/
│   ├── ... (V0 migrations 000–005)
│   ├── 006_deal_awaiting.sql              # V0 Amendment: deal_awaiting_universities + DEAL-AWAITING-STATE sentinel + wiring
│   ├── 007_tagassigner_runs_and_logs.sql
│   ├── 008_conversations_columns.sql      # last_message_at + auto/manual run counts + attribute columns (reconcile §7.2)
│   ├── 009_hotel_chatwoot_label_map.sql
│   └── 010_tag_assigner_queue.sql         # references 007's run_id; partial-unique dedupe index
└── ...
```

---

## 4. API & Webhook Documentation

### 4.1 Inbound — Chatwoot Webhook (shared with V0)

The V0 Chatwoot webhook handler is extended, not replaced. Two responsibilities added:

- **Attribute/label sync:** label and custom-attribute changes arriving from Chatwoot update the corresponding `conversations` columns (the DB is a downstream replica of Chatwoot — see §6.6). **Critically, the `_set_at`/`_set_by` companion fields update atomically with the value** (§6.7) — missing this silently breaks the conflict rule.
- **Feedback-loop guard:** changes authored by the bot's own writes must not re-arm TagAssigner (§6.5).

### 4.2 Inbound — Gemini Batch Results Webhook (new)

```
POST /webhooks/batch-results
```

Google shipped event-driven webhooks for the Gemini API on **2026-05-04**; the Batch API now lets you subscribe to **`batch.succeeded`** directly instead of polling `GET /operations`. So this endpoint is genuinely webhook-driven (no poller needed). But four implementation details differ from a naive "notification carries the results" model — and from our Chatwoot webhook — and all four matter:

- **Thin payload — a pointer, not the results.** The `batch.succeeded` event is a snapshot carrying status plus an `output_file_uri` (a `gs://` GCS URI), **not** the tags. The handler must then **fetch the JSONL from that GCS URI** (or call back into the API) to read each conversation's proposed labels. This GCS-fetch is an extra hop in the write-back path that the old §6.9 framing glossed.
- **Verification is Standard Webhooks, NOT Chatwoot HMAC.** Gemini webhooks follow the Standard Webhooks spec — `webhook-id` / `webhook-timestamp` / `webhook-signature` headers — a **separate verification path** from §6.8's Chatwoot HMAC. Two modes exist: *static* (project-level, symmetric HMAC) and *dynamic* (per-request, JWKS **asymmetric** signatures, with `user_metadata` for routing). **Use dynamic webhooks for the nightly batch:** you bind the endpoint when you submit the batch, and `user_metadata` lets you route which nightly run delivered. "Secure it like the Chatwoot one" is directionally right but not literal — it is a different scheme.
- **Reliability behaviors (must implement):** reject any payload whose `webhook-timestamp` is older than **5 minutes** (replay protection); respond **2xx immediately** and queue parsing internally (§6.1); **deduplicate on `webhook-id`**, since delivery is at-least-once. The durable queue (§6.2) already has the dedupe machinery — it just needs to key on `webhook-id`.
- **State tracking:** results may land minutes to hours after submission, possibly after a process restart. The durable queue (§6.2) tracks `submitted / awaiting-results` state so nothing is lost.

### 4.3 Internal — LLM call (Router → Gemini)

Gemini receives a structured JSON payload (conversation messages, all seven custom attributes as read-only context, InfoGatherer's `university_id`/`gender`, current label set) and returns structured JSON (the proposed label set only). The Router is the only caller; Gemini has no DB or Chatwoot access.

### 4.4 Trigger — idle scan (in-process sweep)

A frequent **in-process asyncio sweep** (every 1–2 min) scans for conversations meeting all start conditions, including `last_message_at < now() - interval '15 minutes'` (§5.2). **Use an in-process loop, not `pg_cron`** — consistent with V0's existing sweeps (`background/reprompt_sweep.py` and the daily integrity sweep); V0 has no `pg_cron` and we do not introduce it here. The sweep runs on a fixed schedule and *checks* the idle condition — no scheduler can "fire 15 minutes after last activity," it polls. **Idle is measured against `last_message_at`, not `last_updated_at`** (§5.2, §7.2): internal/self writes bump `last_updated_at` and would otherwise mask idleness.

---

## 5. Operation Layers & Triggering

### 5.1 The three-layer flow

```
Chatwoot webhook → ChatBot DB (conversations + messages)
                          │
              [trigger fires] → Script Router
                          │
         Router builds payload → Gemini (labels only)
                          │
         Gemini returns labels → Router resolves (4-list enforce,
              mutex, terminal guard, merge, deterministic attributes)
                          │
              Router → Chatwoot (write labels + 3 attributes)
                          │
         Chatwoot webhook → ChatBot DB (downstream sync)
```

### 5.2 Trigger conditions

**Message-triggered run** fires when *all* hold:
- ≥ 5 messages since last run (since creation if no prior run), **at least one inbound**,
- 15 minutes elapsed with no new *message* activity — measured as `last_message_at < now() - interval '15 minutes'` (**not** `last_updated_at`; see §7.2). Internal/self writes bump `last_updated_at` and must not reset the idle timer.

After a run, the counter resets — 5 *more* qualifying messages are needed before the next message-triggered run.

**Message counting rule:** InfoGatherer's outbound messages (`sender_type: infoGatherer`) **count** toward the 5-message threshold and **do** advance `last_message_at`. TagAssigner produces no messages (it only writes labels/attributes), so it never self-counts on the message axis. Its label/attribute *writes* echo back via the conversation-update webhook and are excluded from triggering by the feedback-loop guard (§6.5).

**Run caps (per conversation, per day, reset at Istanbul midnight):**
- **Automated:** max 5/day — up to 4 message-triggered + 1 guaranteed nightly run.
- **Manual:** max 5/day — separate counter, independent of the automated cap.

Stored as two counters on `conversations`: `auto_run_count`, `manual_run_count`.

### 5.3 Nightly scheduled run (23:40 Istanbul)

At 23:40 the Router checks each conversation for *any* difference since its last run. Eligible conversations are submitted via the **Batch API** (not the live endpoint) — this halves cost and sidesteps the RPM-spike that firing hundreds of simultaneous live calls would cause. The nightly run **reads full message history** (not just since-last-run) for best judgment, and **counts as one of the 5 automated runs**.

**Batch submission is not idempotent.** Sending the same batch-create request twice creates **two separate jobs** — so run-level idempotency must guard **submission**, not only result processing (§6.3): a retry at 23:40 must not double-submit the whole nightly sweep. **Bind the dynamic results webhook at submit time** (§4.2), carrying the run identity in `user_metadata` so the `batch.succeeded` event routes back to the right run.

Eligibility for the nightly run mirrors the message gate:
- never tagged + < 5 messages → **not** swept,
- never tagged + ≥ 5 messages → swept,
- previously tagged + ≥ 1 new message since last run → swept.

### 5.4 Manual `tag` trigger

A private note saying `tag`, **or** a label named `tag`, forces a run drawing from the separate `manual_run_count` (5/day). The manual trigger **bypasses** the 5-message/1-inbound gate. Manual + nightly runs read **full** history; normal message-triggered runs read **only since last run** (cost/context split).

- The `tag` **label** is removed by TagAssigner during the run.
- The `tag` **private note** stays in place.
- If a run is already `processing` for that conversation, a manual trigger is **rejected as redundant** (not queued) — the human can re-fire once it completes. This prevents a queued manual run from double-spending the manual cap.

### 5.5 Manual on/off

Both the automatic trigger and the manual-trigger option can be turned off independently (operational toggles).

---

## 6. Backend

### 6.1 Async request-reply (core pattern, inherited from V0)

No webhook handler blocks on a slow downstream call. Handlers do cheap bookkeeping and return `200` immediately; all waiting/retrying runs in detached background tasks. Railway's always-on process is what makes this safe (serverless would kill the background work).

### 6.2 Queue + throttle

All runs (daytime live + nightly batch) feed a durable `tag_assigner_queue` table. A worker drains it at a pace held under the Gemini RPM ceiling (client-side rate limiting). On a `429` from Gemini, exponential backoff + retry (same backoff family as V0's send-retry). The durable table (not an in-process queue) means a Railway restart mid-drain loses nothing.

### 6.3 Idempotency (mirrors V0)

One `run_id` (uuid) is generated when a run is *decided* (any trigger type), reused across any retries of that run. The Router writes a `tag_assigner_runs` row with `status: processing` **before** calling Gemini. A duplicate with the same `run_id` finds the row and no-ops. The key is **per-run**, not per-conversation.

**Batch-submission guard (§5.3):** because Gemini batch-job creation is **non-idempotent** (a repeated create makes a second job), the nightly submit step must record/check submission state under the `run_id` *before* calling the Batch API — the same "write the row, then act" discipline, applied to **submission** and not only to result write-back. The `submitted` state on `tag_assigner_queue` (§7.1) is what makes a 23:40 retry safe.

### 6.4 Partial-write recovery

If write-back to Chatwoot fails after some labels/attributes are written (e.g. a 502 mid-sequence): the run's `gemini_result` (cached jsonb on `tag_assigner_runs`) is retained, and recovery **retries the write-back only, using the cached result — Gemini is never re-called**. Exponential backoff, 3 attempts (~1s/2s/4s); on exhaustion, log `fatal` and leave for the next natural trigger (the cached result remains for any recovery tooling). Retryable errors only (timeouts/5xx/connection resets); a 4xx skips straight to fatal.

### 6.5 Feedback-loop guard

TagAssigner's own label/attribute writes echo back through Chatwoot as `conversation_updated` webhooks. If unhandled, they'd advance the conversation's activity clock → conversation goes idle again → re-triggers → loops. The guard: **changes authored by the bot are ignored for all triggering purposes** (no `last_message_at` advance, no run-arming). The separation of `last_message_at` (real message activity) from `last_updated_at` (any write, incl. self/internal — §7.2) is what makes this guard clean: a bot self-write can never look like lead activity. Two detection mechanisms, used in priority order (Chatwoot's conversation-update payload may or may not include the acting agent):

- **Primary — author attribution:** if the update's author is the `ChatBot` agent, it's a self-write → ignore for triggering.
- **Fallback — self-write record:** if the payload lacks author info, the Router records "about to write conversation X at time T" before each write; the webhook handler cross-checks incoming updates against recent self-writes to identify echoes.

CRM-authored changes are *not* `ChatBot` and therefore **do** count as real activity — correct, since a CRM-driven change is a genuine state change TagAssigner may want to react to. (The CRM needs its own equivalent "don't reprocess my own writes" guard on its side — flagged for the CRM team, out of scope here.)

### 6.6 Sync topology (single source of truth)

```
                    ┌─────────────┐
   writes  ───────► │   CHATWOOT  │ ◄─────── writes (humans, CRM-DB)
   (Router only,    │  (truth)    │
    for ChatBot)    └──────┬──────┘
                           │ webhook (only sync direction)
                           ▼
                    ┌─────────────┐
                    │  CHATBOT DB │  (downstream replica — never writes Chatwoot directly)
                    └─────────────┘
```

- **Chatwoot is the single source of truth** for labels/attributes.
- **ChatBot DB is strictly downstream** — it receives state from Chatwoot via webhook and may *read* Chatwoot for current state, but **never writes Chatwoot directly**.
- **The Script Router is the only path** by which the ChatBot system writes to Chatwoot.
- CRM DB and ChatBot DB are **separate** and never talk directly — they converge only through Chatwoot.

**Label-state read for the merge:** because the DB replica can lag Chatwoot by the webhook propagation delay, TagAssigner reads **current label state live from Chatwoot at run start** (not from the DB) before computing the merge. The extra API call is cheap relative to the Gemini call, and the terminal-label guard (§8) depends on an accurate "before" snapshot.

### 6.7 Option A — timestamp conflict rule (human vs. LLM)

For any field both TagAssigner and humans/CRM can write (notably `ilgili_otel`, and `ziyaret` which can be phone-booked by a human or chat-booked by the bot):

> TagAssigner may change the value **only if** there is chat evidence timestamped **strictly newer** than the value's last-set time. Otherwise the existing value stands, regardless of who set it.

This satisfies all three requirements simultaneously: TagAssigner can set the value when no human has; a human's correction survives the next run (no newer chat evidence → untouched); but a genuine later change in chat (newer than the human's edit) is still caught. Strict "newer-than" (not "≥") prevents TagAssigner churning its own value each run.

**Requires** companion columns `<field>_set_at` (timestamptz) and `<field>_set_by` (text: `tagAssigner`/`human`/`crm`) per conflict-managed field, updated **atomically with the value from any source** — including human/CRM changes arriving via webhook. The webhook handler updating the value without bumping `_set_at` silently breaks the rule.

### 6.8 Security

Same model as V0: **shared-secret verification at every trust boundary, with loud failure.**
- **Chatwoot → bot webhook:** HMAC signature, recomputed and compared, mismatch → `401` before parsing.
- **Gemini batch-results webhook:** **separate verification path — Standard Webhooks, NOT Chatwoot HMAC** (§4.2). `webhook-id` / `webhook-timestamp` / `webhook-signature` headers; dynamic mode uses JWKS **asymmetric** signatures. Same *discipline* (verify before parse, constant-time compare, loud failure), different *scheme*. Also reject timestamps older than 5 minutes and dedupe on `webhook-id`.
- **Internal Router calls:** shared-secret header.
- **Constant-time comparison always** (`hmac.compare_digest`, never `==`).
- **Secrets in env only**, never committed.
- **Auth failures log loudly** (`fatal`, distinct status) — mirroring the V0 `cron_secret` lesson, a misconfigured secret must scream on day one, not reject real traffic silently for weeks.

### 6.9 Deterministic Router writes (not LLM)

Three attributes are written by the Router, never by Gemini:
- **`university`** — Router resolves InfoGatherer's `university_id` (FK) → `universities.name` and writes the human-readable name to Chatwoot. (Never the raw UUID.)
- **`ogrenci_cinsiyet`** — Router maps InfoGatherer's `gender`: `male → Erkek`, `female → Kız`, unset → `Bilinmiyor`.
- **`ilgili_otel`** — Router resolves `hotels.id` → exact Chatwoot list string via `hotel_chatwoot_label_map` (the ten list values do **not** match `hotels.name`), written under the §6.7 conflict rule.

`university` and `ogrenci_cinsiyet` are authoritative from InfoGatherer's DB columns; TagAssigner **never writes back** to those columns, and Gemini cannot override them (it only sees them as context).

> **Net-new write path, not reuse.** In the current V0 codebase `assign_label` and `set_custom_attribute` exist in `chatwoot_client.py` but are **never called** — V0 writes flow-state and attributes to the **DB only** and pushes nothing to Chatwoot. So all three deterministic attribute pushes here — plus TagAssigner's label writes and InfoGatherer's `deal_awaiting` label (V0 Amendment §4) — are **build, not extend**. The first real Chatwoot label/attribute write path is created by this work; phase it before anything that depends on a push succeeding.

### 6.10 Env-governed modes

- **`TESTING_LIMITATIONS_MODE`** — restricts the entire chatbot, **TagAssigner included**, to act only on conversations from the 2 allowlisted phone numbers. When on, TagAssigner only queues/processes conversations whose contact is in the allowlist — a test run cannot fan out and tag live leads.
- **`INTEGRITY_CHECK_BYPASS`** — skips the boot-time health checks (§10) and launches the app even when the DB is in an unhealthy/incomplete state. Intended for testing against a knowingly-imperfect environment. When on, the referential-integrity and label-map checks that would normally block startup are passed over.

---

## 7. Database Structure

### 7.1 New tables

```sql
-- Per-run tracking: idempotency + cached result for write-back retry
CREATE TABLE tag_assigner_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid REFERENCES conversations(id) NOT NULL,
    created_at timestamptz DEFAULT now(),
    completed_at timestamptz,                 -- when write-back finished (may be hours after created_at for batch)
    trigger_type text CHECK (trigger_type IN ('message', 'scheduled', 'manual')),
    status text NOT NULL CHECK (status IN ('processing', 'success', 'failed')),
    gemini_result jsonb                       -- cached LLM output; enables write-back retry without re-calling Gemini
);

-- Per-request connection audit (distinct from per-run tracking)
CREATE TABLE tag_assigner_logs (
    log_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz DEFAULT now(),
    run_id uuid REFERENCES tag_assigner_runs(run_id),   -- ties every connection to its run
    conversation_id uuid REFERENCES conversations(id),
    request_type text CHECK (request_type IN ('db_read','db_write','webhook','api')),
    request_from text CHECK (request_from IN ('chatwoot','supabase','gemini','router')),
    request_to   text CHECK (request_to   IN ('chatwoot','supabase','gemini','router')),
    is_success boolean,
    status_code text,
    fail_reason text                          -- NULL unless failed
);

-- Deliberate read-replica of a mapping the CRM also holds (hotels.id ↔ exact Chatwoot list value).
-- Re-sync obligation on hotel add/rename. Superseded when CRM↔ChatBot linkage lands (post CRM-DB cleanup).
CREATE TABLE hotel_chatwoot_label_map (
    hotel_id uuid PRIMARY KEY REFERENCES hotels(id),
    chatwoot_list_value text UNIQUE NOT NULL  -- must EXACTLY match an ilgili_otel List option in Chatwoot
);

-- Durable queue feeding both daytime live runs and nightly batch
CREATE TABLE tag_assigner_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid REFERENCES conversations(id) NOT NULL,
    enqueued_at timestamptz DEFAULT now(),
    status text NOT NULL CHECK (status IN ('pending', 'processing', 'submitted', 'done', 'failed')),
    run_id uuid REFERENCES tag_assigner_runs(run_id),
    -- At most one 'pending' entry per conversation (dedupe); a 'processing' run does NOT block a new 'pending'.
    -- Enforce with a partial unique index:
    CONSTRAINT uq_pending_per_conversation EXCLUDE (conversation_id WITH =) WHERE (status = 'pending')
);
```

> Note: `deal_awaiting_universities` (membership list driving the InfoGatherer `deal_awaiting` flow) is defined in the **V0 Amendment Note**, since that flow lives in InfoGatherer, not TagAssigner.

### 7.2 Alterations to `conversations`

```sql
ALTER TABLE conversations
    -- Message-activity clock, SEPARATE from last_updated_at (§5.2, §6.5).
    -- last_updated_at bumps on EVERY write incl. internal/self-writes; last_message_at
    -- advances ONLY on real inbound/InfoGatherer message activity, so the 15-min idle
    -- trigger and the feedback-loop guard can both rely on it without self-writes masking idleness.
    ADD COLUMN last_message_at timestamptz,

    -- Run accounting (reset at Istanbul midnight by a daily job)
    ADD COLUMN auto_run_count   int4 DEFAULT 0,
    ADD COLUMN manual_run_count int4 DEFAULT 0,

    -- Custom-attribute columns (all seven; received from Chatwoot webhooks, all sent to Gemini as context).
    -- university_id and gender already exist from V0 — NOT redefined here.
    ADD COLUMN ilgili_otel    text,           -- conflict-managed (Option A)
    ADD COLUMN tasinma_tarihi date,           -- manual (read-only context for Gemini)
    ADD COLUMN kayip_nedeni   text,           -- manual
    ADD COLUMN oda_tiipi      text,           -- manual (key as configured in Chatwoot)
    ADD COLUMN butce          text,           -- manual

    -- Conflict-rule companions for ilgili_otel (Option A, §6.7)
    ADD COLUMN ilgili_otel_set_at timestamptz,
    ADD COLUMN ilgili_otel_set_by text CHECK (ilgili_otel_set_by IN ('tagAssigner','human','crm'));
```

> **Reconcile with existing V0 columns FIRST.** `conversations` already carries several columns from migration `001` that are currently **unwired** (written by no code): `labels text[]`, `custom_attributes jsonb`, `messages_since_last_run int4`, `time_since_last_run interval`, `daily_run_count int4`. Before adding the columns above, decide per column whether to **wire the existing one or supersede it** — in particular: (a) `daily_run_count` vs the new `auto_run_count`/`manual_run_count` split (the split wins; drop or repurpose the old one), and (b) whether the typed attribute columns above supersede the generic `custom_attributes jsonb` or coexist with it. Do **not** add parallel columns without resolving this, or two sources of truth will silently drift.

> **Pending your custom-attribute cleanup:** the four manual columns above reflect the current Chatwoot attributes (`tasinma_tarihi`, `kayip_nedeni`, `oda_tiipi`, `butce`). If the cleanup adds/removes/renames attributes, adjust this column list to match — one column per Chatwoot attribute. **Drive Gemini's context payload from config** (a column→attribute list read by `payload_builder.py`, §4.3), **not** a hardcoded set — then this pending cleanup is a config change, not a code change. Note `oda_tiipi` keeps its (apparent) typo deliberately: it must match the **live Chatwoot attribute key exactly** — verify against Chatwoot before committing, since a mismatch silently breaks sync.

---

## 8. Algorithms

### 8.1 Label resolution pipeline (per run)

```
1. Read CURRENT labels live from Chatwoot (not the DB replica — §6.6)
2. Send payload to Gemini → receive proposed label set
3. Enforce the four lists (§9):
     - drop any List-3 (never-touch) label from the proposed set
     - for List-2 (add-only): if a terminal label was present before but absent
       in Gemini's output → RE-ADD it (hard Router guard). Additions allowed.
4. Enforce mutually-exclusive groups (§9 List 4):
     - within each group, keep only one; for forward-progressions, latest-wins
5. Apply Option A conflict rule to any conflict-managed field
6. MERGE (not wholesale): change only what differs; leave untouched labels alone
7. Write result to Chatwoot via Router
8. Write deterministic attributes (university / ogrenci_cinsiyet / ilgili_otel)
```

### 8.2 Terminal-label hard guard (List 2)

After Gemini returns, for each of `kapora-alindi`, `sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak`: if present in the live "before" set but missing from Gemini's output, the Router re-adds it before writing. **Additions pass through; removals are blocked.** Only a human may remove these. (Prompt-level instruction backs this up, but the Router guard is the hard guarantee.)

### 8.3 Option A timestamp comparison

```
for each conflict-managed field:
    newest_evidence = newest in-chat signal for this field (e.g. latest lead msg
                      indicating a hotel preference, for ilgili_otel)
    if newest_evidence.created_at  >  <field>_set_at:   # STRICT
        allow TagAssigner to change the value
    else:
        leave the value untouched
```

### 8.4 University matching (inherited from V0 — unchanged, referenced here)

`normalize → exact match → alias table → Levenshtein ≤ 2 → no-match.` All layers retained. Normalization handles formatting (diacritics/case/suffixes); the alias table handles known abbreviations; Levenshtein ≤2 handles genuine typos. Dropping the fuzzy layer would make typo'd Istanbul universities fall into the out-of-Istanbul path (wrong, lead-losing) — see the V0 Amendment Note for how this interacts with `deal_awaiting`.

---

## 9. The Four Label Lists

This taxonomy is **architecture**, not just prompt content — the Router enforces it (List-3 stripping, List-2 hard guard, List-4 mutex) regardless of what the system prompt says. The system prompt will draw from these lists, but the Router is the enforcement backstop.

### LIST 1 — USABLE (TagAssigner may add and remove freely)

`pre-sinav`, `hazırlık`, `1-sinif`, `2-sinif`, `3-sinif`, `4-sinif`, `universitede`, `yerlesti`, `yeni-giris`, `erasmus`, `ogrenci`, `veli`, `ogrenci-degil`, `kyk-sonuc-bekliyor`, `ibb-yurdu-sonuc-bekliyor`, `universite-yurdu-sonuc-bekliyor`, `yatay_geçiş_bekliyor`, `univotelli`, `fiyat-soruyor`, `ilgilenmiyor`, `ziyaret`, `ziyaret-etti`, `ziyaret-etmedi`

(`ziyaret` is also conflict-managed under §6.7 — it can be phone-booked by a human or chat-booked by the bot.)

### LIST 2 — ADD-ONLY / NEVER REMOVE (hard Router guard; only humans remove)

`kapora-alindi`, `sozlesme-imzalandi`, `kayıp`, `ziyaret-ama-almayacak`

### LIST 3 — NEVER TOUCH (read-only: neither add nor remove)

- **Source/channel (CRM-owned):** `google-ads`, `google-maps`, `meta-ads`, `instagram`, `whatsapp`, `netgsm`, `sahibinden`, `manual`
- **Sales-action (not chat-observable — V2 unlock):** `aranacak`, `arandi`, `arandi-acmadi`, `bizi-aradi-konustuk`

### LIST 4 — MUTUALLY-EXCLUSIVE GROUPS

- **Academic year** (one only): `pre-sinav` / `hazırlık` / `1-sinif` / `2-sinif` / `3-sinif` / `4-sinif` / `universitede`
- **Enrollment progression** (forward, latest-wins): `yerlesti` → `yeni-giris`
- **Contact identity** (one only): `ogrenci` / `veli` / `ogrenci-degil`
- **Visit progression** (forward, latest-wins): `ziyaret` → `ziyaret-etti` / `ziyaret-etmedi` → `ziyaret-ama-almayacak`
- **Deal terminal** (one only): `sozlesme-imzalandi` / `kayıp`

### ROUTER-COMPUTED (deterministic — out of all four lists, never LLM-decided)

- `deal_awaiting` — set by **InfoGatherer** (V0 amendment), from `deal_awaiting_universities` membership. Not a TagAssigner concern.
- `university`, `ogrenci_cinsiyet`, `ilgili_otel` — written by the Router (§6.9).

---

## 10. Things to Look Out For

- **Health checks (boot + daily cron), bypassable via `INTEGRITY_CHECK_BYPASS`:**
  - every recommendable hotel has a row in `hotel_chatwoot_label_map`, **and** every mapped `chatwoot_list_value` exactly matches a live Chatwoot `ilgili_otel` List option (the exact-string match is hand-typed and fragile — check it mechanically);
  - the V0 referential-integrity sweep (every hotel has `response_schemas`, every `response_id` resolves, sentinel rows wired) — now also covering `DEAL-AWAITING-STATE` (see V0 amendment);
  - fail loudly (`fatal`) on any orphan; refuse boot unless `INTEGRITY_CHECK_BYPASS` is on.
- **The `_set_at`/`_set_by` atomic-update discipline (§6.7)** is the single most error-prone spot — a webhook handler updating a conflict-managed value without bumping its timestamp silently breaks human-vs-LLM precedence.
- **`hotel_chatwoot_label_map` is a deliberate duplicate** of a CRM-held mapping. Re-sync on every hotel add/rename. Retired when CRM↔ChatBot linkage lands.
- **Model ID drift** — Gemini's retirement cadence is fast; keep `MODEL_ID` an env constant and reconfirm before any redeploy.
- **Two run-reset clocks differ:** TagAssigner run caps reset at Istanbul midnight; Gemini's own RPD resets at Pacific midnight. Not a problem at this volume, just not a coincidence to rely on.
- **`TESTING_LIMITATIONS_MODE` must gate TagAssigner too** — otherwise a test run tags live leads.
- **Turkish-character labels must round-trip verbatim.** Several labels carry Turkish characters (`hazırlık`, `kayıp`, `yatay_geçiş_bekliyor`). The merge's before/after diff (§8.1) and the List-2 terminal guard (§8.2) compare label strings **exactly** — if Chatwoot slug-normalizes labels on read (e.g. `kayıp` → `kayip`), every Turkish-character label mis-compares and the guard mis-fires on every run. **Test an actual read-back from live Chatwoot before trusting the merge/guard logic.**
- **`last_message_at` vs `last_updated_at` separation** (§5.2, §6.5, §7.2) is load-bearing for both the idle trigger and the feedback-loop guard — if the message-ingest path forgets to advance `last_message_at`, conversations never go idle and never trigger; if an internal write advances it by mistake, the bot re-triggers itself.

---

## 11. V2 Roadmap

V2's defining capability is **sales-action awareness** — giving the ChatBot visibility into what the sales team did offline (calls, phone-booked visits, CRM state). This single capability unlocks a coherent set of deferred items:

- **Sales-action labels become writable:** `aranacak` (call queue), `arandi` / `arandi-acmadi` / `bizi-aradi-konustuk`. Today read-only because the LLM can't see calls; with NetGSM-webhook or CRM-API visibility, TagAssigner can set them correctly.
- **Fuller `ilgili_otel` accuracy** — the LLM could reconcile chat-expressed preference against CRM-recorded preference.
- **CRM↔ChatBot linkage** retires the `hotel_chatwoot_label_map` duplicate (single source of truth restored), pending the CRM DB cleanup that makes that DB safe to depend on.
- **FallBack** (the V2 LLM recovery layer from the V0 plan) also lands in this phase.

**Design hook for V2 (do this now):** keep `payload_builder.py` modular so "add a CRM/sales-action context block" is a clean insertion, not a rewrite. That five-minute structural choice now saves a refactor later.
