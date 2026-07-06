-- 016_deal_awaiting_recengine.sql
-- Post-RecEngine deal-awaiting sentinels: label path (…0003) vs plain NULL (…0002).
-- Both use the same pending-deal canned response at order 0.
-- GLOBAL-NULL-STATE (…0001) remains henuz fallback only.

-- Third sentinel: Istanbul NULL + deal_awaiting_universities membership → label write in callback.
INSERT INTO hotels (id, name, is_visible, gender_scope, priority_score)
VALUES ('00000000-0000-0000-0000-000000000003', 'DEAL-AWAITING-LABEL-STATE', false, NULL, NULL)
ON CONFLICT (id) DO NOTHING;

-- Pending-deal message (production canned_responses.id).
-- Used for both …0002 (no label) and …0003 (deal_awaiting label).
-- Wire …0002 at order 0.
INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
VALUES (
    gen_random_uuid(),
    '00000000-0000-0000-0000-000000000002',
    '27ac4381-1c05-4dd6-adc5-2449c8cef639',
    0
)
ON CONFLICT (hotel_id, sending_order) DO UPDATE
SET response_id = EXCLUDED.response_id;

-- Wire …0003 at order 0 (same copy as …0002).
INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
VALUES (
    gen_random_uuid(),
    '00000000-0000-0000-0000-000000000003',
    '27ac4381-1c05-4dd6-adc5-2449c8cef639',
    0
)
ON CONFLICT (hotel_id, sending_order) DO UPDATE
SET response_id = EXCLUDED.response_id;

-- GLOBAL-NULL fallback: henüz at order 0 only (short_code uses Turkish ü in prod).
INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000001', id, 0
FROM canned_responses
WHERE short_code = 'henüz'
ON CONFLICT (hotel_id, sending_order) DO UPDATE
SET response_id = EXCLUDED.response_id;
