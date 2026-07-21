-- 029_parent_default_campus.sql
-- A4 (TAGASSIGNER_ACCURACY_FIXES_PLAN.md) — curated default-campus map. For a SMALL,
-- explicitly curated set of multi-campus parent universities, a bare parent mention
-- with no resolvable campus writes a specific default campus instead of withholding
-- (bilinmiyor-kampus). This is NOT a blanket multi-campus rule — most multi-campus
-- schools genuinely distribute students across campuses and must keep withholding;
-- only the two rows below are exempted, by explicit product decision (2026-07-20).
--
-- İstanbul Üniversitesi -> Beyazıt: the parent has a plain, campus-agnostic Chatwoot
-- list value ("İstanbul Üniversitesi") that already exists and was simply unused.
-- Boğaziçi Üniversitesi -> Ana Kampüs: no plain Boğaziçi list value exists; Ana Kampüs
-- is the historic main campus and the reasonable default reading of a bare mention.

BEGIN;

CREATE TABLE IF NOT EXISTS parent_university_default_campus (
    parent_university_id uuid PRIMARY KEY REFERENCES parent_universities(id),
    university_id uuid NOT NULL REFERENCES universities(id)
);

INSERT INTO parent_university_default_campus (parent_university_id, university_id)
VALUES
    -- İstanbul Üniversitesi -> İÜ Beyazıt Kampüsü ("İstanbul Üniversitesi" list value)
    ('c51006fd-bbde-410d-1a06-8c92182baba9'::uuid, 'bceb53ee-580f-4265-a27d-716dae21c9eb'::uuid),
    -- Boğaziçi Üniversitesi -> Ana Kampüs ("Boğaziçi - Ana Kampüs" list value)
    ('c19098e9-4f4e-52d6-2540-a16f01922824'::uuid, 'ffa47477-7504-48b0-8e82-837da80aa646'::uuid)
ON CONFLICT (parent_university_id) DO NOTHING;

COMMIT;
