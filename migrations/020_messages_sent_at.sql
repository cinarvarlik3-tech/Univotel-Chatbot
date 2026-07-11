-- Spec 020.2 — cadence-based debounce.
-- Records the true customer send time from the Chatwoot webhook payload,
-- distinct from created_at (which is stamped when our pipeline persists the row
-- and is therefore contaminated by processing latency).

BEGIN;

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS sent_at timestamptz;

COMMIT;
