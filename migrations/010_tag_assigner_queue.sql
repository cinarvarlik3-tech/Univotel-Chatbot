-- 010_tag_assigner_queue.sql
-- Durable queue feeding both daytime live runs and nightly batch.
-- Depends on 007_tagassigner_runs_and_logs.sql (run_id FK).

CREATE TABLE IF NOT EXISTS tag_assigner_queue (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid REFERENCES conversations(id) NOT NULL,
    enqueued_at     timestamptz DEFAULT now(),
    status          text NOT NULL CHECK (status IN (
        'pending', 'processing', 'submitted', 'awaiting_results', 'done', 'failed'
    )),
    run_id          uuid REFERENCES tag_assigner_runs(run_id),
    trigger_type    text CHECK (trigger_type IN ('message', 'scheduled', 'manual'))
);

-- At most one 'pending' entry per conversation.
-- A 'processing'/'submitted' item does NOT block a new 'pending'.
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_per_conversation
    ON tag_assigner_queue (conversation_id) WHERE (status = 'pending');
