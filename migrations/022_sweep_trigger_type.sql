-- 022_sweep_trigger_type.sql
-- Spec 021: manual sweep operations enqueue with trigger_type='sweep'.
-- Extend CHECK constraints on queue and runs tables.

ALTER TABLE tag_assigner_queue
    DROP CONSTRAINT IF EXISTS tag_assigner_queue_trigger_type_check;

ALTER TABLE tag_assigner_queue
    ADD CONSTRAINT tag_assigner_queue_trigger_type_check
        CHECK (trigger_type = ANY (ARRAY[
            'message'::text,
            'scheduled'::text,
            'manual'::text,
            'sweep'::text
        ]));

ALTER TABLE tag_assigner_runs
    DROP CONSTRAINT IF EXISTS tag_assigner_runs_trigger_type_check;

ALTER TABLE tag_assigner_runs
    ADD CONSTRAINT tag_assigner_runs_trigger_type_check
        CHECK (trigger_type = ANY (ARRAY[
            'message'::text,
            'scheduled'::text,
            'manual'::text,
            'sweep'::text
        ]));
