-- 017_tagassigner_attributes.sql
-- set_by companions for bot-writable fields + info-check router state (spec 018).

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS university_set_at  timestamptz,
    ADD COLUMN IF NOT EXISTS university_set_by  text
        CHECK (university_set_by IN ('tagAssigner', 'infoGatherer', 'human')),
    ADD COLUMN IF NOT EXISTS gender_set_at      timestamptz,
    ADD COLUMN IF NOT EXISTS gender_set_by      text
        CHECK (gender_set_by IN ('tagAssigner', 'infoGatherer', 'human')),
    ADD COLUMN IF NOT EXISTS oda_tiipi_set_at   timestamptz,
    ADD COLUMN IF NOT EXISTS oda_tiipi_set_by   text
        CHECK (oda_tiipi_set_by IN ('tagAssigner', 'human'));

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS info_check_fingerprint            text,
    ADD COLUMN IF NOT EXISTS info_check_added_at               timestamptz,
    ADD COLUMN IF NOT EXISTS info_check_suppressed_fingerprint text;
