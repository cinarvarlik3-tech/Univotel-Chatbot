-- 019_ilgili_otel_set_by_infogatherer.sql
-- Allow infoGatherer as ilgili_otel_set_by (spec 018 §6).
-- Migration 017 added infoGatherer for university_set_by / gender_set_by only;
-- RecEngine callback writes ilgili_otel with set_by=infoGatherer at flow completion.

ALTER TABLE conversations
    DROP CONSTRAINT IF EXISTS conversations_ilgili_otel_set_by_check;

ALTER TABLE conversations
    ADD CONSTRAINT conversations_ilgili_otel_set_by_check
        CHECK (ilgili_otel_set_by IN ('tagAssigner', 'infoGatherer', 'human', 'crm'));
