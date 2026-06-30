-- 008_conversations_columns.sql
-- Adds last_message_at, run counters, attribute columns with Option-A conflict companions.
-- Drops two unwired V0 columns (daily_run_count, time_since_last_run) that are superseded.

-- Drop unwired V0 columns (no code reads/writes these; replaced by the split below)
ALTER TABLE conversations DROP COLUMN IF EXISTS daily_run_count;
ALTER TABLE conversations DROP COLUMN IF EXISTS time_since_last_run;

-- Real message-activity clock — advances ONLY on actual inbound/outbound messages,
-- NOT on internal state writes. The 15-min idle trigger and feedback-loop guard depend on this.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_message_at timestamptz;

-- Per-conversation daily run caps, reset at Istanbul midnight (UTC+3) by an in-process sweep.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS auto_run_count   int4 NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS manual_run_count int4 NOT NULL DEFAULT 0;

-- Chatwoot custom-attribute columns (typed, source of truth for managed fields;
-- the existing custom_attributes jsonb stays as a raw passthrough/mirror).
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS ilgili_otel    text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tasinma_tarihi date;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kayip_nedeni   text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS oda_tiipi      text;  -- key matches live Chatwoot; verify before use
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS butce          text;

-- Option A conflict companions for ilgili_otel (§6.7 of tagassigner-v1-spec.md).
-- Must update ATOMICALLY with the value from any write source — including webhook syncs.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS ilgili_otel_set_at timestamptz;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS ilgili_otel_set_by text
    CHECK (ilgili_otel_set_by IN ('tagAssigner', 'human', 'crm'));
