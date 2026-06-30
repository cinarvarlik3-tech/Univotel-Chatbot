-- 006_deal_awaiting.sql
-- V0 Amendment: deal_awaiting flow in InfoGatherer.
-- Adds: deal_awaiting_universities membership table, DEAL-AWAITING-STATE sentinel + wiring.

CREATE TABLE IF NOT EXISTS deal_awaiting_universities (
    university_id uuid PRIMARY KEY REFERENCES universities(id),
    created_at    timestamptz DEFAULT now()
);

INSERT INTO hotels (id, name, is_visible, gender_scope, priority_score)
VALUES ('00000000-0000-0000-0000-000000000002', 'DEAL-AWAITING-STATE', false, NULL, NULL)
ON CONFLICT (id) DO NOTHING;

-- TODO: replace placeholder content with real "we serve Istanbul but not your school yet" copy.
INSERT INTO canned_responses (id, short_code, content)
VALUES (
    gen_random_uuid(),
    'deal_awaiting_msg',
    'Üniversiteniz şu an hizmet verdiğimiz kurumlar arasında yer almıyor. İleride bu durumun değişmesi halinde sizi bilgilendireceğiz.'
)
ON CONFLICT (short_code) DO NOTHING;

INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000002', id, 1
FROM canned_responses WHERE short_code = 'deal_awaiting_msg'
ON CONFLICT (hotel_id, sending_order) DO NOTHING;
