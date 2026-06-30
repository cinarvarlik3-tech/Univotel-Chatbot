-- 003_insert_global_null_state.sql
-- Inserts the GLOBAL-NULL-STATE sentinel hotel and wires its canned response.
-- The sentinel UUID is fixed — application code references it directly.

INSERT INTO hotels (id, name, is_visible, gender_scope, priority_score)
VALUES ('00000000-0000-0000-0000-000000000001', 'GLOBAL-NULL-STATE', false, NULL, NULL)
ON CONFLICT (id) DO NOTHING;

-- Replace <TODO> with actual "sorry, no matching property" copy before going live.
INSERT INTO canned_responses (id, short_code, content)
VALUES (
    gen_random_uuid(),
    'henuz',
    'Maalesef şu an üniversitenize yakın uygun bir yurt/otel bulamadık. En kısa sürede size dönüş yapacağız.'
)
ON CONFLICT (short_code) DO NOTHING;

INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000001', id, 1
FROM canned_responses
WHERE short_code = 'henuz'
ON CONFLICT (hotel_id, sending_order) DO NOTHING;
