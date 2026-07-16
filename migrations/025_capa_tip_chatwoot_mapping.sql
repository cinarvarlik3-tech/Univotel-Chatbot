-- 025_capa_tip_chatwoot_mapping.sql
-- Remap İÜ Çapa Tıp Fakültesi to dedicated Chatwoot list value.
-- Prerequisite: "Çapa Tıp Fakültesi" must exist in Chatwoot university List.
-- Apply manually via Supabase SQL editor.

BEGIN;

UPDATE university_chatwoot_label_map
SET chatwoot_list_value = 'Çapa Tıp Fakültesi'
WHERE university_id = '082e55c7-bc59-43dd-8235-c172d4275bb2';

INSERT INTO university_aliases (university_id, alias)
SELECT '082e55c7-bc59-43dd-8235-c172d4275bb2'::uuid, 'çapa tıp'
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE university_id = '082e55c7-bc59-43dd-8235-c172d4275bb2'::uuid
      AND alias = 'çapa tıp'
);

COMMIT;
