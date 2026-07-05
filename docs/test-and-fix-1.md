# Univotel Chatbot — Test Findings & Fix List

**Source:** First real end-to-end test (conversation 52, İTÜ + male lead). Terminal logs + DB queries analyzed. This document lists confirmed bugs with root causes, not hypotheses — each was verified against logs or SQL output.

**Priority order:** 1 (RecEngine) and 3 (orphan universities) are quick/one-line. 2 (escalation) is a real feature build. 4 (attribute timing) is a design decision.

---

## ✅ Confirmed working — DO NOT TOUCH

The test verified these are functional; changes here risk regressions:
- HMAC webhook verification
- The Gemini retry ladder (caught a real 503 mid-run, recovered on attempt 2 — logs at 20:07:20→20:07:27)
- TESTING_MODE allowlist (correctly ignored conv 836, off-allowlist)
- Manual `tag` trigger → TagAssigner run
- Response schema resolution & ordering (Academia Residence responses sent in correct order)
- TagAssigner labeling (correctly applied `ogrenci`, `universitede`)
- The deterministic attribute writes themselves (`custom_attributes` POST succeeded — university/gender/ilgili_otel all written correctly *when the write ran*)
- Gender eligibility filtering (all three İTÜ candidates were correctly eligible for a male lead — `male` and `mixed` both passed; see Fix 1 for why this matters)

---

## FIX 1 — RecEngine ignores priority_score (CONFIRMED, likely one line)

**Symptom:** For a male lead at İTÜ Ayazağa, RecEngine returned **Academia Residence (priority 80)** when **GK Regency Suites (priority 100)** was eligible and higher-scored.

**Proof it's a bug, not correct behavior:**
Both hotels are `gender_scope = 'mixed'` (verified via SQL), so both are eligible for a male lead. Among eligible candidates the highest `priority_score` must win. GK Regency (100) should beat Academia Residence (80). It didn't.

**Root cause — confirmed by reproduction:** Running the selection manually WITH ordering returns the correct winner:
```sql
SELECT h.name, h.gender_scope, h.priority_score
FROM hotels h
JOIN hotel_accessible_universities hau ON h.id = hau.hotel_id
WHERE hau.university_id = 'a17cc4c1-12b8-4762-9731-64ba9235d0de'
  AND h.gender_scope IN ('male', 'mixed')
ORDER BY h.priority_score DESC;
-- → GK Regency (100) first. CORRECT.
```
RecEngine returned Academia Residence, so RecEngine's actual query is **missing `ORDER BY priority_score DESC`** (returning DB-default/insertion order, which happens to be Academia Residence).

**Fix:**
- Add `ORDER BY priority_score DESC` to RecEngine's candidate selection, then take the first row (or `LIMIT 1`).
- Confirm the gender filter clause is `gender_scope IN ('male'/'female' as appropriate, 'mixed')` — `mixed` must always be eligible regardless of lead gender. (This part appears already correct; don't remove it.)

**Also add (important for future debugging):** RecEngine currently logs NOTHING about its selection — it ran ~7s and emitted a result with no visibility (this is why the bug was invisible until now, masked by the old Academia-forced-to-10000 test hack). Add a log line dumping the candidate set with scores and the chosen winner, e.g.:
```
RecEngine: conv=X uni=Y gender=Z candidates=[(GK Regency,100),(Academia Residence,80),(Academia Seyrantepe,78)] → selected=GK Regency
```
So the next test is debuggable without manual SQL.

---

## FIX 2 — InfoGatherer parent-escalation not implemented (feature build)

**Symptom:** Lead said "itü". InfoGatherer went **straight to the gender question** — no "Hangi İTÜ kampüsü?" escalation. It resolved "itü" to a single campus (İTÜ Ayazağa) and proceeded, producing a wrong/arbitrary campus assignment.

**Root cause — confirmed by logs:** When "itü" arrived (20:04:07), the logs show webhook → upsert → 200, then immediately the gender question outbound. There is **zero log activity** for a parent lookup, `university_parent_map` query, or campus question. The escalation code path does not exist — InfoGatherer is still running the pre-escalation "resolve alias → proceed" flow.

**The data is ready** (this session seeded it): `university_aliases.parent_university_id`, `parent_universities` (with `question` templates), `university_parent_map` (with `campus_label`s). Only the InfoGatherer code to *use* them is missing.

**Fix — implement the escalation branch in InfoGatherer's university resolution:**
```
match free text against university_aliases →
  alias.university_id is set (campus-level alias)     → resolve directly, proceed (no escalation)
  alias.parent_university_id is set (parent-level)    →
      SELECT university_id, campus_label
      FROM university_parent_map WHERE parent_university_id = <parent>
      → exactly 1 campus → resolve to it directly (no question)
      → >1 campuses      → SEND the escalation question, set awaiting-campus state,
                           the lead's reply resolves to the specific campus
```

**The escalation question (two runtime pieces — see this session's spec):**
1. **Fill `{campuses}` slot** from the live `campus_label` list under the parent (as many `[label] mı` clauses as there are campuses; auto-updates when campuses added). Template is in `parent_universities.question`: `"Hangi {name} kampüsü efendim? {campuses}"`.
2. **Vowel harmony** on the `mı/mi/mu/mü` particle per campus label — last vowel of the label decides: {a,ı}→mı, {e,i}→mi, {o,u}→mu, {ö,ü}→mü. Tiny helper, runs per label.

Example: İTÜ (Maçka/Ayazağa/Tuzla) → `"Hangi İstanbul Teknik Üniversitesi kampüsü efendim? Maçka mı, Ayazağa mı, Tuzla mı?"`

**Campus-selection reply matching (important — scope it):** when the lead answers the campus question, match their reply against **only the campuses of that parent** (the `university_parent_map` rows for that `parent_university_id`), NOT against the global alias table. This prevents cross-university collisions (e.g. both İTÜ and Beykent have an "Ayazağa" campus — a lead who said "Beykent" then "Ayazağa" must resolve to Beykent Ayazağa, not İTÜ). The escalation reply is a constrained match within the parent's campus set.

---

## FIX 3 — Two universities missing parent-map rows (one-time seed)

**Symptom (startup CRITICAL, working as designed):**
```
CRITICAL app.health.integrity_check INTEGRITY: 2 university/universities have no
university_parent_map row ['22490d0d-d25a-474f-b158-f0e602e181ee',
'874e42ea-e599-4d29-a893-fb8b133513bb']
```
Every university must have a parent (option-a rule). These two slipped through the seed. The health check correctly caught it.

**Fix:** Identify them, then add their parent-map rows.
```sql
SELECT id, name FROM universities
WHERE id IN ('22490d0d-d25a-474f-b158-f0e602e181ee',
             '874e42ea-e599-4d29-a893-fb8b133513bb');
```
Then either map them to an existing parent (if they're campuses of one already seeded) or create their own single-campus parent (if standalone). Follow the same pattern as the rest of `university_parent_map`. Re-run the health check to confirm the CRITICAL clears.

---

## FIX 4 — Attribute timing: InfoGatherer writes nothing (design decision)

**Finding — confirmed by logs:** The ONLY `custom_attributes` POST in the entire flow occurred at **20:07:35, inside the TagAssigner run** (triggered by the manual "tag" at 20:06:57). During the InfoGatherer flow (20:03–20:04), **zero attributes were written** — not even gender. What appeared in Chatwoot came entirely from TagAssigner's deterministic attribute resolver.

**This is not a bug per se — it's an unintended consequence.** TagAssigner's Router writes university/gender/ilgili_otel deterministically (correct, and independent of the LLM prompt — which is why attributes appeared despite the prompt not mentioning them). But it means: **a lead who completes the InfoGatherer flow has BLANK attributes in Chatwoot until the first TagAssigner run** (which is trigger/idle/nightly-based, so could lag minutes to hours).

**Decision needed:**
- **Option A (recommended):** InfoGatherer publishes university + gender on flow completion (it has both in the DB by then), and ilgili_otel from the RecEngine result it just received. TagAssigner continues to maintain/re-write them thereafter. → attributes are immediate.
- **Option B:** Leave as-is (TagAssigner-only). Simpler, but attributes lag until first tag run.

Recommend A — the same deterministic resolver logic already exists (TagAssigner's `attribute_resolver`); it just needs to also run at InfoGatherer completion. No new mechanism, just an additional call site.

---

## Suggested fix order

1. **Fix 1** (RecEngine `ORDER BY` + selection logging) — one line + logging, highest impact (wrong hotels to real leads).
2. **Fix 3** (orphan universities) — quick seed, clears the startup CRITICAL.
3. **Fix 2** (escalation branch) — the real build; needed before parent-alias inputs work at all.
4. **Fix 4** (attribute timing) — decision + additional call site.

Re-run the conv-52 İTÜ test after Fixes 1–3: expect "itü" → campus escalation question → correct campus → RecEngine returns GK Regency (100) → correct attributes written promptly. That single test exercises all three.