# Spec 020 — Divergence Recovery: Post-Suite-D Fixes

**Status:** Build-ready. Hand to Claude Code (Cursor). Amends Spec 019 + Migration 018.
**Origin:** Suite D live test results. Five workstreams, in strict priority order. Part A is the spine — B–E depend on nothing but should land in the same release.

**Priority order (do not reorder):**
1. **Part A** — Uniform pre-RecEngine extraction pipeline (fixes D4.1, D4.2, D6.1; hardens D5.3; folds in hotel-name interrupt). The spine.
2. **Part B** — Escalate-label correctness bug (fixes D7.3, D1.7 black-hole handoffs).
3. **Part C** — DB copy fixes (D2.2/D2.5 district-neutral, D3.x gender phrasing, base flow gender ask).
4. **Part D** — Classifier prompt hardening (typos, blunt/rude phrasing).
5. **Part E** — Inbound message debounce (burst = one turn). Separate ingestion-path change; may be its own PR but is required to close the multi-message behavior.

---

## Root-cause summary

Suite D proved the happy paths and divergence routing work, but three "failures" (D4.1, D4.2, D6.1) are **one** defect: each pre-RecEngine state has a single matcher bound to it with no extraction/partition and no divergence fallback. `awaiting_university` runs `match_university` on the **whole message** and, on failure, clarifies or escalates — it never extracts gender, never tries n-gram matching, never falls through to divergence. Fixing that one structural gap resolves all three. Everything else (B–E) is correctness or copy.

---

# PART A — Uniform pre-RecEngine extraction pipeline (THE SPINE)

## A.1 Principle

Every state before RecEngine (`new`, `awaiting_university`, `awaiting_gender`, `awaiting_university_clarification`, `awaiting_campus_clarification`) runs the **same** processing block. The state does not decide *which matchers run* — it only decides *which slot is pending* (i.e. where to advance and what to re-anchor to). All matchers run in every pre-RecEngine state. Divergence is a **fallback inside** this block, not a replacement for it.

## A.2 The block (exact order)

For an inbound message in any pre-RecEngine state:

```
STEP 0 — Hotel-name interrupt (deterministic)
  hotel = match_hotel_by_ngram(content, all_visible_hotels)
  if hotel:
      fire_hotel_path(hotel)         # serve hotel response_schemas; state -> completed
      return

STEP 1 — Gender extraction (independent boundary pass; only if gender not already set)
  if conversation.gender is None:
      g = extract_gender(content)    # existing GENDER_FEMALE / GENDER_MALE \b regexes
      if g:
          set_conversation_gender(conversation, g)   # write gender + set_by/set_at
          gender_filled = True

STEP 2 — Primary-entity extraction (context-scoped)
  if state == 'awaiting_campus_clarification' AND pending_parent_university_id is set:
      campus = match_campus(content, pending_parent_university_id)   # scoped campus match
      if campus:
          resolve_campus(conversation, campus)        # sets university_id, clears pending
          entity_filled = True
  else:
      uni = scan_entities_by_ngram(content, all_unis, all_aliases)   # N-GRAM, not whole-string
      if uni.confidence == AMBIGUOUS:
          -> awaiting_university_clarification (send clarify_uni); return
      elif uni.parent_university_id is set:
          campus = match_campus(content, uni.parent_university_id)   # campus from SAME message
          if campus:
              resolve_campus(conversation, campus); entity_filled = True
          else:
              set pending_parent; send campus question; state -> awaiting_campus_clarification; return
      elif uni.university_id is set:
          set_conversation_university(conversation, uni.university_id); entity_filled = True
      else:
          ooc = match_out_of_city(content)
          if ooc:
              fire_out_of_city(); state -> completed; return

STEP 3 — Advance if anything was filled this turn
  if gender_filled or entity_filled:
      reset divergence counter (last_divergence_intent=NULL, divergence_repeat_count=0)
      advance_to_earliest_empty_slot(conversation)
        # both slots present -> fire RecEngine
        # university set, gender missing -> awaiting_gender (send gender ask)
        # gender set, university missing -> awaiting_university (send hangi)
      return

STEP 4 — Nothing resolved -> divergence fallback
  intent = divergence_classifier.classify(content)     # state-blind LLM
  decision = divergence_router.route(intent, state)
  execute_divergence(decision, conversation)           # per Spec 019 §5, incl. persistence counter
```

## A.3 Key changes from current code

1. **Gender extraction runs in `awaiting_university` and the clarification states**, not just early-capture in `_handle_new`. This is what lets "İTÜ, kız" and "Marmara Göztepe, erkek öğrenci" partition. Gender and university are **independent passes over the same text** — do NOT strip tokens between them (gender words never match a university n-gram, so stripping is unnecessary and risks corrupting names).

2. **University resolution uses `scan_entities_by_ngram`, never whole-string `match_university`.** This is the fix for "Marmara Üniversitesi Göztepe" failing. The n-gram scan already runs `match_university` per 1–4-word window (longest first), so the existing tier ladder (exact → short_name → alias → Levenshtein) applies to each window and "marmara" resolves inside the longer string. `match_university` on the whole string stays available only for already-clean single-token inputs; the pre-RecEngine path calls the n-gram scanner.

3. **Campus resolution from the same message.** When a parent university matches, scan the same content for a campus of that parent *before* asking the campus question. If present, resolve directly and skip the clarification turn. Only ask when the campus isn't already in the message. (This is the "skip stages whose info is already present" rule extended to campus.)

4. **Hotel-name interrupt fires in all pre-RecEngine states**, not just `new`/`completed`. Uses the existing `match_hotel_by_ngram` + `_fire_hotel_path`. Deterministic — NOT routed through the LLM. A lead naming a specific hotel mid-flow gets that hotel's schema immediately. No new intent, no new routing row.

5. **Divergence is Step 4 of the block, reached only when Steps 0–3 resolve nothing.** It does not replace the flow; it catches what the deterministic passes miss.

## A.4 Expected behavior after A (test deltas)

- **D4.1** `Marmara Üniversitesi Göztepe, erkek öğrenci` in `awaiting_university`: gender→male (Step 1), n-gram→Marmara (Step 2), campus "Göztepe" resolved from same message → both slots + campus set → **RecEngine fires**. PASS.
- **D4.2** `İTÜ, kız` in `awaiting_university`: gender→female (Step 1), n-gram→İTÜ parent (Step 2). İTÜ is multi-campus and "kız" is not a campus → **one campus-clarification question**, gender retained. After campus reply → RecEngine. NOTE: correct behavior is a single campus ask, not direct RecEngine, because İTÜ genuinely needs disambiguation; the fix is that it no longer silently escalates and gender is preserved. Adjust the D4.2 expected result to "asks campus once, then RecEngine."
- **D6.1** second different question in `awaiting_university`: Steps 0–3 resolve nothing (it's not a uni/gender/hotel) → Step 4 divergence → classified, answered, re-anchored. Loop continues per intent. PASS.

## A.5 Ambiguity guard (n-gram over-matching)

N-gram scanning is more permissive than whole-string. Two guards:
- **Longest-match-first** (already in `scan_entities_by_ngram`) — prefer the longest window that matches, so "marmara universitesi" wins over a stray 1-gram.
- **Negation/contrast risk** ("boğaziçi değil marmara") is acceptable to mis-handle in V1 (rare); log the resolved match so it's observable. Do not add contrast parsing now.

---

# PART B — Escalate-label correctness bug (D7.3, D1.7)

## B.1 Symptom

D7.3 (`non_turkish` → escalate) set no `human_needed` label and sent no message — a silent black hole invisible to both lead and agent. D1.7 likely the same. The divergence-escalate path is not writing the label that `_escalate_human_needed` writes on the deterministic path.

## B.2 Requirement

**Every** escalation path must produce the full silent-escalate triple: `flow_state=human_needed` + `human_needed` Chatwoot label + fatal/info log, and **no** outbound message. This includes all divergence escalation causes:
- router action `escalate`,
- missing routing row (default escalate),
- persistence 3rd-strike escalate,
- `complex` / `non_turkish` classification.

## B.3 Fix

Route all divergence escalations through the same `_escalate_human_needed()` used by the deterministic path (with `internal_class="divergence_unhandled"` or a cause-specific class), rather than any local state-only write. Audit for any code that sets `flow_state=human_needed` directly without the label write and replace it with the canonical helper. Add a unit test asserting that each divergence-escalate cause writes the label (mock Chatwoot; assert `set_labels` called with `human_needed`).

## B.4 Verification

Re-run D7.3 and D1.7: confirm `human_needed` label appears in Chatwoot and DB `flow_state=human_needed`, still no outbound message.

---

# PART C — DB copy fixes

All are `UPDATE canned_responses` by `short_code`. No schema change. Apply as a small follow-up migration (018b or inline). **Çınar to review/adjust Turkish before applying — these are drafts in his voice, but the brand tone is his call.**

## C.1 District-neutral location re-anchor (D2.2 / D2.5)

The location messages must not promise or deny specific districts (geography is RecEngine's job via deal_awaiting). Neutralize:

```sql
UPDATE canned_responses SET content =
 'İstanbul''un pek çok yerinde şubemiz bulunuyor efendim. Üniversitenizi ve kız mı erkek öğrenci için mi baktığınızı söylerseniz size en uygun şubeyi iletebilirim.'
 WHERE short_code = 'div_location_new';

UPDATE canned_responses SET content =
 'İstanbul''un pek çok yerinde şubemiz bulunuyor efendim. Hangi üniversitede okuduğunuzu söylerseniz size en uygun şubeyi iletebilirim.'
 WHERE short_code = 'div_location_await_uni';

UPDATE canned_responses SET content =
 'İstanbul genelinde birçok şubemiz var efendim. Kız mı erkek öğrenci için mi baktığınızı söylerseniz size en uygun konumu iletebilirim.'
 WHERE short_code = 'div_location_await_gender';
```
Also update `div_location_new_alt`, `div_location_await_uni_alt`, `div_location_await_gender_alt` in the same neutral spirit (no district claims).

## C.2 Gender-ask phrasing — remove the "difference between genders" framing (D3.x)

The `*_await_gender` divergence messages currently emphasize *differences between* kız/erkek branches, which reads as discriminatory. Reframe as "we have separate branches for male and female students, which are you looking for" — standard, neutral, expected in TR student housing:

```sql
UPDATE canned_responses SET content =
 'Efendim kız ve erkek öğrencilerimiz için ayrı şubelerimiz bulunuyor. Hangisi için baktığınızı söylerseniz size uygun fiyatı iletebilirim.'
 WHERE short_code = 'div_price_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimize ayrı şubelerimizde hizmet veriyoruz efendim. Hangisi için baktığınızı söylerseniz doluluk durumunu iletebilirim.'
 WHERE short_code = 'div_vacancy_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimiz var efendim. Hangisi için baktığınızı söylerseniz ödeme detaylarını iletebilirim.'
 WHERE short_code = 'div_payment_await_gender';
```
Apply the same reframe to every `*_await_gender` and `*_await_gender_alt` short_code (coverage, eligibility, housing, parent, location included).

## C.3 Base-flow gender ask (`kiz-erkek` / `CANNED_KIZ_ERKEK`)

The main funnel's gender question also needs the warmer, student-centered phrasing (Çınar's note: "öğrencimizin kız mı erkek mi olduğunu"). This is NOT a divergence canned — it's the core flow, so fix it here too or the funnel stays weird:

```sql
UPDATE canned_responses SET content =
 'Efendim öğrencimizin kız mı erkek mi olduğunu öğrenebilir miyim? Ona göre size en uygun şubemizi önerebilirim.'
 WHERE short_code = 'kiz-erkek';
```

## C.4 Post-copy check

After copy changes, a second phrase-gate pass may be warranted (Çınar's note): the new gender wording "öğrencimizin kız mı erkek mi" contains "kız"/"erkek" which the gender extractor (Part A Step 1) reads — ensure the bot's OWN outbound messages are never fed back through extraction (existing feedback-loop guard / bot-agent check must cover this; verify it does after copy change).

---

# PART D — Classifier prompt hardening

Amend `system_prompts/divergence_classifier_prompt.md`. Real traffic is fast, blunt, misspelled, and often rude — the current few-shot set is too clean and polite.

## D.1 Add a robustness instruction block (after the Decision rules)

> **Real messages are messy.** Leads type quickly on phones: missing spaces ("ücretnedir"), doubled/dropped letters ("alabiir miyim", "Boşmu"), missing question marks, all-lowercase, no diacritics ("fiyat ne kadar" written "fiyat ne kadr"), and blunt or rude tone ("fiyat söyle", "ne kadar bu", "yer var mı yok mu"). Classify by the underlying intent regardless of spelling, punctuation, casing, or politeness. A rude price question is still `price`. A misspelled vacancy question is still `vacancy`. Do not downgrade a real question to `no_intent` because it is terse or impolite — `no_intent` is only for genuine junk, pure acknowledgments, and content-free abuse.

## D.2 Add real messy examples to the few-shot set (verbatim from corpus)

```
Input: `ücretnedir ?`
Output: {"intent": "price"}

Input: `fiyat bilgisi alabiir miyim`
Output: {"intent": "price"}

Input: `Fiyatları nedir`
Output: {"intent": "price"}

Input: `fiyat söyle`
Output: {"intent": "price"}

Input: `Boşmu?`
Output: {"intent": "vacancy"}

Input: `Bos mudur`
Output: {"intent": "vacancy"}

Input: `O ne tarafta oluyor`
Output: {"intent": "location"}

Input: `Ve semt olarak nerdesiniz`
Output: {"intent": "location"}

Input: `Daha yakin şubeleriniz var mi`
Output: {"intent": "location"}

Input: `Metrobüse yakın olsa güzel olur`
Output: {"intent": "location"}
```

## D.3 Note on scope

Do NOT add spelling correction to the deterministic matchers via this prompt — the classifier only labels intent. University/gender typo tolerance is the n-gram + Levenshtein matcher's job (Part A), not the LLM's.

---

# PART E — Inbound message debounce (burst = one turn)

## E.1 Problem

Leads send thought-fragments as separate WhatsApp messages ("fiyat ne" / "İTÜ" / "kız" in three rapid sends). Processing each independently produces three separate bot replies and defeats the Part A partition logic (which wants "fiyat ne, İTÜ, kız" as one turn). The distinction between "should merge" and "should answer separately" is **temporal, not semantic**: a rapid burst is one turn; spaced messages are separate turns.

## E.2 Design

Debounce at the webhook ingestion layer (`app/webhooks/chatwoot.py`), before `info_gatherer.process_message`:

- On inbound non-private `message_created`, store the message and (re)start a per-conversation debounce timer of `DEBOUNCE_WINDOW_SECONDS` (default **3s**, env-configurable).
- If another inbound arrives for the same conversation before the timer fires, append it to the buffer and reset the timer.
- When the timer expires with no new message, concatenate the buffered messages **in arrival order, newline-joined**, and invoke `process_message` **once** with the combined content.
- Messages are still individually persisted to `messages` (dedupe unchanged) for audit; only the *processing* is coalesced.

## E.3 Constraints & edge cases

- **Persistent-process only.** Debounce timers are `asyncio` tasks in the Railway process (same model as existing background loops). Document that this breaks under multi-replica; single web dyno assumed (already true).
- **Human-takeover race:** if an outbound human message arrives during the debounce window, flush/cancel the buffer and set `stopped` per existing logic — do not process buffered lead text after a human took over.
- **Hotel-path / terminal:** if the buffered content triggers Step 0 hotel path, that's fine (one combined turn). Terminal states still short-circuit.
- **Optimistic locking:** the combined turn goes through the existing `update_conversation_state(expected_from_state)` path unchanged — coalescing reduces, not increases, race surface.
- **Reprompt sweep:** `last_message_at` advances on each buffered message as today; only processing waits. The 3s window is far below the reprompt cadence, no interaction.

## E.4 Config

Add `DEBOUNCE_WINDOW_SECONDS` (default 3) to `app/config.py` and `.env.example`. A value of 0 disables debounce (processes immediately) for testing.

---

## Files to touch

| File | Part | Change |
|---|---|---|
| `app/layers/info_gatherer.py` | A, B | Replace per-state handlers with the uniform block (A.2); route all escalations through `_escalate_human_needed` (B). |
| `app/layers/matching.py` | A | Ensure pre-RecEngine university resolution calls `scan_entities_by_ngram`; add/verify `match_campus(content, parent_id)` scoped campus matcher usable outside the campus-clarification handler. |
| `app/webhooks/chatwoot.py` | E | Debounce buffer + timer before `process_message`. |
| `app/config.py`, `.env.example` | E | `DEBOUNCE_WINDOW_SECONDS`. |
| `system_prompts/divergence_classifier_prompt.md` | D | Robustness block + messy few-shot. |
| `migrations/018b_divergence_copy_fixes.sql` (or inline) | C | The `UPDATE canned_responses` statements. |
| `tests/test_slot_skip.py` | A | Extend: extract-both in `awaiting_university`, campus-from-same-message, hotel interrupt mid-flow, "İTÜ, kız" → campus ask with gender retained. |
| `tests/test_divergence_persistence.py` | A | Counter resets on entity_filled via the new block. |
| `tests/test_escalation_label.py` (new) | B | Every divergence-escalate cause writes `human_needed` label. |
| `tests/test_debounce.py` (new) | E | Burst coalescing; spaced messages stay separate; human-takeover flush. |

## Acceptance criteria

1. D4.1 fires RecEngine from a single two-slot message (no clarify, no escalate).
2. D4.2 asks campus once (gender retained), then RecEngine — no silent escalate.
3. D6.1 answers ≥5 different questions in `awaiting_university` with no escalate; state stable.
4. D5.3 still passes via the new block (entity fill resets counter and advances).
5. Every divergence-escalate cause (router escalate, missing row, 3rd strike, complex, non_turkish) writes the `human_needed` label — verified live (re-run D7.3) and in unit test.
6. Location re-anchors make no district claims; gender asks use neutral separate-branch phrasing; base `kiz-erkek` uses student-centered phrasing.
7. Classifier labels the D.2 messy corpus messages correctly (add to offline eval fixture).
8. Burst of 3 rapid messages → one bot turn; 3 spaced messages → three turns; human takeover mid-burst flushes safely.
9. Full `pytest` green; existing F/O suites unchanged; Suite D re-run passes with the D4.2 expectation amended.

## Explicitly out of scope (deferred, per decision)

- Parent not-yet-enrolled branch (send GK Residence sample) — separate mini-spec later.
- Escalation analytics UI / settings panel — CRM-panel task; data already logged to `chatbot_logs`.
- Contrast/negation parsing ("X değil Y").
- English-language serving (non_turkish still → escalate).
