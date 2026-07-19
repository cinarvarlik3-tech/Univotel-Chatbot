-- 026_alias_hygiene.sql
-- WS1 (UNIVERSITY_ACCURACY_PLAN.md) — remove/re-scope bare-word university
-- aliases that collide with ordinary Turkish words.
--
-- Scope note: the original diagnosis assumed 'bir' (-> Biruni) and 'su' /
-- 'yu' (-> Sabancı / Yeditepe) were alias-table rows. Investigation showed
-- otherwise:
--   - 'bir' was never an alias row. It was normalize("biruni")/"BİRUNİ"
--     being incorrectly chewed down to "bir" by a substring (not
--     word-boundary) suffix strip in app/layers/matching.py:normalize().
--     Fixed in code (see that file's normalize()); no data change needed
--     here, and none is included below.
--   - 'su' (Sabancı, short_name="SU") and 'yu'/'yü' (Yeditepe,
--     short_name="YÜ") are NOT alias-table collisions at all — they match
--     via Tier 1 exact match against university_short_name, which exists
--     independently of the alias table. Deleting an alias row would be a
--     no-op, and "SU"/"YÜ" are those universities' genuine real-world
--     abbreviations, not junk data. Changing Tier 1 semantics is a larger,
--     higher-blast-radius change (it's the lookup path for every
--     short_name in the system, e.g. KHAS, BOUN, GSU) and is deliberately
--     OUT OF SCOPE for this migration — flagged to the developer instead
--     of guessed at.
--
-- What IS a genuine alias-table collision, fixed below:
--   - 'teknik' (parent alias -> İTÜ) collides with the common Turkish word
--     "teknik" ("technical"). İTÜ already resolves via the 'itu'/'itü'
--     aliases and campus-specific short names, so this is a safe delete
--     with no replacement needed.
--   - 'bilgi' (parent alias -> İstanbul Bilgi Üniversitesi) collides with
--     "bilgi" ("information"), which appears in nearly every greeting
--     ("...hakkında bilgi alabilir miyim?").
--   - 'rumeli' (parent alias -> İstanbul Rumeli Üniversitesi) collides with
--     "Rumeli Hisarı" (a Boğaziçi campus reference, fixed separately in
--     027_campus_aliases.sql).
--
-- IMPORTANT — why the replacement for 'bilgi'/'rumeli' is "istanbul X", not
-- "X üniversitesi": app/layers/matching.py:normalize() strips a trailing
-- "üniversitesi"/"uni"/"üni" WORD (word-boundary-aware, post the normalize()
-- fix in this same changeset). That means "bilgi üniversitesi" normalizes
-- down to the SAME string as the bare word "bilgi" — a naive "just append
-- üniversitesi" replacement collapses right back into the original
-- collision and fixes nothing (caught by tests/test_alias_collision_check.py
-- during implementation). "istanbul bilgi" / "istanbul rumeli" do NOT end in
-- a suffix word, so they survive normalization intact and stay
-- distinguishable from the bare collision word.
--
-- Both 'bilgi' and 'rumeli' parents have NO row in `universities` (they are
-- alias-table-only "virtual" parents in `parent_universities`), so the alias
-- table is their ONLY reachable name in the system — the bare form must be
-- replaced, not simply deleted, or the university becomes unreachable via
-- the deterministic path entirely (falls back to the LLM's belt guess).

BEGIN;

-- teknik -> İTÜ parent: delete, no replacement needed.
DELETE FROM university_aliases
WHERE alias = 'teknik'
  AND parent_university_id = 'b77ff96a-eb03-a055-0fc7-0933ae778a5c'::uuid;

-- bilgi -> İstanbul Bilgi Üniversitesi parent: replace with a non-collapsing
-- multi-token form.
DELETE FROM university_aliases
WHERE alias = 'bilgi'
  AND parent_university_id = '43237726-8a05-2ef1-cce7-072f7bbf99d3'::uuid;

INSERT INTO university_aliases (parent_university_id, alias)
SELECT '43237726-8a05-2ef1-cce7-072f7bbf99d3'::uuid, 'istanbul bilgi'
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE parent_university_id = '43237726-8a05-2ef1-cce7-072f7bbf99d3'::uuid
      AND alias = 'istanbul bilgi'
);

-- rumeli -> İstanbul Rumeli Üniversitesi parent: replace with a
-- non-collapsing multi-token form.
DELETE FROM university_aliases
WHERE alias = 'rumeli'
  AND parent_university_id = '1ba00140-e42e-e923-1717-b06231a9d387'::uuid;

INSERT INTO university_aliases (parent_university_id, alias)
SELECT '1ba00140-e42e-e923-1717-b06231a9d387'::uuid, 'istanbul rumeli'
WHERE NOT EXISTS (
    SELECT 1 FROM university_aliases
    WHERE parent_university_id = '1ba00140-e42e-e923-1717-b06231a9d387'::uuid
      AND alias = 'istanbul rumeli'
);

COMMIT;
