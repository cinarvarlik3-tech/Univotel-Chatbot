-- 004_create_university_aliases.sql
-- Already created in 001 if running a fresh setup.
-- This migration is a no-op on fresh installs; exists for environments that
-- ran 001 before aliases were part of it.

CREATE TABLE IF NOT EXISTS university_aliases (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id uuid REFERENCES universities(id) NOT NULL,
    alias         text UNIQUE NOT NULL,
    created_at    timestamptz DEFAULT now()
);

-- Seed from university_short_name where unambiguous.
-- Insert manually verified aliases only — ambiguous ones belong in the clarification flow.
-- Example (uncomment and adjust UUIDs to match your data):
-- INSERT INTO university_aliases (university_id, alias) VALUES
--     ('uuid-of-iku', 'iku'),
--     ('uuid-of-itu', 'itu')
-- ON CONFLICT (alias) DO NOTHING;
