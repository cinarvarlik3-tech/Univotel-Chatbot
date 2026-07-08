-- ============================================================================
-- Migration 018 — InfoGatherer Divergence Recovery
-- Adds: bot_enabled + divergence counter columns on conversations,
--       divergence_routing table, divergence canned responses (Turkish),
--       seeded routing rows for the high-value intent × state matrix.
--
-- Apply AFTER 017. Idempotent where practical (IF NOT EXISTS / ON CONFLICT).
-- Run manually in the Supabase SQL editor against the ChatBot DB.
--
-- Design rules encoded here:
--   * Missing (intent, flow_state) row  → escalate  (handled in CODE, not seeded)
--   * complex / non_turkish             → no rows   (they escalate by default)
--   * no_intent                         → explicit  action='ignore' rows
--   * answer_and_reanchor rows          → BOTH canned FKs non-null (CHECK)
--   * activate_flow / ignore / escalate → BOTH canned FKs null    (CHECK)
--   * Firing states only: new, awaiting_university, awaiting_gender,
--     awaiting_university_clarification, awaiting_campus_clarification
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. conversations: outbound-first gating + divergence persistence counter
-- ----------------------------------------------------------------------------
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS bot_enabled boolean NOT NULL DEFAULT true;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS last_divergence_intent text;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS divergence_repeat_count integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN conversations.bot_enabled IS
    'False for salesperson-initiated (outbound-first) conversations; bot performs no processing.';
COMMENT ON COLUMN conversations.last_divergence_intent IS
    'Most recent classifier intent on a divergence turn; NULL after any slot progress. Same-intent persistence tracking.';
COMMENT ON COLUMN conversations.divergence_repeat_count IS
    'Consecutive repeats of last_divergence_intent with no slot progress. 1→primary canned, 2→alt canned, 3→escalate.';

-- ----------------------------------------------------------------------------
-- 2. divergence_routing table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS divergence_routing (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intent                  text NOT NULL,
    flow_state              text NOT NULL,
    action                  text NOT NULL,
    canned_response_id      uuid REFERENCES canned_responses(id),
    canned_response_alt_id  uuid REFERENCES canned_responses(id),
    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT divergence_routing_unique_cell UNIQUE (intent, flow_state),

    CONSTRAINT divergence_routing_action_check
        CHECK (action IN ('activate_flow', 'answer_and_reanchor', 'ignore', 'escalate')),

    CONSTRAINT divergence_routing_flow_state_check
        CHECK (flow_state IN (
            'new',
            'awaiting_university',
            'awaiting_gender',
            'awaiting_university_clarification',
            'awaiting_campus_clarification'
        )),

    CONSTRAINT divergence_routing_intent_check
        CHECK (intent IN (
            'housing', 'price', 'location', 'vacancy', 'parent_shopping',
            'logistics_coverage', 'logistics_payment', 'logistics_eligibility',
            'no_intent', 'complex', 'non_turkish'
        )),

    -- answer_and_reanchor requires both phrasings; all other actions require neither.
    CONSTRAINT divergence_routing_canned_check
        CHECK (
            (action = 'answer_and_reanchor'
                AND canned_response_id IS NOT NULL
                AND canned_response_alt_id IS NOT NULL)
            OR
            (action IN ('activate_flow', 'ignore', 'escalate')
                AND canned_response_id IS NULL
                AND canned_response_alt_id IS NULL)
        )
);

COMMENT ON TABLE divergence_routing IS
    'Policy table: (intent × flow_state) → action. Missing row is handled in code as escalate. '
    'Not seeded for complex/non_turkish (escalate by default) nor for unseeded clarification-state cells.';

-- ----------------------------------------------------------------------------
-- 3. Divergence canned responses (Turkish). Primary + _alt phrasings.
--    Copy is production-drafted; refine wording in place as needed — do NOT
--    rename short_codes (the routing seed below references them).
--    Assumes canned_responses(id uuid default, short_code text unique, content text).
-- ----------------------------------------------------------------------------
INSERT INTO canned_responses (short_code, content) VALUES

-- ---- PRICE ----
('div_price_new',
 'Efendim fiyatlarımız şubeden şubeye değişiyor. Hangi üniversite ve hangi cinsiyet için konaklama aradığınızı öğrenebilirsem size en uygun şubemizin fiyatlarını iletebilirim.'),
('div_price_new_alt',
 'Fiyat bilgisini netleştirebilmem için öncelikle hangi üniversitede okuduğunuzu ve kız mı erkek şubesi mi aradığınızı öğrenebilir miyim efendim?'),
('div_price_await_uni',
 'Fiyatlarımız üniversiteye ve şubeye göre değişiyor efendim. Hangi üniversitede okuyorsunuz?'),
('div_price_await_uni_alt',
 'Size doğru fiyatı iletebilmem için hangi üniversite için baktığınızı öğrenebilir miyim efendim?'),
('div_price_await_gender',
 'Efendim kız ve erkek şubelerimiz arasında fiyat farklılıkları oluyor, hangisine baktığınızı söylerseniz ona göre fiyat iletebilirim.'),
('div_price_await_gender_alt',
 'Fiyatı netleştirmem için kız öğrenci mi yoksa erkek öğrenci için mi konaklama aradığınızı öğrenebilir miyim efendim?'),

-- ---- LOCATION ----
('div_location_new',
 'Konumlarımızı size üniversitenize göre öneriyoruz efendim. Hangi üniversite ve cinsiyet için baktığınızı söylerseniz size en yakın şubemizi iletebilirim.'),
('div_location_new_alt',
 'Size en yakın şubemizi bulabilmem için hangi üniversitede okuduğunuzu ve kız mı erkek şubesi mi aradığınızı öğrenebilir miyim efendim?'),
('div_location_await_uni',
 'Size en yakın konumu önerebilmem için hangi üniversitede okuduğunuzu öğrenebilir miyim efendim?'),
('div_location_await_uni_alt',
 'En uygun konumu iletebilmem için üniversitenizi öğrenmem gerekiyor efendim, hangi üniversitedesiniz?'),
('div_location_await_gender',
 'Şubelerimiz kız ve erkek olarak ayrılıyor efendim, hangisine baktığınızı söylerseniz size en yakın konumu iletebilirim.'),
('div_location_await_gender_alt',
 'Size doğru konumu önerebilmem için kız mı erkek öğrenci için mi aradığınızı öğrenebilir miyim efendim?'),

-- ---- VACANCY ----
('div_vacancy_new',
 'Müsaitlik durumumuz şubeye göre değişiyor efendim. Hangi üniversite ve cinsiyet için baktığınızı söylerseniz uygun şubelerimizdeki durumu iletebilirim.'),
('div_vacancy_new_alt',
 'Boş yer durumunu kontrol edebilmem için hangi üniversite ve kız mı erkek şubesi mi aradığınızı öğrenebilir miyim efendim?'),
('div_vacancy_await_uni',
 'Müsaitlik durumunu kontrol edebilmem için hangi üniversitede okuduğunuzu öğrenebilir miyim efendim?'),
('div_vacancy_await_uni_alt',
 'Uygun yerlerimizi iletebilmem için üniversitenizi öğrenmem gerekiyor efendim, hangi üniversitedesiniz?'),
('div_vacancy_await_gender',
 'Kız ve erkek şubelerimizin doluluk durumu farklı efendim, hangisine baktığınızı söylerseniz kontrol edip iletebilirim.'),
('div_vacancy_await_gender_alt',
 'Boş yer durumunu iletebilmem için kız mı erkek öğrenci için mi aradığınızı öğrenebilir miyim efendim?'),

-- ---- HOUSING (pure re-anchor; new → activate_flow, no canned) ----
('div_housing_await_uni',
 'Tabii efendim, memnuniyetle yardımcı olurum. Öncelikle hangi üniversitede okuyorsunuz?'),
('div_housing_await_uni_alt',
 'Elbette efendim. Size uygun konaklamayı bulabilmem için hangi üniversitede okuduğunuzu öğrenebilir miyim?'),
('div_housing_await_gender',
 'Tabii efendim. Kız mı erkek öğrenci için mi konaklama aradığınızı öğrenebilir miyim?'),
('div_housing_await_gender_alt',
 'Elbette yardımcı olurum efendim. Kız mı erkek şubesi mi bakıyorsunuz?'),

-- ---- PARENT_SHOPPING (pure re-anchor; new → activate_flow, no canned) ----
('div_parent_await_uni',
 'Tabii efendim, öğrencimiz için yardımcı olalım. Hangi üniversiteyi kazandı ya da hangi üniversitede okuyor?'),
('div_parent_await_uni_alt',
 'Elbette efendim. Öğrencinin hangi üniversitede okuduğunu öğrenebilir miyim?'),
('div_parent_await_gender',
 'Tabii efendim. Öğrencimiz kız mı erkek mi, ona göre en uygun şubemizi önerebilirim?'),
('div_parent_await_gender_alt',
 'Kız öğrenci için mi erkek öğrenci için mi baktığınızı öğrenebilir miyim efendim?'),

-- ---- LOGISTICS_COVERAGE ----
('div_coverage_new',
 'Şu an yalnızca İstanbul''da hizmet veriyoruz efendim. İstanbul''daki bir üniversite için bakıyorsanız hangi üniversite ve cinsiyet olduğunu söylerseniz size yardımcı olabilirim.'),
('div_coverage_new_alt',
 'Hizmet bölgemiz şu an sadece İstanbul efendim. İstanbul''daki bir üniversite için hangi cinsiyette konaklama aradığınızı iletirseniz size uygun şubeyi önerebilirim.'),
('div_coverage_await_uni',
 'Evet efendim, şu an yalnızca İstanbul''da hizmet veriyoruz. Hangi üniversitede okuyorsunuz?'),
('div_coverage_await_uni_alt',
 'Şu an sadece İstanbul''dayız efendim. Hangi üniversite için baktığınızı öğrenebilir miyim?'),
('div_coverage_await_gender',
 'Evet, hizmetimiz İstanbul geneli efendim. Kız mı erkek öğrenci için mi bakıyorsunuz?'),
('div_coverage_await_gender_alt',
 'Şu an yalnızca İstanbul''dayız efendim. Kız mı erkek şubesi mi aradığınızı öğrenebilir miyim?'),

-- ---- LOGISTICS_PAYMENT ----
('div_payment_new',
 'Ödeme koşullarımızı en doğru şekilde iletebilmem için hangi üniversite ve cinsiyet için baktığınızı öğrenmem gerekiyor efendim; koşullar şubeye göre değişebiliyor.'),
('div_payment_new_alt',
 'Ödeme detaylarını şubeye özel paylaşıyoruz efendim. Hangi üniversite ve kız/erkek şubesi için baktığınızı söylerseniz iletebilirim.'),
('div_payment_await_uni',
 'Ödeme koşulları şubeye göre değişiyor efendim. Hangi üniversitede okuyorsunuz?'),
('div_payment_await_uni_alt',
 'Ödeme detaylarını iletebilmem için hangi üniversite için baktığınızı öğrenebilir miyim efendim?'),
('div_payment_await_gender',
 'Ödeme koşulları kız ve erkek şubelerimizde farklılık gösterebiliyor efendim, hangisine baktığınızı söyler misiniz?'),
('div_payment_await_gender_alt',
 'Ödeme detayları için kız mı erkek öğrenci için mi aradığınızı öğrenebilir miyim efendim?'),

-- ---- LOGISTICS_ELIGIBILITY ----
('div_eligibility_new',
 'Konaklamalarımız öncelikli olarak öğrencilerimize yöneliktir efendim. Detayları netleştirmek için hangi üniversite ve cinsiyet için baktığınızı öğrenebilir miyim?'),
('div_eligibility_new_alt',
 'Bu konudaki koşullarımızı şubeye göre paylaşabiliyorum efendim. Hangi üniversite ve kız/erkek şubesi için baktığınızı iletir misiniz?'),
('div_eligibility_await_uni',
 'Bu detayı sizin için netleştirebilirim efendim; öncelikle hangi üniversitede okuyorsunuz?'),
('div_eligibility_await_uni_alt',
 'Koşulları iletebilmem için hangi üniversite için baktığınızı öğrenebilir miyim efendim?'),
('div_eligibility_await_gender',
 'Bu konudaki koşullar şubeye göre değişebiliyor efendim, kız mı erkek öğrenci için mi bakıyorsunuz?'),
('div_eligibility_await_gender_alt',
 'Detayları iletebilmem için kız mı erkek şubesi mi aradığınızı öğrenebilir miyim efendim?')

ON CONFLICT (short_code) DO UPDATE SET content = EXCLUDED.content;

-- ----------------------------------------------------------------------------
-- 4. Routing rows.
--    answer_and_reanchor rows resolve canned FKs by short_code subquery.
--    activate_flow / ignore rows carry NULL FKs.
--    Clarification-state cells are intentionally NOT seeded here → escalate by
--    default. Add them later as canned copy is written.
-- ----------------------------------------------------------------------------

-- Helper note: c(x) := (SELECT id FROM canned_responses WHERE short_code = x)

INSERT INTO divergence_routing (intent, flow_state, action, canned_response_id, canned_response_alt_id) VALUES

-- PRICE (answer_and_reanchor across the 3 main firing states)
('price','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_price_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_price_new_alt')),
('price','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_price_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_price_await_uni_alt')),
('price','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_price_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_price_await_gender_alt')),

-- LOCATION
('location','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_location_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_location_new_alt')),
('location','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_location_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_location_await_uni_alt')),
('location','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_location_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_location_await_gender_alt')),

-- VACANCY
('vacancy','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_new_alt')),
('vacancy','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_await_uni_alt')),
('vacancy','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_vacancy_await_gender_alt')),

-- HOUSING (new → activate_flow; mid-flow → pure re-anchor)
('housing','new','activate_flow', NULL, NULL),
('housing','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_housing_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_housing_await_uni_alt')),
('housing','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_housing_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_housing_await_gender_alt')),

-- PARENT_SHOPPING (new → activate_flow; mid-flow → pure re-anchor)
('parent_shopping','new','activate_flow', NULL, NULL),
('parent_shopping','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_parent_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_parent_await_uni_alt')),
('parent_shopping','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_parent_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_parent_await_gender_alt')),

-- LOGISTICS_COVERAGE
('logistics_coverage','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_new_alt')),
('logistics_coverage','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_await_uni_alt')),
('logistics_coverage','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_coverage_await_gender_alt')),

-- LOGISTICS_PAYMENT
('logistics_payment','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_payment_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_payment_new_alt')),
('logistics_payment','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_payment_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_payment_await_uni_alt')),
('logistics_payment','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_payment_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_payment_await_gender_alt')),

-- LOGISTICS_ELIGIBILITY
('logistics_eligibility','new','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_new'),
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_new_alt')),
('logistics_eligibility','awaiting_university','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_await_uni'),
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_await_uni_alt')),
('logistics_eligibility','awaiting_gender','answer_and_reanchor',
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_await_gender'),
  (SELECT id FROM canned_responses WHERE short_code='div_eligibility_await_gender_alt')),

-- NO_INTENT → ignore (all firing states; junk must not escalate)
('no_intent','new','ignore', NULL, NULL),
('no_intent','awaiting_university','ignore', NULL, NULL),
('no_intent','awaiting_gender','ignore', NULL, NULL),
('no_intent','awaiting_university_clarification','ignore', NULL, NULL),
('no_intent','awaiting_campus_clarification','ignore', NULL, NULL)

ON CONFLICT (intent, flow_state) DO UPDATE
    SET action = EXCLUDED.action,
        canned_response_id = EXCLUDED.canned_response_id,
        canned_response_alt_id = EXCLUDED.canned_response_alt_id;

COMMIT;

-- ============================================================================
-- Post-apply verification (run manually; all should return expected):
--
--   -- Every answer_and_reanchor row has both FKs resolved (0 rows = good):
--   SELECT intent, flow_state FROM divergence_routing
--   WHERE action='answer_and_reanchor'
--     AND (canned_response_id IS NULL OR canned_response_alt_id IS NULL);
--
--   -- No dangling canned FKs (0 rows = good):
--   SELECT r.intent, r.flow_state FROM divergence_routing r
--   LEFT JOIN canned_responses c1 ON c1.id = r.canned_response_id
--   LEFT JOIN canned_responses c2 ON c2.id = r.canned_response_alt_id
--   WHERE (r.canned_response_id IS NOT NULL AND c1.id IS NULL)
--      OR (r.canned_response_alt_id IS NOT NULL AND c2.id IS NULL);
--
--   -- Row count sanity (expect: 24 answer_and_reanchor + 2 activate_flow + 5 ignore = 31):
--   SELECT action, count(*) FROM divergence_routing GROUP BY action ORDER BY action;
--
-- Coverage gaps left to escalate-default (intentional, add later):
--   * clarification/campus states for all answerable intents
--   * complex / non_turkish (never seeded — escalate by code default)
-- ============================================================================
