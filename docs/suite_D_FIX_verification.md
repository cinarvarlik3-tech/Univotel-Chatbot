# Suite D-FIX — Spec 020 Fix Verification (targeted, no regression retest)

**Scope:** ONLY the functionality changed in Spec 020. Does NOT retest anything that passed in Suite D. Run after Spec 020 (Parts A–E) is deployed.

**Skip entirely (already passing, do not re-run):** D1.1–1.6, D1.8–1.10, D2.1, D2.3, D2.6, D3.1–3.4 (behavior — copy is re-checked in Part C below), D4.3, D4.4, D5.1, D5.2, D7.1, D7.2, D7.4, D8.x.

**Teardown between cases** (same as Suite D — run before each): reset the test conversation's `flow_state, university_id, gender, pending_parent_university_id, clarification_attempt, last_divergence_intent, divergence_repeat_count, bot_enabled` and clear Chatwoot labels/attributes. For debounce cases (Part E) set `DEBOUNCE_WINDOW_SECONDS=3`.

**Legend:** *Bot sends X* = outbound canned appears · *Silent escalate* = `human_needed` state **+ label** + no message · *RecEngine fires* = advances to `recengine_running`/rec sent.

---

## PART A — Uniform pre-RecEngine pipeline (the spine)

Highest priority. Each case targets a specific A-mechanism. Setup for A2–A6: opener `merhaba` → bot asks `hangi` → state `awaiting_university`.

| ID | Setup | Send | Pass condition | Result |
|----|-------|------|----------------|--------|
| **A1** | `awaiting_university` | `Marmara Üniversitesi Göztepe, erkek öğrenci` | Gender→male, uni→Marmara, campus→Göztepe all from ONE message → **RecEngine fires directly**. No clarify, no gender ask, no escalate. `chatbot_logs`: no classifier call this turn. | PASSED |
| **A2** | `awaiting_university` | `İTÜ, kız` | Gender→female extracted; uni→İTÜ (parent). Bot asks **campus once** (gender NOT re-asked). Then send `Ayazağa` → RecEngine fires. (Correct = one campus ask, per Spec 020 A.4 — not direct RecEngine.) | PARTIAL |
| **A3** | `awaiting_university` | `Marmara Göztepe` (no "üniversitesi", no gender) | N-gram resolves Marmara + campus Göztepe from same message → advance to `awaiting_gender` (send gender ask). Proves n-gram multi-word match + campus-from-message without the word "üniversitesi". | PASSED |
| **A4** | `awaiting_university` | 4 different questions back-to-back: `fiyat ne` → `sadece İstanbul mu` → `konum neresi` → `ödeme nasıl` | Each → appropriate canned + re-anchor. **No escalate** across all 4. State stays `awaiting_university`. `divergence_repeat_count` never exceeds 1 (each intent differs). | FAILED |
| **A5** | `awaiting_university` | a specific hotel name (use a real `hotels.name`, e.g. `Keten Suites`) | **Hotel path fires immediately** mid-flow: that hotel's `response_schemas` served, state → `completed`. Proves Step 0 hotel interrupt works outside `new`/`completed`. | FAILED |
| **A6** | opener `fiyat ne` → bot sends `div_price_new`, state `awaiting_university` | `Boğaziçi kız` | Two-slot extraction after a divergence answer: uni→Boğaziçi, gender→female → advance/RecEngine (Boğaziçi single-campus → RecEngine; if multi, one campus ask). Proves partition works in the post-divergence state too. | PASSED | 

A2 EXPLANATION: "İTÜ kız" succeeded. "İTÜ, kız" failed and asked for campus clarification. At campus clarification,
"Ayazağa" failed; "Maslak" succeeded. 

A4 EXPLANATION: At "awaiting_university" state the question "fiyat ne" was still treated as a campus response and 
the bot asked for university name clarification. 

A5 EXPLANATION: The hotel name was treated as a university name submission and university clarification was triggered.

**If A1 or A3 fail:** the n-gram swap (A.3.2) or campus-from-same-message (A.3.3) isn't wired — check `scan_entities_by_ngram` is the resolver, not whole-string `match_university`.

---

## PART B — Escalate-label correctness (critical — black-hole handoffs)

Every escalate cause must write the `human_needed` **label**, not just the state. This is the D7.3 failure.

| ID | Setup | Send | Pass condition | Result |
|----|-------|------|----------------|--------|
| **B1** | opener | `Привет! Можно узнать подробнее?` (Russian) | `non_turkish` → silent escalate **WITH `human_needed` label in Chatwoot** + DB `flow_state=human_needed` + no outbound. (This is the exact D7.3 re-test — label is the thing that failed.) | PASSED |
| **B2** | `awaiting_university` | `sözleşme şartlarınız neler` | `complex` → silent escalate **with label**. | PASSED |
| **B3** | `awaiting_university` | 3× same intent: `fiyat ne` → `fiyat söyle` → `ya fiyat` | 3rd strike → silent escalate **with label** (verify label, not just state + `divergence_repeat_count=3`). | FAILED |

**Verify for each:** the `human_needed` label is visibly present in the Chatwoot UI. State-only-no-label = FAIL even if state is correct.

B3 EXPLANATION: "Fiyat ne" is treated as university submission and clarification is triggered. Second "fiyat söyle" 
message is treated as clarification attempt which fails and silent escalation is triggered. In awaiting_university
and awaiting_university_clarification I don't think the script can currently look for anything other than a university answer submission. Need to fix it. 

---

## PART C — DB copy fixes (fast — trigger one message, read the outbound string)

No full flow needed. Trigger each canned and confirm the NEW wording. These are seconds each.

| ID | Trigger | Pass condition (outbound text) | Result |
|----|---------|--------------------------------|--------|
| **C1** | `awaiting_university` → send `konum neresi` | `div_location_await_uni` = the district-neutral text ("İstanbul'un pek çok yerinde şubemiz bulunuyor…"). Must NOT name or promise specific districts. | FAILED |
| **C2** | Get to `awaiting_gender` (uni set) → send `fiyat ne` | `div_price_await_gender` = new neutral phrasing ("kız ve erkek öğrencilerimiz için ayrı şubelerimiz…"). Must NOT contain "farklılıkları" / difference framing. | PASSED |
| **C3** | opener `merhaba` → answer `hangi` with a single-campus Istanbul uni → observe the gender ask | Base `kiz-erkek` = "Efendim öğrencimizin kız mı erkek mi olduğunu öğrenebilir miyim?…" (student-centered, not "hangi cinsiyet"). | PASSED |
| **C4** | (feedback-loop check) After C3, confirm the bot's own gender-ask message did NOT get re-ingested and self-matched as a gender answer | Bot waits for the lead; no self-triggered advance. Confirms C.4 guard holds after the copy change. | PASSED |

C1 EXPLANATION: Treated the question as university answer submission and triggered university clarification. 

C2 INSIGHT: This is surprising. I expected this to fail since awaiting_university state treated everything as 
answer submission attempt, so I figured awaiting_gender would do the same. This points to the fact that something
specific in the awaiting_university behaviour is the block rather than our general state structure. Will look into.

C4 INSIGHT: The gender field is null and flow state is gender_awaiting, as I understand that was the success condition. 

---

## PART D — Classifier prompt hardening (fast — run as openers, single message each)

Messy/blunt/typo'd real-corpus phrasings. Each is a standalone opener; just confirm the classified intent (from `chatbot_logs`) and that an answer_and_reanchor fires (not escalate/ignore).

| ID | Send (opener) | Expected intent | Result |
|----|---------------|-----------------|--------|
| **D1** | `ücretnedir ?` | `price` | PASSED |
| **D2** | `fiyat bilgisi alabiir miyim` | `price` | PARTIAL |
| **D3** | `fiyat söyle` (blunt) | `price` | PASSED |
| **D4** | `Boşmu?` | `vacancy` | PASSED |
| **D5** | `Bos mudur` | `vacancy` | PASSED |
| **D6** | `O ne tarafta oluyor` | `location` | PASSED |
| **D7** | `Daha yakin şubeleriniz var mi` | `location` | PARTIAL |

**Pass:** ≥6/7 classify correctly and fire the matching canned. Any that mis-route to `no_intent`/`complex` → add to the prompt's few-shot and re-run just that one.

D2 EXPLANATION: After the opener it returned 'hangi'. Technically wrong but not terrible from business standpoint. 
This might be becuse D2's message is way more words than D1 or D3. 

D7 EXPLANATION: Sent 'hangi' after the opening, don't know why it happened; might be because of word count. 

---

## PART E — Inbound debounce (burst vs spaced)

Requires `DEBOUNCE_WINDOW_SECONDS=3`. Timing-sensitive — send deliberately.

| ID | Action | Pass condition | Result |
|----|--------|----------------|--------|
| **E1** | In `awaiting_university`, send 3 messages within ~1s of each other: `fiyat ne` · `İTÜ` · `kız` | Coalesced into ONE turn = "fiyat ne\nİTÜ\nkız". Partition: gender→female, uni→İTÜ(parent). **One** bot response (campus ask, gender retained) — NOT three separate replies. | FAILED |
| **E2** | Send 3 messages with >3s gap between each: `fiyat ne` … wait 4s … `konum neresi` … wait 4s … `ödeme nasıl` | Three SEPARATE turns → three distinct canned answers. Debounce must not over-merge spaced messages. | PASSED |
| **E3** | Start a burst (`fiyat ne` · `İTÜ`), then before 3s elapses have a human agent send an outbound reply | Buffer flushed/cancelled; conversation → `stopped`; buffered lead text NOT processed after human takeover. | PASSED |

**If E1 produces 3 replies:** debounce isn't buffering — check the timer resets on each inbound within the window. **If E2 merges:** window too long or timer not firing per-gap.

E1 EXPLANATION: The pass condition in the document isn't super clear but even if this result is technically correct
it's unacceptable business logic. After 'fiyat ne', 'İTÜ', 'kız' the chatbot returned 'multiple campus university, ask specific campus' response
and then 'university name clarification' message. 

---

## Done-gate for this suite

- [ ] A1–A6 pass (spine). A1 + A4 are the load-bearing ones — the original D4.1/D6.1 failures.
- [ ] B1–B3 each show the `human_needed` **label** in Chatwoot.
- [ ] C1–C4 show new copy; C4 confirms no self-ingestion.
- [ ] D ≥6/7 correct.
- [ ] E1 coalesces, E2 stays separate, E3 flushes on takeover.
- [ ] `pytest` green (unit tests for A/B/E from Spec 020 §Files).

No need to re-run full F/O/Suite-D. If A-spine changes touched shared matching code, spot-check ONE happy-path flow (merhaba → uni → gender → rec) to confirm no regression — that single smoke is enough.
