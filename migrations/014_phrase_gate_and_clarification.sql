-- 014_phrase_gate_and_clarification.sql
-- Phrase-gate spec: clarification retry counter + missing canned response seeds.

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS clarification_attempt integer NOT NULL DEFAULT 0;

INSERT INTO canned_responses (id, short_code, content)
VALUES (
    gen_random_uuid(),
    'clarify_uni',
    'Tam ismi neydi efendim üniversitenizin, kısaltmadan çıkaramadım?'
)
ON CONFLICT (short_code) DO NOTHING;

INSERT INTO canned_responses (id, short_code, content)
VALUES (
    gen_random_uuid(),
    'clarify_uni_name',
    'Efendim üniversite ismini çıkaramadım, resmi adı neydi okulunuzun?'
)
ON CONFLICT (short_code) DO NOTHING;

INSERT INTO canned_responses (id, short_code, content)
VALUES (
    gen_random_uuid(),
    'clarify_campus_name',
    'Efendim kampüs ismini çıkaramadım, resmi adı neydi kampüsünüzün?'
)
ON CONFLICT (short_code) DO NOTHING;
