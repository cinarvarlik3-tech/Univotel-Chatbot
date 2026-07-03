-- 012_fix3_orphan_universities.sql
-- Seeds university_parent_map rows for two universities that were in the
-- universities table but were missed during the parent-map seed.
-- Identified via the boot-time INTEGRITY CRITICAL logged in test session.
--
-- Apply manually via the Supabase SQL editor.
-- Run the integrity check after applying to confirm the CRITICAL clears.

-- -----------------------------------------------------------------------
-- 1. Doğuş Üniversitesi - Kadıköy  (CONFIRMED)
--    Third campus of the already-seeded Doğuş parent.
--    Sibling labels: Çengelköy, Dudullu — using same district-only pattern.
-- -----------------------------------------------------------------------
INSERT INTO university_parent_map (university_id, parent_university_id, campus_label)
VALUES (
    '22490d0d-d25a-474f-b158-f0e602e181ee',   -- Doğuş Üniversitesi - Kadıköy
    '23e97161-e64c-0b2d-d9e7-27d239ac4a38',   -- parent: Doğuş Üniversitesi
    'Kadıköy'
)
ON CONFLICT (university_id) DO NOTHING;

-- -----------------------------------------------------------------------
-- 2. İstanbul Arel Üniversitesi - Kemal Gözükara Yerleşkesi  (DELETED)
--
--    This row was a duplicate of the existing Tepekent Kampüsü
--    (university_parent_map campus_label = 'Tepekent Kemal Gözükara').
--    Same physical location, different name in the DB. The canonical row
--    is Tepekent Kampüsü; this one was extraneous.
--
--    Also had one dangling university_chatwoot_label_map row which is
--    removed first to satisfy the FK constraint.
-- -----------------------------------------------------------------------
DELETE FROM university_chatwoot_label_map
WHERE university_id = '874e42ea-e599-4d29-a893-fb8b133513bb';

DELETE FROM universities
WHERE id = '874e42ea-e599-4d29-a893-fb8b133513bb';
