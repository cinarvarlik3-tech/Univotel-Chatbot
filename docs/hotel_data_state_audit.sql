-- =====================================================================
-- hotel_data_state_audit.sql
-- =====================================================================
-- Flag-1 data-state audit for the hotels subsystem.
--
-- MOTIVATION: The GK Regency incident was NOT a logic bug — RecEngine
-- correctly excluded a hotel whose is_visible flag was false when it should
-- have been true. The lesson: recommendation correctness depends on data
-- FLAGS being in the right state, and a wrong flag fails silently. This suite
-- audits every flag/link/mapping a recommendable hotel depends on.
--
-- CONVENTION (important): every query is written so that a PASSING check
-- returns ZERO ROWS. Any row returned is a violation to investigate. Run the
-- whole file; any result set that is non-empty is a finding.
--
-- READ-ONLY: every statement is a SELECT. Safe to run against production.
--
-- SENTINELS (excluded from "recommendable" checks):
--   GLOBAL-NULL-STATE  = 00000000-0000-0000-0000-000000000001
--   DEAL-AWAITING-STATE = 00000000-0000-0000-0000-000000000002
--
-- LEGACY (being deleted; excluded where noted): Mari Suites Hotel,
--   Keten Suites, Monezza Avcılar. Adjust the legacy filter if names differ.
-- =====================================================================

-- Reusable definition of "recommendable": visible, not a sentinel, not legacy.
-- (Inlined per query since Postgres has no session-scoped view here.)

-- ---------------------------------------------------------------------
-- A1  Visible, recommendable hotels must have a usable priority_score (>0).
--     A visible hotel with NULL/0 priority can be silently out-competed or
--     mis-ranked. (Legacy hotels legitimately have 0; they're excluded.)
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A1_bad_priority' AS check_id, id, name, priority_score, is_visible
FROM hotels
WHERE is_visible = true
  AND id NOT IN ('00000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-000000000002')
  AND name NOT IN ('Mari Suites Hotel','Keten Suites','Monezza Avcılar')
  AND (priority_score IS NULL OR priority_score <= 0);

-- ---------------------------------------------------------------------
-- A2  The GK Regency check, generalized: a hotel that is FULLY WIRED for
--     recommendation (has ≥1 university link AND a chatwoot label-map row)
--     but is is_visible = false. That is the exact silent-exclusion state
--     that hid GK Regency. Such a hotel is "ready but hidden" — suspicious.
-- EXPECT: 0 rows. Any row = confirm whether the hotel is intentionally hidden.
-- ---------------------------------------------------------------------
SELECT 'A2_ready_but_hidden' AS check_id, h.id, h.name, h.is_visible
FROM hotels h
WHERE h.is_visible = false
  AND h.id NOT IN ('00000000-0000-0000-0000-000000000001',
                   '00000000-0000-0000-0000-000000000002')
  AND EXISTS (SELECT 1 FROM hotel_accessible_universities hau WHERE hau.hotel_id = h.id)
  AND EXISTS (SELECT 1 FROM hotel_chatwoot_label_map m WHERE m.hotel_id = h.id);

-- ---------------------------------------------------------------------
-- A3  Every visible recommendable hotel must have ≥1 university link.
--     A visible hotel with no hotel_accessible_universities row can never be
--     recommended to anyone — dead inventory.
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A3_no_university_link' AS check_id, h.id, h.name
FROM hotels h
WHERE h.is_visible = true
  AND h.id NOT IN ('00000000-0000-0000-0000-000000000001',
                   '00000000-0000-0000-0000-000000000002')
  AND h.name NOT IN ('Mari Suites Hotel','Keten Suites','Monezza Avcılar')
  AND NOT EXISTS (SELECT 1 FROM hotel_accessible_universities hau WHERE hau.hotel_id = h.id);

-- ---------------------------------------------------------------------
-- A4  Every visible recommendable hotel must have a chatwoot label-map row,
--     else its ilgili_otel attribute write silently drops. (Health-check
--     mirror, as a standalone audit.)
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A4_no_label_map' AS check_id, h.id, h.name
FROM hotels h
WHERE h.is_visible = true
  AND h.id NOT IN ('00000000-0000-0000-0000-000000000001',
                   '00000000-0000-0000-0000-000000000002')
  AND h.name NOT IN ('Mari Suites Hotel','Keten Suites','Monezza Avcılar')
  AND NOT EXISTS (SELECT 1 FROM hotel_chatwoot_label_map m WHERE m.hotel_id = h.id);

-- ---------------------------------------------------------------------
-- A5  gender_scope must be exactly one of the three allowed values.
--     A NULL or typo'd scope breaks the gender eligibility filter silently.
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A5_bad_gender_scope' AS check_id, id, name, gender_scope
FROM hotels
WHERE id NOT IN ('00000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-000000000002')
  AND (gender_scope IS NULL OR gender_scope NOT IN ('male','female','mixed'));

-- ---------------------------------------------------------------------
-- A6  Every hotel that can be selected (visible recommendable + BOTH
--     sentinels) must have ≥1 response_schemas row, else RecEngine/
--     InfoGatherer selects it but has nothing to send.
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A6_no_response_schema' AS check_id, h.id, h.name
FROM hotels h
WHERE (
        (h.is_visible = true
         AND h.name NOT IN ('Mari Suites Hotel','Keten Suites','Monezza Avcılar'))
        OR h.id IN ('00000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-000000000002')
      )
  AND NOT EXISTS (SELECT 1 FROM response_schemas rs WHERE rs.hotel_id = h.id);

-- ---------------------------------------------------------------------
-- A7  Both sentinels must exist, be hidden, and be wired to a response.
--     Split into existence + state so a missing sentinel is obvious.
-- EXPECT: 0 rows (the VALUES list expects exactly these two, present & wired).
-- ---------------------------------------------------------------------
SELECT 'A7_sentinel_problem' AS check_id, s.expected_id, s.expected_name,
       h.id AS found_id, h.is_visible,
       EXISTS (SELECT 1 FROM response_schemas rs WHERE rs.hotel_id = s.expected_id) AS has_schema
FROM (VALUES
        ('00000000-0000-0000-0000-000000000001'::uuid, 'GLOBAL-NULL-STATE'),
        ('00000000-0000-0000-0000-000000000002'::uuid, 'DEAL-AWAITING-STATE')
     ) AS s(expected_id, expected_name)
LEFT JOIN hotels h ON h.id = s.expected_id
WHERE h.id IS NULL                               -- missing entirely
   OR h.is_visible = true                        -- should be hidden
   OR NOT EXISTS (SELECT 1 FROM response_schemas rs WHERE rs.hotel_id = s.expected_id);  -- unwired

-- ---------------------------------------------------------------------
-- A8  Legacy hotels should be gone OR fully de-listed (hidden + no links).
--     A legacy hotel still visible or still linked can leak into results.
-- EXPECT: 0 rows once deletion is complete.
-- ---------------------------------------------------------------------
SELECT 'A8_legacy_not_retired' AS check_id, h.id, h.name, h.is_visible,
       EXISTS (SELECT 1 FROM hotel_accessible_universities hau WHERE hau.hotel_id = h.id) AS still_linked
FROM hotels h
WHERE h.name IN ('Mari Suites Hotel','Keten Suites','Monezza Avcılar')
  AND (h.is_visible = true
       OR EXISTS (SELECT 1 FROM hotel_accessible_universities hau WHERE hau.hotel_id = h.id));

-- ---------------------------------------------------------------------
-- A9  Referential integrity of the link table: every hotel_accessible_
--     universities row must point to a real hotel AND a real university.
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A9_orphan_link' AS check_id, hau.hotel_id, hau.university_id,
       (h.id IS NULL) AS hotel_missing, (u.id IS NULL) AS university_missing
FROM hotel_accessible_universities hau
LEFT JOIN hotels h       ON h.id = hau.hotel_id
LEFT JOIN universities u ON u.id = hau.university_id
WHERE h.id IS NULL OR u.id IS NULL;

-- ---------------------------------------------------------------------
-- A10  No orphaned label-map rows (mapping points at a deleted hotel).
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A10_orphan_label_map' AS check_id, m.hotel_id, m.chatwoot_list_value
FROM hotel_chatwoot_label_map m
LEFT JOIN hotels h ON h.id = m.hotel_id
WHERE h.id IS NULL;

-- ---------------------------------------------------------------------
-- A11  Duplicate chatwoot_list_value in the label map. Two hotels mapped to
--      the same Chatwoot option means an ambiguous ilgili_otel write.
-- EXPECT: 0 rows.
-- ---------------------------------------------------------------------
SELECT 'A11_dup_label_value' AS check_id, chatwoot_list_value, COUNT(*) AS n
FROM hotel_chatwoot_label_map
GROUP BY chatwoot_list_value
HAVING COUNT(*) > 1;

-- =====================================================================
-- A12  NON-ASSERTING REVIEW: per-university intended winner.
-- This one is meant to RETURN ROWS — it's an eyeball report, not a pass/fail.
-- For each university, it lists the visible, gender-eligible candidates ranked
-- as RecEngine would rank them, so you can confirm the hotel you EXPECT to win
-- per campus actually sits at rank 1. This is the GK Regency scenario made
-- visible: if the intended winner isn't rank 1, a flag is wrong.
--
-- Run per university_id of interest (example uses İTÜ Maslak/Ayazağa).
-- Repeat for each campus you care about, or remove the WHERE to dump all.
-- =====================================================================
SELECT 'A12_ranking_review' AS check_id,
       u.name AS university,
       h.name AS hotel,
       h.gender_scope,
       h.priority_score,
       h.is_visible,
       RANK() OVER (
         PARTITION BY u.id
         ORDER BY (h.is_visible)::int DESC, h.priority_score DESC NULLS LAST
       ) AS rec_rank
FROM hotel_accessible_universities hau
JOIN hotels h       ON h.id = hau.hotel_id
JOIN universities u ON u.id = hau.university_id
WHERE u.id = 'a17cc4c1-12b8-4762-9731-64ba9235d0de'   -- İTÜ Maslak; change/remove as needed
ORDER BY u.name, rec_rank;
