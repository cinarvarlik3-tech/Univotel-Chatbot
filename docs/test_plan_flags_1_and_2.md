# Univotel Chatbot — Pre-V1 Test Plan: Flags 1 & 2

**Scope:** Two pre-deployment concerns from the last test review.
**Flag 1 — Hotel data-state audit:** the GK Regency incident proved recommendation correctness depends on data flags (`is_visible`, `priority_score`, links, label-maps) being in the right state, and a wrong flag fails *silently*. This suite audits every such flag.
**Flag 2 — Alias activation & collision:** the diacritic-normalization fix (`normalize()` both sides of the alias comparison) activated ~200 previously-dead aliases at once. This suite proves they resolve correctly and none collide.

**Companion artifacts (run these, this doc explains them):**
- `hotel_data_state_audit.sql` — Suite A (data audit). Every query returns rows **only on failure**.
- `alias_collision_check.py` — Suite B automated portion (C1–C6). Exit 0 = pass.

---

## 0. Conventions & environment

**Test IDs:** `A#` = hotel data-state (SQL). `B#` = alias (automated). `F#` = functional conversational.

**Pass convention for audits:** a passing SQL check returns **zero rows**; any row is a finding. The automated Python check exits `0` on pass, `1` on any hard failure.

**Environment / preconditions (all functional tests):**
- App running, connected to the ChatBot DB and Chatwoot.
- `TESTING_LIMITATIONS_MODE = on`, and the test phone number is on the 2-number allowlist. (Confirmed working: off-allowlist conversations are correctly ignored.)
- `INTEGRITY_CHECK_BYPASS = off` for at least one run, so the startup integrity check actually asserts (it currently flags one orphan — see Exit Criteria).
- Watch the terminal logs live; several assertions are log-based.

**Test isolation — MANDATORY teardown between functional tests.** Conversations are stateful (`flow_state`, `pending_parent_university_id`, etc.). A test that leaves the conversation parked will poison the next. Reset between every functional test:

```sql
-- TEARDOWN: reset the test conversation to a clean pre-flow state.
-- Replace 52 with your test conversation's cw_id.
UPDATE conversations
SET flow_state = NULL,
    university_id = NULL,
    gender = NULL,
    pending_parent_university_id = NULL,
    ilgili_otel = NULL,
    ilgili_otel_set_at = NULL,
    ilgili_otel_set_by = NULL,
    auto_run_count = 0,
    manual_run_count = 0
WHERE cw_id = 52;
```
Also clear the Chatwoot conversation's labels and custom attributes in the UI (or via API) before a fresh run, so stale state from a prior test isn't mistaken for a result. **Run teardown, confirm the reset, then start the next test.**

**Turkish-message note:** all lead-side and bot-side messages below are written in the exact Turkish they should appear as. Bot escalation questions are built from `parent_universities.question` = `"Hangi {name} kampüsü efendim? {campuses}"` with per-campus vowel-harmony suffixes. **Campus ORDER within a question is not asserted** unless `get_campuses_for_parent` has an `ORDER BY` — assert the *set* of campuses and the *correct suffix per campus*, not the sequence (see F-note-1).

---

## SUITE A — Hotel data-state audit (Flag 1)

Run the entire `hotel_data_state_audit.sql` file. Below: what each check means and how to act on a finding. A1–A11 must return zero rows; A12 is a review report meant to return rows for eyeballing.

| ID | Asserts | A non-empty result means | Remediation |
|----|---------|--------------------------|-------------|
| **A1** | Visible recommendable hotels have `priority_score > 0` | A visible hotel is unrankable/mis-rankable | Set a real priority_score, or hide it if not ready |
| **A2** | No hotel is fully-wired-but-hidden (**the GK Regency check**) | A hotel ready to recommend has `is_visible=false` | Confirm intent; flip to true if it should be live |
| **A3** | Visible hotels have ≥1 university link | Dead inventory — can't be recommended to anyone | Add `hotel_accessible_universities` links or hide |
| **A4** | Visible hotels have a label-map row | `ilgili_otel` silently drops for this hotel | Seed `hotel_chatwoot_label_map` row |
| **A5** | `gender_scope ∈ {male,female,mixed}` | Gender filter breaks silently for this hotel | Fix the scope value |
| **A6** | Selectable hotels + both sentinels have `response_schemas` | Engine selects it, has nothing to send | Wire response_schemas |
| **A7** | Both sentinels exist, hidden, wired | A sentinel is missing/visible/unwired | Restore the sentinel row + schema |
| **A8** | Legacy hotels retired (gone or hidden+unlinked) | Legacy hotel can leak into results | Complete deletion / de-list |
| **A9** | Link table referential integrity | Orphan link points at deleted hotel/university | Delete orphan links |
| **A10** | No orphan label-map rows | Map points at deleted hotel | Delete orphan map row |
| **A11** | No duplicate `chatwoot_list_value` | Two hotels → same Chatwoot option (ambiguous write) | De-duplicate the mapping |
| **A12** | *(review)* per-university RecEngine ranking | — | Confirm the intended winner is `rec_rank = 1` for each campus you serve |

**A12 is the most important preventive check** — it's the GK Regency scenario made visible before a lead hits it. For each campus you actively serve, run A12 with that `university_id` and confirm the hotel you *expect* to be recommended sits at `rec_rank = 1`. If it doesn't, a flag is wrong (hidden winner, mis-scored competitor). Do this for at least: İTÜ Maslak, İTÜ Maçka, and 2–3 other high-traffic campuses.

---

## SUITE B — Alias automated checks (Flag 2, automated portion)

Run:
```bash
export DATABASE_URL='postgresql://…'   # ChatBot DB
python3 alias_collision_check.py            # or --verbose to dump every group
```

| ID | Check | Severity | Pass condition |
|----|-------|----------|----------------|
| **B1 / C1** | Two aliases normalize to the same string but point to **different** targets | HARD | none |
| **B2 / C2** | Redundant duplicates (same normalized form, same target, e.g. `itü`/`İTÜ`→parent) | WARN | informational |
| **B3 / C3** | Alias shadowed by a full university **name** (Tier 1 runs first → alias never fires) | HARD | none |
| **B4 / C4** | Alias overlaps a **short_name** | INFO | alias correctly wins post-fix |
| **B5 / C5** | Alias normalizes to empty string | HARD | none |
| **B6 / C6** | Exact duplicate raw alias (UNIQUE constraint check) | HARD | none |

**The one to watch is C1.** With diacritics stripped, distinct-looking aliases can collapse to the same normalized string. That's *fine* when they point to the same target (C2, harmless) but a **bug** when they point to different targets (C1) — the matcher returns whichever it hits first and the other target becomes unreachable. Example of what C1 would catch: if "işık" (Işık Üni) and some other alias both normalized to "isik" but pointed at different universities. Exit code `0` from the script = C1/C3/C5/C6 all clean.

**Run C4 with `--verbose` once** and read the list: it shows every alias that overlaps a `short_name`. After the tier-order fix these are all supposed to resolve via the alias (Tier 2) not the short_name (Tier 3). This is the exact class of bug that caused the escalation failure ("itü" shadowed by Maslak's short_name "İTÜ"), so confirming the overlaps now resolve alias-first is worthwhile even though it's INFO severity.

---

## SUITE F — Functional alias resolution (Flag 2, conversational)

These exercise the ~200 newly-live aliases end-to-end across every resolution *type*. Testing best practice: one representative per equivalence class, plus the specific high-risk collision case, plus negative cases — not all 262 aliases.

Every test: **run teardown first.** Then the lead-side messages are sent from the allowlisted test phone; the bot-side messages are the expected responses. "PASS" requires both the correct message AND the correct resolved DB state (verify with the check query given).

---

### F1 — Parent-escalating diacritic alias (Boğaziçi)
**Class:** parent-level alias containing Turkish diacritics → must escalate. This class was 100% dead before the fix.

**Preconditions:** teardown run; conversation clean.

| Step | Actor | Message |
|------|-------|---------|
| 1 | Lead | `Merhabalar, üniversiteme yakın konaklama arıyorum` |
| 2 | Bot | `Size daha iyi yardımcı olabilmek adına hangi üniversitede okuduğunuzu öğrenebilir miyim?` |
| 3 | Lead | `boğaziçi` |
| 4 | Bot | `Hangi Boğaziçi Üniversitesi kampüsü efendim? Ana Kampüs mü, Anadolu Hisarı mı?` |
| 5 | Lead | `Ana Kampüs` |
| 6 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions:**
- Step 4 fires (escalation happened — this is the core assertion).
- Suffix harmony correct: `Ana Kampüs` → **mü** (last vowel ü), `Anadolu Hisarı` → **mı** (last vowel ı).
- After step 5, DB resolves to the Boğaziçi Ana Kampüs `university_id`:
  ```sql
  SELECT university_id, pending_parent_university_id, flow_state
  FROM conversations WHERE cw_id = 52;
  -- expect: university_id = Boğaziçi Ana Kampüs, pending_parent cleared, flow past escalation
  ```

**Teardown:** run reset SQL.

---

### F2 — Parent-escalating ASCII variant (bogazici)
**Class:** ASCII-typed version of a diacritic alias → must resolve identically to F1. Confirms normalization maps both spellings to the same alias.

| Step | Actor | Message |
|------|-------|---------|
| 1 | Lead | `merhaba` |
| 2 | Bot | `Size daha iyi yardımcı olabilmek adına hangi üniversitede okuduğunuzu öğrenebilir miyim?` |
| 3 | Lead | `bogazici` |
| 4 | Bot | `Hangi Boğaziçi Üniversitesi kampüsü efendim? Ana Kampüs mü, Anadolu Hisarı mı?` |

**Assertion:** identical escalation to F1 despite ASCII input. **Teardown.**

---

### F3 — Üsküdar (three-campus escalation, mixed suffixes)
**Class:** parent escalation with a 3-campus list and mixed vowel-harmony suffixes.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `üsküdar` |
| 4 | Bot | `Hangi Üsküdar Üniversitesi kampüsü efendim? Güney mi, Merkez mi, Çarşı mı?` |
| 5 | Lead | `Merkez` |
| 6 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions:** three campuses listed; suffixes `Güney`→**mi**, `Merkez`→**mi**, `Çarşı`→**mı**. Resolves to Üsküdar Merkez. **Teardown.**

---

### F4 — Doğuş (rounded-vowel suffixes mu/mü)
**Class:** verifies the `mu`/`mü` branch of vowel harmony (rounded back/front vowels), which F1–F3 don't cover.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `doğuş` |
| 4 | Bot | `Hangi Doğuş Üniversitesi kampüsü efendim? Dudullu mu, Çengelköy mü?` |

**Assertions:** `Dudullu`→**mu** (last vowel u), `Çengelköy`→**mü** (last vowel ö). This is the only test that exercises mu/mü — if the harmony helper only handles mı/mi, it fails here. **Teardown.**

---

### F5 — Abbreviation → single-campus, resolves directly (SU / Sabancı)
**Class:** short abbreviation alias, single-campus target → **no escalation**, resolves straight to gender.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `su` |
| 4 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions:** **no** campus question (Sabancı is single-campus → escalation must NOT fire); resolves directly to Sabancı. Verify `university_id` = Sabancı, `pending_parent_university_id` IS NULL. **Teardown.**

> Repeat F5 quickly for `ku` (Koç), `gsü` (Galatasaray), `fbü` (Fenerbahçe), `acu` (Acıbadem), `prü` (Piri Reis) — each should resolve directly with no escalation. These abbreviations were all dead pre-fix.

---

### F6 — Direct campus alias, no escalation (taşkışla → İTÜ Maçka)
**Class:** sub-location alias pointing at a specific campus → resolves directly even though İTÜ is multi-campus (the alias targets the campus, not the parent).

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `taşkışla` |
| 4 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions:** **no** İTÜ campus question (the alias points at İTÜ Maçka directly); resolves to İTÜ Maçka `university_id`. This confirms campus-level aliases bypass escalation while parent-level ones trigger it. **Teardown.**

---

### F7 — ★ CROSS-PARENT COLLISION (the critical one) ★
**Class:** two different parents each have an "Ayazağa" campus (İTÜ and Beykent). A lead who escalates under Beykent then answers "Ayazağa" must resolve to **Beykent** Ayazağa, NOT İTÜ Ayazağa. This tests that the campus-reply match is scoped to the pending parent's campuses, not the global alias table.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `beykent` |
| 4 | Bot | `Hangi Beykent Üniversitesi kampüsü efendim? Ayazağa mı, Beykent mi, Beylikdüzü mü, Taksim mi?` |
| 5 | Lead | `Ayazağa` |
| 6 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions (the whole point):**
- After step 5, resolves to **Beykent Ayazağa**, not İTÜ Ayazağa:
  ```sql
  SELECT c.university_id, u.name
  FROM conversations c JOIN universities u ON u.id = c.university_id
  WHERE c.cw_id = 52;
  -- expect u.name LIKE 'Beykent% Ayazağa%', NOT any İTÜ row
  ```
- If it resolves to İTÜ Ayazağa, the campus-reply matcher is querying the global alias table instead of `university_parent_map WHERE parent_university_id = <Beykent>`. That's a scope bug — the exact collision we designed the scoped-match to prevent.

**Teardown.** This is the single most important functional test in the suite — run it twice to be sure.

---

### F8 — Campus reply that is invalid / not in the offered set
**Class:** negative — lead answers the escalation with something not among the offered campuses.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `itü` |
| 4 | Bot | `Hangi İstanbul Teknik Üniversitesi kampüsü efendim? Maslak mı, Maçka mı, Tuzla mı?` |
| 5 | Lead | `Beşiktaş` |
| 6 | Bot | *(defined behavior — see below)* |

**Assertion — this is a DESIGN-GAP PROBE, not a known-good path.** "Beşiktaş" is not an İTÜ campus. Expected behavior must be one of: (a) re-ask the campus question, (b) escalate to a human, (c) a graceful fallback. What it must **not** do: silently resolve to a wrong campus, crash, or hang. **Record the actual behavior.** If it's undefined/ugly, that's a finding for FallBack scope (this is exactly the kind of off-rails case FallBack exists to catch) — not necessarily a V1 blocker, but must be known. **Teardown.**

---

### F9 — Multi-word alias (kadir has, ibn haldun, 29 mayıs)
**Class:** aliases containing spaces → confirm the matcher handles multi-token aliases (normalization + comparison must not split on whitespace).

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `kadir has` |
| 4 | Bot | `Kız öğrenci için mi konaklama arıyordunuz, erkek öğrenci için mi?` |

**Assertions:** resolves directly to Kadir Has (single-campus). Repeat for `ibn haldun` and `29 mayıs`. **Teardown.**

---

### F10 — Negative: unrecognized university
**Class:** input matching nothing → must not false-match via Levenshtein into a wrong university.

| Step | Actor | Message |
|------|-------|---------|
| 3 | Lead | `qwerty üniversitesi` |
| 4 | Bot | *(expected: re-ask, out-of-Istanbul path, or human escalation — NOT a silent wrong match)* |

**Assertion:** does not resolve to a real university. Confirm `university_id` stays NULL and the bot did not proceed to gender with a bogus match. Records the negative-path behavior. **Teardown.**

---

## F-note-1 — Campus ordering caveat

The escalation question's campus order comes from `get_campuses_for_parent`. If that query has no `ORDER BY`, the order is **nondeterministic** and may differ run-to-run. Two consequences for these tests:
1. Don't fail a test purely because campus order differs from what's written above — assert the *set* of campuses and the *per-campus suffix*, not the sequence.
2. Consider this itself a minor finding: for a consistent lead experience, `get_campuses_for_parent` should probably `ORDER BY campus_label` (or a deliberate display order). Flag for Claude Code if order matters to you.

---

## Exit criteria (before calling V1 done)

**Must pass (blockers):**
- Suite A: A1–A11 all return zero rows. A12 shows the intended winner at rank 1 for every served campus.
- Suite B: `alias_collision_check.py` exits 0 (C1, C3, C5, C6 clean).
- F1, F3, F5, F6, F7 pass. **F7 especially** — the cross-parent collision.
- The one remaining startup orphan (`22490d0d…`, missing `university_chatwoot_label_map` row) is resolved, so the integrity check is clean with `INTEGRITY_CHECK_BYPASS=off`.

**Should pass (strongly recommended, but FallBack may absorb):**
- F4 (mu/mü harmony), F2, F9.
- F8 and F10 (off-rails behavior) — *record* the behavior even if imperfect; these define FallBack's scope rather than blocking V1.

**Informational:**
- B2/C2 redundant-alias count (trim if noisy), B4/C4 short-name overlaps (confirm alias-first), F-note-1 campus ordering.

**Recommended regression anchor:** keep the original conv-52 İTÜ→erkek walkthrough as a smoke test to re-run after any future change — it exercises escalation, campus resolution, gender, RecEngine ranking, and attribute writes in one conversation.
