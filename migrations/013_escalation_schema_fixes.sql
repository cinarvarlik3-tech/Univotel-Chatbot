-- 013_escalation_schema_fixes.sql
-- Fixes two gaps in the parent-escalation feature discovered during the
-- conv-52 İTÜ end-to-end test. Apply manually via the Supabase SQL editor.
--
-- Gap 1: migration 011 introduced the 'awaiting_campus_clarification' flow
--        state in code but never widened the conversations_flow_state_check
--        constraint, so the UPDATE to that state was rejected at runtime.
-- Gap 2: migration 012 seeded Doğuş Kadıköy into university_parent_map but
--        not into university_chatwoot_label_map, tripping integrity check #6.
--
-- Notes on migration 011 application status (verified 2026-07-03):
--   Sections 1–4a/b, 5 — applied.
--   Section 4c (university_aliases_has_target constraint) — was NOT applied.
--   Section 5 (pending_parent_university_id column) — was NOT applied; found
--     missing mid-test and applied out-of-band. Both 4c and 5 are included
--     below using IF NOT EXISTS / DO block so this file is idempotent.

-- -----------------------------------------------------------------------
-- Gap 1: widen the flow_state check constraint to include the escalation state
-- -----------------------------------------------------------------------
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_flow_state_check;
ALTER TABLE conversations ADD CONSTRAINT conversations_flow_state_check
    CHECK (flow_state = ANY (ARRAY[
        'new',
        'awaiting_university',
        'awaiting_university_clarification',
        'awaiting_campus_clarification',
        'awaiting_gender',
        'recengine_running',
        'completed',
        'human_needed',
        'stopped'
    ]));

-- -----------------------------------------------------------------------
-- Gap 2: Doğuş Kadıköy campus needs a university_chatwoot_label_map row.
--        Value follows the sibling pattern: "Doğuş Üniversitesi <Campus>"
--        (cf. "Doğuş Üniversitesi Çengelköy", "Doğuş Üniversitesi Dudullu").
--
--   IMPORTANT: this string must EXACTLY match an option in the Chatwoot
--   "university" custom-attribute List, or the attribute write will fail at
--   runtime. Confirm/add the option "Doğuş Üniversitesi Kadıköy" in Chatwoot.
-- -----------------------------------------------------------------------
INSERT INTO university_chatwoot_label_map (university_id, chatwoot_list_value)
VALUES ('22490d0d-d25a-474f-b158-f0e602e181ee', 'Doğuş Üniversitesi Kadıköy')
ON CONFLICT (university_id) DO NOTHING;

-- -----------------------------------------------------------------------
-- 011 section 4c (missed): at least one FK column must be populated
-- -----------------------------------------------------------------------
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
-- 011 section 5 (missed on tested DB): campus escalation state column
-- -----------------------------------------------------------------------
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS pending_parent_university_id uuid
        REFERENCES parent_universities(id);
