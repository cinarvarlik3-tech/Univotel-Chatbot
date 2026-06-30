-- 007_tagassigner_runs_and_logs.sql
-- Per-run tracking (idempotency + write-back cache) and per-connection audit for TagAssigner.

CREATE TABLE IF NOT EXISTS tag_assigner_runs (
    run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid REFERENCES conversations(id) NOT NULL,
    created_at       timestamptz DEFAULT now(),
    completed_at     timestamptz,
    trigger_type     text CHECK (trigger_type IN ('message', 'scheduled', 'manual')),
    status           text NOT NULL CHECK (status IN ('processing', 'success', 'failed')),
    gemini_result    jsonb,
    -- Nightly batch fields
    batch_job_name   text,        -- Google Batch API resource name; NULL for live (daytime) runs
    batch_webhook_id text UNIQUE  -- Standard Webhooks webhook-id; used for at-most-once dedup
);

CREATE TABLE IF NOT EXISTS tag_assigner_logs (
    log_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz DEFAULT now(),
    run_id          uuid REFERENCES tag_assigner_runs(run_id),
    conversation_id uuid REFERENCES conversations(id),
    request_type    text CHECK (request_type IN ('db_read','db_write','webhook','api')),
    request_from    text CHECK (request_from IN ('chatwoot','supabase','gemini','router')),
    request_to      text CHECK (request_to   IN ('chatwoot','supabase','gemini','router')),
    is_success      boolean,
    status_code     text,
    fail_reason     text
);
