-- 011_parent_university_escalation.sql
-- Schema for the parent-university escalation model and university attribute map.
-- All DDL is idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- Seed data lives in session_migration.sql (parent_universities + university_parent_map)
-- and university_map_seed.sql (university_chatwoot_label_map, 92 rows).
-- Apply manually via the Supabase SQL editor — do NOT auto-run.

-- -----------------------------------------------------------------------
-- 1. university_chatwoot_label_map
--    Translates universities.id → exact Chatwoot "university" List option.
--    Mirror of hotel_chatwoot_label_map pattern.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS university_chatwoot_label_map (
    university_id       uuid PRIMARY KEY REFERENCES universities(id),
    chatwoot_list_value text NOT NULL
);

-- -----------------------------------------------------------------------
-- 2. parent_universities
--    One row per multi-campus group (and single-campus stub).
--    question is a Python .format() template: {name} and {campuses} slots.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parent_universities (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name     text NOT NULL,
    question text NOT NULL DEFAULT 'Hangi {name} kampüsü efendim? {campuses}'
);

-- -----------------------------------------------------------------------
-- 3. university_parent_map
--    One row per campus. PK on university_id enforces one-parent-per-campus.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS university_parent_map (
    university_id       uuid PRIMARY KEY REFERENCES universities(id),
    parent_university_id uuid NOT NULL REFERENCES parent_universities(id),
    campus_label        text NOT NULL
);

-- -----------------------------------------------------------------------
-- 4. university_aliases — add parent_university_id column
--    Aliases can now target either a campus (university_id) or a parent
--    (parent_university_id) for escalation.
--    The NOT NULL constraint on university_id must be dropped to allow
--    parent-only aliases.
-- -----------------------------------------------------------------------
ALTER TABLE university_aliases
    ADD COLUMN IF NOT EXISTS parent_university_id uuid REFERENCES parent_universities(id);

-- Drop the NOT NULL constraint on university_id (parent aliases have it NULL).
-- Idempotent: fails silently if the constraint is already absent.
ALTER TABLE university_aliases
    ALTER COLUMN university_id DROP NOT NULL;

-- Ensure at least one of the two FK columns is populated.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'university_aliases'
          AND constraint_name = 'university_aliases_has_target'
    ) THEN
        ALTER TABLE university_aliases
            ADD CONSTRAINT university_aliases_has_target
            CHECK (university_id IS NOT NULL OR parent_university_id IS NOT NULL);
    END IF;
END$$;

-- -----------------------------------------------------------------------
-- 5. conversations — pending_parent_university_id
--    Stores which parent university was asked about while the conversation
--    is in the awaiting_campus_clarification state.
-- -----------------------------------------------------------------------
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS pending_parent_university_id uuid
        REFERENCES parent_universities(id);
