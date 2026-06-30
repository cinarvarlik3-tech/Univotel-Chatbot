# Univotel TagAssigner V1 — Corrections & Build-Order Brief

**Status:** Governing document. **Where this brief conflicts with `tagassigner-v1-spec.md`, `v0-amendment-deal-awaiting.md`, or the codebase audit, this brief wins.**
**Read before implementing.** The audit is accurate except finding #1, which predates a Gemini API change (corrected below).

---

## 1. Gemini Batch completion is webhook-based — do NOT switch to polling

Google shipped event-driven webhooks for the Gemini API on **2026-05-04**; the Batch API supports a `batch.succeeded` event. The spec's `/webhooks/batch-results` endpoint is correct. Implement with these specifics:

- **Thin payload:** the webhook delivers a pointer, not results — a `gs://` `output_file_uri`. The handler must **fetch the JSONL output from that GCS URI**; tags are not inline.
- **Use dynamic webhooks** (bound per-request at batch-submit time via `webhook_config`), not a static project-level webhook — so `user_metadata` routes which nightly run completed.
- **Verification is Standard Webhooks, NOT the Chatwoot HMAC.** Headers: `webhook-id` / `webhook-timestamp` / `webhook-signature`. Dynamic webhooks use **JWKS asymmetric signatures** — a separate verification path; do not reuse Chatwoot HMAC code.
- **Reliability:** reject payloads older than **5 minutes** (replay protection via `webhook-timestamp`); respond **2xx immediately**, parse asynchronously; **dedupe on `webhook-id`** (at-least-once delivery) using the durable queue.
- **Guard batch submission for idempotency:** Gemini batch-job creation is **not idempotent** — submitting twice creates two jobs. Run-level idempotency must cover the 23:40 **submission**, not just result processing, or a retry double-submits the nightly sweep.

## 2. The codebase writes to Chatwoot nowhere today — three "extend" tasks are net-new builds

`assign_label` and `set_custom_attribute` in `chatwoot_client.py` are **dead code** (defined, never called). Flow state (`human_needed`, `stopped`) is written as DB `flow_state` values, not Chatwoot labels. Build a real Chatwoot write path first; these are **net-new, not reuse**:

- InfoGatherer setting the `deal_awaiting` label (V0 amendment).
- The deterministic attribute push (`university`, `ogrenci_cinsiyet`, `ilgili_otel`) — first-ever push of these to Chatwoot.
- TagAssigner's label writes — Chatwoot's label POST **replaces the full set** (required for merge/removal); today there's no label-fetch and `assign_label` only adds.

## 3. Add a dedicated `last_message_at` column

V0 bumps `last_updated_at` on every state write, internal or not. The 15-minute-idle trigger needs time-since-last-message, and the feedback-loop guard needs to tell message activity from internal writes. Add `conversations.last_message_at`, set **only on real inbound/outbound messages**. Do this in the schema phase — the idle trigger and feedback-loop guard both depend on it.

## 4. Use in-process asyncio sweeps, not pg_cron

V0 has no `pg_cron`; it uses in-process asyncio sweep loops (`reprompt_sweep.py`, `integrity_check.py`). Implement TagAssigner's idle-scan and the Istanbul-midnight reset as in-process loops mirroring that pattern. **Ignore all `pg_cron` framing.**

## 5. Reconcile existing unwired columns — don't blindly add parallel ones

`conversations` already has `labels`, `custom_attributes` (jsonb), `messages_since_last_run`, `time_since_last_run`, `daily_run_count` — all present but unwired. Before adding `auto_run_count`/`manual_run_count` and the per-attribute columns, decide **per column: wire the existing one or supersede it.** Specifically decide whether the typed attribute columns replace `custom_attributes` jsonb, and whether `auto_run_count`/`manual_run_count` replace `daily_run_count`. Don't leave two parallel sets.

## 6. Drive Gemini's context payload from config, not a hardcoded column list

The custom-attribute set is pending a cleanup, so the manual attribute columns (`tasinma_tarihi`, `kayip_nedeni`, `oda_tiipi`, `butce`) may change. `payload_builder.py` must read the attribute list from config so a cleanup needs no code change.

## 7. Verify two data-fidelity items against live Chatwoot before trusting sync/merge

- **`oda_tiipi`** is spelled with the double-i to match Chatwoot's actual attribute key. Confirm the live key matches exactly; a mismatch silently breaks attribute sync.
- Several labels carry **Turkish characters** (`hazırlık`, `kayıp`, `yatay_geçiş_bekliyor`). Confirm Chatwoot stores/returns them **verbatim with no slug-normalization**. If it normalizes, the merge before/after comparison and the terminal-label hard-guard mis-fire — adjust the comparison to Chatwoot's canonical form.

## 8. Renumber migrations

Existing migrations stop at `005`; the spec used `010+`. New migrations renumbered to **006+** in dependency order:

| # | File | Notes |
|---|------|-------|
| 006 | `006_deal_awaiting.sql` | V0 amendment: `deal_awaiting_universities` + `DEAL-AWAITING-STATE` sentinel + `response_schemas` wiring |
| 007 | `007_tagassigner_runs_and_logs.sql` | `tag_assigner_runs`, `tag_assigner_logs` |
| 008 | `008_conversations_columns.sql` | `last_message_at` + run counters + attribute columns (reconcile per #5) |
| 009 | `009_hotel_chatwoot_label_map.sql` | seed the 10 list values; verify against live Chatwoot |
| 010 | `010_tag_assigner_queue.sql` | references 007's `run_id`; partial-unique dedupe index |

---

## Build order (each phase shippable/testable before the next)

0. **Schema & seed** — all new tables, `last_message_at`, column reconciliation (#5), `deal_awaiting` amendment migration, `hotel_chatwoot_label_map` seed (verify the 10 list values against live Chatwoot).
1. **`deal_awaiting` in InfoGatherer** (no LLM) — build the real label-write path here.
2. **Router I/O foundation** — Chatwoot label-fetch + full-set write, attribute resolver + conflict rule, `conversation_updated` webhook branch (sync + feedback-loop guard + manual-trigger capture). Run with `TESTING_LIMITATIONS_MODE` on.
3. **Label resolution engine** — pure, heavily unit-tested function (4-list enforcement, mutex/latest-wins, terminal hard-guard, merge) before any live calls.
4. **Gemini integration** — `MODEL_ID` env constant (`gemini-2.5-flash-lite`), config-driven payload builder, live calls behind a single manual `tag` trigger first.
5. **Triggers, queue, caps** — durable queue drain + throttle, idle-scan loop, message-counting, Istanbul-midnight reset, `run_id` idempotency, partial-write recovery.
6. **Nightly batch** — submit with dynamic-webhook binding, the verified batch-results handler (per #1), `submitted`/`awaiting-results` queue states.
7. **Health checks & hardening** — `hotel_chatwoot_label_map` completeness + exact-string match against live Chatwoot options, full integrity sweep, end-to-end tests.

Both env modes (`TESTING_LIMITATIONS_MODE`, `INTEGRITY_CHECK_BYPASS`) already exist in `config.py` and **must gate TagAssigner too.**
