# Univotel TagAssigner V1 — Step-by-Step Phase Plan

**Governed by:** `tagassigner-build-brief.md` (wins all conflicts), then `tagassigner-v1-spec.md`, `v0-amendment-deal-awaiting.md`.
**Status:** Planning. No code is written until explicitly authorized; each phase ends at a review gate.

## Conventions (apply to every phase)

- **Review gate per phase:** stop and show the diff before the next phase starts.
- **Migrations are handed over, never auto-applied.** I produce the `.sql`; you run it. All `ALTER`s are written idempotent (`IF NOT EXISTS`) against the populated prod schema.
- **Unverified-against-live-Chatwoot values** become a marked `TODO` **plus** a boot/daily health-check assertion — never a silent guess.
- **Pattern reuse:** in-process `asyncio` sweeps mirror `background/reprompt_sweep.py`; retry ladders mirror `background/send_retry.py` (1s/2s/4s); idempotency mirrors `layers/rec_engine.py` (write the row, then act).
- **Both env modes gate TagAssigner:** `TESTING_LIMITATIONS_MODE` (allowlist only), `INTEGRITY_CHECK_BYPASS` (skip boot checks).

## Column reconciliation (recommended defaults — confirm before Phase 0)

| Existing column (migration 001) | Decision | Rationale |
|---|---|---|
| `daily_run_count int4` | **Drop** | Unwired; replaced by `auto_run_count`/`manual_run_count` split. |
| `custom_attributes jsonb` | **Superseded** by typed columns | Managed fields need `_set_at`/`_set_by` companions + real types. Keep only as optional raw passthrough. |
| `labels text[]` | **Wire** | Becomes the downstream replica of Chatwoot labels (§4.1 sync target). Live merge still reads Chatwoot (§6.6). |
| `messages_since_last_run int4` | **Wire** | Drives the 5-message gate. |
| `time_since_last_run interval` | **Drop** | Redundant once `last_message_at` exists. |

---

## Phase 0 — Schema & seed

**Goal:** every table/column/seed TagAssigner and the `deal_awaiting` amendment depend on, applied and integrity-checkable.
**Depends on:** column-reconciliation sign-off; the 10 `hotel_chatwoot_label_map` values (or Chatwoot access).

**Migrations (renumbered 006+):**
1. `006_deal_awaiting.sql` — `deal_awaiting_universities` table; `DEAL-AWAITING-STATE` sentinel hotel (`…0002`); its `canned_responses` row; `response_schemas` wiring. (V0 Amendment §5.)
2. `007_tagassigner_runs_and_logs.sql` — `tag_assigner_runs`, `tag_assigner_logs` (spec §7.1).
3. `008_conversations_columns.sql` —
   - `ADD last_message_at timestamptz` (brief #3);
   - `ADD auto_run_count`, `manual_run_count`; **`DROP daily_run_count`, `DROP time_since_last_run`** (per reconciliation);
   - attribute columns `ilgili_otel`, `tasinma_tarihi`, `kayip_nedeni`, `oda_tiipi`, `butce`;
   - conflict companions `ilgili_otel_set_at`, `ilgili_otel_set_by`.
4. `009_hotel_chatwoot_label_map.sql` — table + **seed of the 10 rows** (TODO-guarded until verified against live Chatwoot).
5. `010_tag_assigner_queue.sql` — queue table + partial-unique dedupe index (`EXCLUDE ... WHERE status='pending'`).

**Steps:** write the five files; add `DEAL_AWAITING_STATE_ID = UUID('…0002')` constant alongside `GLOBAL_NULL_STATE_ID`; extend `db/models.py` with the new row models; add query stubs in `db/queries.py` for the new tables (no behavior yet).

**Exit criteria:** files apply cleanly on a fresh DB and idempotently on a populated one; `\d conversations` shows the reconciled column set; sentinel + label-map rows present. (Verified by you applying to dev, or by the Phase 7 integrity check once wired.)

**Blockers:** the 10 list values; sign-off on the two `DROP`s.

---

## Phase 1 — `deal_awaiting` in InfoGatherer (no LLM) + the real Chatwoot write path

**Goal:** ship the deterministic `deal_awaiting` outcome — and, because it's net-new (brief #2), build the first working Chatwoot label-write here.
**Depends on:** Phase 0 (`006`).

**Steps:**
1. **Real label write:** make `chatwoot_client.assign_label` actually used; add `get_labels()` + `set_labels(full_set)` (Chatwoot POST replaces the set — needed later for merge). Wrap in a `send_with_retry`-style ladder.
2. **Membership query:** `queries.is_deal_awaiting_university(university_id)` against `deal_awaiting_universities`.
3. **Shared helper** `_resolve_post_match(...)`: after a successful university match, branch — member → set `deal_awaiting` label + send `DEAL-AWAITING-STATE` via `_send_hotel_responses(DEAL_AWAITING_STATE_ID)` + go terminal; non-member → existing `awaiting_gender` path.
4. **Wire the helper into all three match sites** in `layers/info_gatherer.py`: `_handle_new` (~L282), `_handle_awaiting_university` (~L330), `_handle_clarification` (~L357).
5. Extend `health/integrity_check.py` to assert `DEAL-AWAITING-STATE` is wired (mirror `global_null_state_is_wired`).

**Exit criteria:** unit tests — a `deal_awaiting` member university sets the label, sends the canned response, terminates; a non-member proceeds to gender; an out-of-Istanbul (no match) still hits `/istanbul`. Live label write confirmed against dev Chatwoot.

**Blockers:** dev Chatwoot for the live-write smoke test; `deal_awaiting_msg` copy (currently a TODO in the amendment).

---

## Phase 2 — Router I/O foundation (no Gemini)

**Goal:** all the deterministic I/O the Router brokers, end-to-end, before any LLM is involved. Run with `TESTING_LIMITATIONS_MODE=on`.
**Depends on:** Phase 1 (write path).

**Steps:**
1. `security.py` — add `verify_standard_webhook()` (Standard Webhooks: `webhook-id`/`webhook-timestamp`/`webhook-signature`, 5-min replay reject, JWKS for dynamic). **Separate path from Chatwoot HMAC** (brief #1).
2. `tagassigner/attribute_resolver.py` — `university` (id→`universities.name`), `ogrenci_cinsiyet` (`male→Erkek`/`female→Kız`/unset→`Bilinmiyor`), `ilgili_otel` (id→`hotel_chatwoot_label_map`). Pushes via `chatwoot_client` (first-ever attribute push — brief #2).
3. `tagassigner/conflict.py` — Option A strict-newer rule; reads/writes `ilgili_otel_set_at`/`_set_by`.
4. **Extend `webhooks/chatwoot.py`** with a `conversation_updated` event branch: (a) sync labels/attributes into `conversations` columns, **atomically bumping `_set_at`/`_set_by`** (§6.7); (b) feedback-loop guard (author = `ChatBot` → ignore; else self-write record fallback); (c) advance `last_message_at` only on real message activity; (d) capture the manual `tag` label / `tag` private note.
5. `tagassigner/router.py` — skeleton brokering DB reads + Chatwoot writes (no Gemini call yet); `tag_assigner_logs` per-connection audit.

**Exit criteria:** a simulated `conversation_updated` webhook updates the right columns with `_set_at`/`_set_by`; a bot-authored echo does **not** advance `last_message_at`; attribute resolver writes the three attributes to dev Chatwoot correctly; Standard-Webhooks verifier passes/rejects on crafted payloads.

**Blockers:** `oda_tiipi` exact key; whether `conversation_updated` carries the acting agent; `chatwoot_bot_agent_id` = the `ChatBot` agent.

---

## Phase 3 — Label resolution engine (pure, heavily tested)

**Goal:** the four-list enforcement as a pure function, fully unit-tested, before any live call.
**Depends on:** none (pure logic); can run parallel to Phase 2.

**Steps:** `tagassigner/label_resolver.py`, encoding the four lists (§9) as data:
1. Drop List-3 (never-touch) from Gemini's proposal.
2. List-2 terminal hard-guard: re-add any of `kapora-alindi`/`sozlesme-imzalandi`/`kayıp`/`ziyaret-ama-almayacak` present in the live "before" set but missing from output (additions pass, removals blocked).
3. List-4 mutex: one-per-group; forward-progressions latest-wins.
4. Option A hook for conflict-managed fields.
5. **Merge** (change only diffs; leave untouched labels alone).

**Exit criteria:** exhaustive unit tests covering each list, each mutex group, terminal re-add, merge-not-replace, and **Turkish-character labels** (`hazırlık`, `kayıp`, `yatay_geçiş_bekliyor`) — with a fixture for both verbatim and slug-normalized Chatwoot forms so we're ready whichever way #7 resolves.

**Blockers:** none to build; the Turkish-normalization answer (#7) decides which comparison form is canonical.

---

## Phase 4 — Gemini integration (single manual trigger)

**Goal:** first live LLM call, end-to-end, behind one manual `tag` trigger, allowlist-gated.
**Depends on:** Phases 2 + 3.

**Steps:**
1. `config.py` + `.env.example` — `MODEL_ID=gemini-2.5-flash-lite` (env constant), `GEMINI_API_KEY`. Add `google-genai` to `requirements.txt`.
2. `tagassigner/payload_builder.py` — assemble the structured payload; **attribute list read from config**, not hardcoded (brief #6); keep the structure modular for the V2 CRM block.
3. `tagassigner/gemini_client.py` — live call, structured JSON in/out (labels only).
4. Wire `router.py`: live labels → `label_resolver` → write-back → deterministic attributes (§8.1 pipeline). `run_id` written `processing` before the call; `gemini_result` cached for write-back retry.
5. Partial-write recovery: retry write-back only from cache, 1s/2s/4s, then `fatal`.

**Exit criteria:** firing the `tag` trigger on an allowlisted dev conversation produces a sane label set, enforced and merged correctly, with the three attributes written; re-firing the same `run_id` no-ops; a forced mid-write 502 recovers from cache without re-calling Gemini.

**Blockers:** Gemini API key + billing-enabled project.

---

## Phase 5 — Triggers, queue, caps

**Goal:** automated daytime operation.
**Depends on:** Phase 4.

**Steps:**
1. `tagassigner/queue.py` — durable `tag_assigner_queue` drain, client-side throttle under RPM ceiling, 429 backoff; restart-safe.
2. `tagassigner/trigger.py` — in-process idle-scan sweep (1–2 min), gate = ≥5 messages (≥1 inbound) **and** `last_message_at < now()-15min`; manual `tag` trigger (bypasses gate, separate cap, reject-if-`processing`).
3. Message counting: wire `messages_since_last_run`; reset on run.
4. Run caps: `auto_run_count`/`manual_run_count`; **Istanbul-midnight reset as an in-process daily loop** (brief #4), not pg_cron.
5. Operational toggles (§5.5): independent on/off for automatic and manual triggers (env-backed).

**Exit criteria:** a conversation crossing the gate triggers exactly one run; counter resets after; caps enforced; a `processing` conversation rejects a manual re-fire; restart mid-drain loses nothing.

**Blockers:** none new.

---

## Phase 6 — Nightly batch

**Goal:** 23:40 Istanbul batch sweep via Gemini Batch API + verified webhook completion.
**Depends on:** Phase 5.

**Steps:**
1. `tagassigner/batch_client.py` — eligibility sweep (§5.3), submit via Batch API **with dynamic-webhook binding at submit time** (`user_metadata` routes the run). **Submission guarded for idempotency** (brief #1) — record `submitted` under `run_id` before the create call so a 23:40 retry can't double-submit.
2. `webhooks/batch_results.py` — `POST /webhooks/batch-results`: Standard-Webhooks verify → 2xx immediately → async parse → **fetch JSONL from the `gs://` `output_file_uri`** → standard write-back path. Dedupe on `webhook-id`.
3. Queue states `submitted` / `awaiting-results` so async completion (possibly post-restart) is never lost.

**Exit criteria:** a submitted batch's `batch.succeeded` is verified, de-duped, fetched from GCS, and written back; a replayed/old webhook is rejected; a duplicated submit attempt is suppressed.

**Blockers:** GCP project + billing, GCS bucket, public Railway URL for the dynamic-webhook binding.

---

## Phase 7 — Health checks & hardening

**Goal:** boot/daily integrity covering all new invariants; full test pass.
**Depends on:** Phases 0–6.

**Steps:**
1. Extend `health/integrity_check.py`: every recommendable hotel has a `hotel_chatwoot_label_map` row **and** each `chatwoot_list_value` exactly matches a live Chatwoot `ilgili_otel` option (mechanical check — brief #7); `DEAL-AWAITING-STATE` wired; existing V0 sweep retained. Fail `fatal` unless `INTEGRITY_CHECK_BYPASS`.
2. End-to-end tests across message-trigger, manual, and nightly paths.
3. Confirm `TESTING_LIMITATIONS_MODE` gates queue/processing, not just webhook ingress.

**Exit criteria:** boot refuses on any orphan/mismatch (bypassable); e2e green; a test run cannot fan out to non-allowlisted leads.

**Blockers:** live Chatwoot read for the exact-string label-map check.

---

## Cross-cutting: new env vars (added incrementally)

`MODEL_ID`, `GEMINI_API_KEY`, `GEMINI_WEBHOOK_*` (Standard Webhooks / JWKS), `GCS_OUTPUT_BUCKET`, `AUTOMATIC_TRIGGER_ENABLED`, `MANUAL_TRIGGER_ENABLED`. All in `.env.example`, secrets in env only.

## Open blockers (consolidated)

| Item | Needed by | Source |
|---|---|---|
| Column-reconciliation sign-off (2 drops) | Phase 0 | you |
| 10 `hotel_chatwoot_label_map` values | Phase 0 / 7 | live Chatwoot |
| `deal_awaiting_msg` copy | Phase 1 | you |
| `oda_tiipi` exact key | Phase 2 | live Chatwoot |
| `conversation_updated` includes acting agent? + `ChatBot` agent id | Phase 2 | Chatwoot config |
| Turkish-label normalization behavior | Phase 3 / 7 | live Chatwoot |
| Gemini API key + billing | Phase 4 | GCP |
| GCS bucket + public webhook URL | Phase 6 | GCP / Railway |
| Dev DB + dev Chatwoot for smoke tests | Phases 1–7 | infra |
