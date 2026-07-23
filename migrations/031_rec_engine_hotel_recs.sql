-- RecEngine multi-property recommendations: persist full eligible hotel list per run.

ALTER TABLE rec_engine_logs
    ADD COLUMN IF NOT EXISTS hotel_recs uuid[];
