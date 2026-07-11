BEGIN;

-- A4 point 1: logistics_coverage in awaiting_university should confirm Istanbul-only
-- service without re-asking for university (out-of-city leads are not pursued).
UPDATE canned_responses
SET content = 'Evet efendim, şu an yalnızca İstanbul''da hizmet veriyoruz.'
WHERE short_code = 'div_coverage_await_uni';

UPDATE canned_responses
SET content = 'Şu an sadece İstanbul''dayız efendim.'
WHERE short_code = 'div_coverage_await_uni_alt';

COMMIT;
