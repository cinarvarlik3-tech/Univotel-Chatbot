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
-- 2. İstanbul Arel Üniversitesi - Kemal Gözükara Yerleşkesi  (PENDING CONFIRMATION)
--
--    STOP — do NOT run this block until the following is confirmed:
--
--    The Arel parent already has three campuses:
--      • Cevizlibağ
--      • Sefaköy
--      • Tepekent Kemal Gözükara  ← note: label already includes "Kemal Gözükara"
--
--    The orphan university is named "Kemal Gözükara Yerleşkesi".
--    It is UNCLEAR whether this is:
--      (a) A 4th distinct campus — in which case add it here with label 'Kemal Gözükara'
--      (b) The SAME physical location as Tepekent Kampüsü, differently named in the DB
--          — in which case the universities row should be investigated/removed,
--            NOT added to university_parent_map
--
--    Ask the user before applying. A wrong parent assignment here routes a real
--    lead's campus-escalation reply to the wrong campus.
--
-- INSERT INTO university_parent_map (university_id, parent_university_id, campus_label)
-- VALUES (
--     '874e42ea-e599-4d29-a893-fb8b133513bb',   -- Arel Kemal Gözükara Yerleşkesi
--     'f353775e-c72a-5640-6d7b-5e46d092379f',   -- parent: İstanbul Arel Üniversitesi
--     'Kemal Gözükara'
-- )
-- ON CONFLICT (university_id) DO NOTHING;
-- -----------------------------------------------------------------------
