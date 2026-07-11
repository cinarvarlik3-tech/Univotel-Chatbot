BEGIN;

INSERT INTO university_aliases (university_id, alias)
SELECT 'a17cc4c1-12b8-4762-9731-64ba9235d0de'::uuid, 'ayazağa'
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE university_id = 'a17cc4c1-12b8-4762-9731-64ba9235d0de'::uuid
      AND alias = 'ayazağa'
);

COMMIT;
