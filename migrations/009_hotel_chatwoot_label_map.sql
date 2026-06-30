-- 009_hotel_chatwoot_label_map.sql
-- Maps hotels.id to the exact Chatwoot ilgili_otel list-option string.
-- chatwoot_list_value must EXACTLY match a live Chatwoot ilgili_otel List option
-- (case-sensitive, no whitespace variation tolerated).
-- Re-sync required on every hotel add/rename.

CREATE TABLE IF NOT EXISTS hotel_chatwoot_label_map (
    hotel_id            uuid PRIMARY KEY REFERENCES hotels(id),
    chatwoot_list_value text UNIQUE NOT NULL
);

-- TODO: seed the rows once chatwoot_list_value strings are confirmed against live Chatwoot.
-- The boot-time integrity check (health/integrity_check.py) will fail loudly on any gap.
--
-- Example insert pattern (replace UUIDs and strings with real values):
--
-- INSERT INTO hotel_chatwoot_label_map (hotel_id, chatwoot_list_value) VALUES
--     ('xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', '<exact-chatwoot-option-1>'),
--     ('yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy', '<exact-chatwoot-option-2>')
-- ON CONFLICT (hotel_id) DO UPDATE SET chatwoot_list_value = EXCLUDED.chatwoot_list_value;
