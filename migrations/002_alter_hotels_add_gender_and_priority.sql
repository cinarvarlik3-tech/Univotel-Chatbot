-- 002_alter_hotels_add_gender_and_priority.sql
-- Adds gender_scope and priority_score to the existing hotels table.
-- RecEngine cannot run until this migration is applied AND every row's
-- gender_scope is manually verified (the UPDATE below is a heuristic starting point).

ALTER TABLE hotels
    ADD COLUMN IF NOT EXISTS gender_scope   text CHECK (gender_scope IN ('male','female','mixed')),
    ADD COLUMN IF NOT EXISTS priority_score int4 DEFAULT 100;

-- Heuristic backfill from hotel name — must be manually reviewed before going live.
UPDATE hotels SET gender_scope = 'male'   WHERE name ILIKE '%erkek%' AND gender_scope IS NULL;
UPDATE hotels SET gender_scope = 'female' WHERE (name ILIKE '%kız%' OR name ILIKE '%kiz%') AND gender_scope IS NULL;

-- Any hotel still NULL after this block needs manual classification.
-- RecEngine will never return a hotel with gender_scope IS NULL.
