-- 028_remove_beyoglu_alias.sql
-- A1 (TAGASSIGNER_ACCURACY_FIXES_PLAN.md) — undo the migration-027 regression: a bare
-- 'beyoğlu' alias to MSGSÜ's Fındıklı campus was added there. Beyoğlu is a DISTRICT
-- (MSGSÜ's Fındıklı campus merely sits in it), not a university identifier, so the alias
-- hijacked any lead who mentioned the district. Verified:
-- canonicalize("Istanbul Kent University Beyoğlu") -> MSGSÜ Fındıklı today; with this
-- alias removed -> İstanbul Kent Üniversitesi Taksim (the lead's actual university).
--
-- Keep 'fındıklı' / 'fındıklı kampüsü' — those are real campus names, not districts.
-- Idempotent: DELETE is a no-op if the row is already gone.

BEGIN;

DELETE FROM university_aliases
WHERE alias = 'beyoğlu'
  AND university_id = '82136f33-2b29-4830-ae0a-46cd8bd4bb3c'::uuid;

COMMIT;
