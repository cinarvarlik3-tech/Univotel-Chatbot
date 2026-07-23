-- Spec 031: InfoGatherer live-test readiness (history backfill marker, abstain buckets, automation sender).

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS history_backfilled_at timestamptz;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS infogatherer_abstain_reason text
        CHECK (infogatherer_abstain_reason IN (
            'prior_history',
            'backfill_failed',
            'outbound_first'
        ));

ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS messages_sender_type_check;
ALTER TABLE messages
    ADD CONSTRAINT messages_sender_type_check
        CHECK (sender_type IN ('user','contact','infoGatherer','fallBack','automation'));
