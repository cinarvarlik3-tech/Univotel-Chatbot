-- 027_campus_aliases.sql
-- WS2 (UNIVERSITY_ACCURACY_PLAN.md) — add campus aliases for phrases leads
-- actually use that the matcher currently can't resolve, per review:
--   - Boğaziçi "güney" / "Rumeli Hisarı" -> Boğaziçi Üniversitesi - Ana Kampüs
--     (the historic south/Rumelihisarı campus; "güney" = south in Turkish).
--   - Mimar Sinan "Fındıklı" / "Beyoğlu" -> the single MSGSÜ list entry
--     (MSGSÜ - Beşiktaş; confirmed there is exactly one MSGSÜ campus in the
--     universities table, id 82136f33-2b29-4830-ae0a-46cd8bd4bb3c).
--
-- Also fixes an adjacent pre-existing data bug found while implementing
-- this: MSGSÜ has TWO separate `parent_universities` rows —
--   - 614255de-... name="Mimar Sinan Güzel Sanatlar Üniversitesi" (the
--     clean parent name). The existing 'mimar sinan' / 'msgsu' / 'msgsü'
--     aliases point HERE, but it has ZERO rows in university_parent_map.
--   - 3fad2cb4-... name="Mimar Sinan Güzel Sanatlar Üniversitesi - Fındıklı
--     Kampüsü" (a malformed duplicate whose "parent" name is actually the
--     full CAMPUS name — a data-entry mistake). The real campus
--     (82136f33-...) IS mapped here, but NO alias points at this id, so
--     it's unreachable via any phrase.
-- Net effect: canonicalize()'s "single-campus parent auto-resolves to that
-- campus" shortcut could never fire for MSGSÜ via a bare institution
-- mention, because the alias-bearing parent and the campus-bearing parent
-- were two different, disconnected rows. Since university_id is the
-- PRIMARY KEY of university_parent_map (one parent per campus), the fix is
-- to REPOINT the existing campus row onto the clean, alias-bearing parent
-- (614255de) rather than insert a second row (which the PK would reject
-- anyway). The orphaned 3fad2cb4 parent row is left in place untouched
-- (deleting parent_universities rows is out of scope here) but becomes
-- fully dead — no alias references it before or after this migration.

BEGIN;

-- ---------------------------------------------------------------------
-- Data-bug fix: repoint MSGSÜ's campus onto its clean, alias-bearing
-- parent (see note above). Idempotent: no-op if already repointed.
-- ---------------------------------------------------------------------
UPDATE university_parent_map
SET parent_university_id = '614255de-6aca-8407-f622-4eba64bf8696'::uuid
WHERE university_id = '82136f33-2b29-4830-ae0a-46cd8bd4bb3c'::uuid
  AND parent_university_id <> '614255de-6aca-8407-f622-4eba64bf8696'::uuid;

-- ---------------------------------------------------------------------
-- Boğaziçi Üniversitesi - Ana Kampüs (ffa47477-...): güney / Rumeli Hisarı
-- ---------------------------------------------------------------------
INSERT INTO university_aliases (university_id, alias)
SELECT 'ffa47477-7504-48b0-8e82-837da80aa646'::uuid, v.alias
FROM (VALUES
    ('güney kampüs'),
    ('güney yerleşkesi'),
    ('rumeli hisarı'),
    ('rumelihisarı'),
    ('hisarüstü')
) AS v(alias)
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE university_id = 'ffa47477-7504-48b0-8e82-837da80aa646'::uuid
      AND alias = v.alias
);

-- ---------------------------------------------------------------------
-- MSGSÜ (82136f33-...): Fındıklı / Beyoğlu
-- ---------------------------------------------------------------------
INSERT INTO university_aliases (university_id, alias)
SELECT '82136f33-2b29-4830-ae0a-46cd8bd4bb3c'::uuid, v.alias
FROM (VALUES
    ('fındıklı'),
    ('fındıklı kampüsü'),
    ('beyoğlu')
) AS v(alias)
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE university_id = '82136f33-2b29-4830-ae0a-46cd8bd4bb3c'::uuid
      AND alias = v.alias
);

COMMIT;
