# Suite D-FIX2 — Spec 020.1 Verification (failed cases only + Fix 2 regression watch)

**Scope:** Reruns ONLY the Suite D-FIX cases that failed or were partial, plus a tight regression check on the paths Fix 2 (`normalize` punctuation) could disturb. Everything that passed in D-FIX is not re-run.

**Do NOT re-run (passed in D-FIX):** A1, A3, A6, B1, B2, C2, C3, C4, D1, D3, D4, D5, D6, E2, E3, and all of D8. (A1/A3/A6/C2/C3 appear below ONLY as Fix-2 regression spot-checks, not full re-tests — see Part R.)

**Teardown between cases:** standard reset of the test conversation (`flow_state, university_id, gender, pending_parent_university_id, clarification_attempt, last_divergence_intent, divergence_repeat_count, bot_enabled`) + clear Chatwoot labels/attributes. For E1 set `DEBOUNCE_WINDOW_SECONDS=3`.

**Legend:** *Silent escalate* = `human_needed` state **+ label** + no message · *RecEngine fires* = advances to `recengine_running` / rec sent.

---

## Part 1 — Fix 1 reruns (invert the no-match gate)

Setup for all: opener `merhaba` → bot asks `hangi` → state `awaiting_university`.

| ID | Send | Pass condition | Result |
|----|------|----------------|--------|
| **C1** | `konum neresi` | Routes to divergence → `location` → bot sends the district-neutral location canned. **NOT** a university-clarification prompt. | PASSED | 
| **A4** | 4 different questions back-to-back: `fiyat ne` → `sadece İstanbul mu` → `konum neresi` → `ödeme nasıl` | Each → its own divergence answer + re-anchor. **No escalate** across all 4. State stays `awaiting_university`. `divergence_repeat_count` never exceeds 1. None treated as a university answer. | PASSED |
| **B3** | Same intent ×3: `fiyat ne` → `fiyat söyle` → `ya fiyat` | Turn 1 → price primary. Turn 2 → price alternate. Turn 3 → **silent escalate WITH `human_needed` label**. `divergence_repeat_count` 1→2→3. **Not** an early clarification-triggered escalate. | PASSED |
| **F1.new** (typo guard) | `Marmaraa` | Recognizes 'marmaraa' as 'marmara' via fuzzy match and asks for campus rather than university name clarification. | PASSED |
| **F1.clar** (typo, 2nd strike) | After F1.new sent one clarify, send `Marmaraaa` again | Second university-attempt failure → silent escalate **with label** (clarification_attempt cap). Confirms escalation authority in the clarification state. | NOT APPLICABLE |

**If C1/A4 still clarify:** the old `classify_university_reply` block wasn't removed from `_run_deterministic_extraction`, or the redundant `is_near_miss` is still in that path.

F1.clar EXPLANATION: Since F1.new's definition changed it has made F1.clar unapplicable. All tests now pass. 

---

## Part 2 — Fix 2 rerun (punctuation in normalize)

| ID | Setup | Send | Pass condition | Result |
|----|-------|------|----------------|--------|
| **A2** | opener `merhaba` → `hangi`, state `awaiting_university` | `İTÜ, kız` (with comma) | Gender→female, uni→İTÜ (parent) extracted from the comma'd message identically to `İTÜ kız`. Bot asks campus once (gender retained). Then `Maslak` → RecEngine. The comma must no longer break the match. | PASSED |
| **A2.b** (Ayazağa via Fix 3) | continue A2 to the campus question | `Ayazağa` | Campus resolves via the new alias → RecEngine fires. (Also validates Fix 3 end-to-end.) | PASSED |

---

## Part 3 — E1 rerun (two variables — read carefully)

Requires `DEBOUNCE_WINDOW_SECONDS=3`. **E1 tests two things at once now** — Fix 1 (no stray second message) and debounce (burst coalesces). Record both observations separately.

| ID | Action | Pass condition | Result | 
|----|--------|----------------|--------|
| **E1** | In `awaiting_university`, send 3 messages within ~1s: `fiyat ne` · `İTÜ` · `kız` | **(a) Debounce:** the three coalesce into ONE processed turn (check logs: one `process_message` invocation, not three). **(b) Fix 1:** the turn resolves to a SINGLE bot response — İTÜ (parent) + gender→female extracted, one campus-clarification question — with **no** trailing university-clarification message. | PASSED |

E1 DETAIL: Initially failed but a quick fix was applied during testing saved it. Turns out the message timestamp
happening in the chatbot process was resulting in messages sent consecutively with no pause to be stamped as
3+ seconds, which caused them to be recognized as separate messages instead of mixed input. The fix was to switch 
the timestamp to customer input rather than the system's internal recognition, which resulted in success.

**Read the result on two axes:** if E1 still emits two messages, that's Fix 1 (stray clarify). If it emits three separate replies (one per message), that's debounce not buffering. They are different failures — don't conflate.

---

## Part R — Fix 2 regression spot-checks (NOT full re-tests)

Fix 2 changes `normalize()`, which every matcher uses. These are fast single-message confirmations that previously-passing matching still works. One message each; confirm the bot still resolves as before.

| ID | Send (in stated state) | Must still | Result |
|----|------------------------|------------|--------|
| **R1** | `İTÜ kız` (no comma) in `awaiting_university` | Resolve exactly as it did in D-FIX A2 (parent → campus ask, gender retained). Confirms Fix 2 didn't regress the no-punctuation path. | PASSED |
| **R2** | `Marmara Üniversitesi Göztepe, erkek öğrenci` in `awaiting_university` | Still fire RecEngine directly (D-FIX A1 behavior). The comma before "erkek" must not break the two-slot extraction. | PASSED |
| **R3** | `GK Regency Suites` in `awaiting_university` | Still serve the hotel schema → `completed` (D-FIX A5 rerun behavior). Confirms hotel `normalize` path intact. | PASSED |
| **R4** | opener `merhaba` | Still greet → `hangi`. Confirms phrase-gate greeting/widget normalize path intact. | PASSED |

**If any of R1–R4 regress:** Fix 2 disturbed a matcher — check the pre-apply audit (Spec 020.1 §2.3) was actually run and `test_matching.py` passed.

---

## Done-gate

- [ ] C1, A4, B3 pass (Fix 1). F1.new / F1.clar confirm typos still clarify/escalate correctly.
- [ ] A2 passes with the comma; A2.b confirms Ayazağa (Fix 3).
- [ ] E1 coalesces to one turn AND one response (both axes).
- [ ] R1–R4 unchanged (Fix 2 no regression).
- [ ] `pytest` green — `test_matching.py` unchanged-and-passing (hard gate).
- [ ] README carries the D2/D7 note.
- [ ] One happy-path smoke: `merhaba` → uni → gender → rec, end to end.

If all green: divergence handling is complete. Ship.
