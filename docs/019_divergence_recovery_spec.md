# Spec 019 — InfoGatherer Divergence Recovery (LLM Intent Classifier)

**Status:** Build-ready. Hand to Claude Code (Cursor).
**Depends on:** Migration 018 (this feature's schema). Related prerequisite fixes (§9) may ship independently but are required for correct behavior.
**Governing principle:** The LLM classifies intent and nothing else. All policy lives in a code-owned routing table. All customer-facing text is pre-written canned content. State never enters the LLM; message text never enters the routing code; the LLM never parses slots.

---

## 1. Purpose

Today, when a lead sends a message InfoGatherer's deterministic layer can't place — a price question, a district question, a parent shopping for their kid — the bot goes silent and escalates (`off_script_no_answer`) or ignores it (`IGNORE`). Corpus analysis of 987 real conversations showed ~1 in 4 winnable conversations hits this silent wall, and the majority are high-intent leads a human handled trivially.

This feature fills that gap. When deterministic matching fails, a narrow LLM classifies the message into a fixed intent enum. A routing table maps `(intent × flow_state)` to an action: answer the digression with a canned response and re-anchor to the pending slot, activate the flow, ignore, or escalate. Everything the deterministic layer already handles is untouched — the LLM never fires on the happy path.

---

## 2. Trigger boundary — when the classifier fires (and never fires)

The classifier is a **fallback**, invoked at exactly the points where InfoGatherer would otherwise go silent. It is the implementation of the FallBack V2 seam.

**Fires only when, after deterministic processing, the message would result in:**
- Phrase gate `IGNORE` in `new` (`first_inbound_but_no_filter_matched`), OR
- `_escalate_human_needed(..., internal_class="off_script_no_answer")` in `awaiting_university`, `awaiting_gender`, `awaiting_university_clarification`, or `awaiting_campus_clarification`.

**Never fires when:**
- Any deterministic matcher succeeds (university, gender, hotel n-gram, out-of-city, phrase-gate filter, campus match). These proceed exactly as today.
- State is `recengine_running`, `completed`, `human_needed`, or `stopped` (unchanged — ignore/terminal/deferred).
- `conversations.bot_enabled = false` (outbound-first conversations; see §9.3).

**Ordering inside a firing state (critical):** deterministic slot extraction runs FIRST (§7). The classifier is reached only if extraction filled no slot. This guarantees the LLM never sees a message that contained a resolvable university or gender.

**Failure = current behavior.** If the LLM errors, times out, returns invalid JSON, or returns a label not in the enum, the system falls back to today's behavior for that state (silent `IGNORE` in `new`; `_escalate_human_needed` mid-flow). The feature can only improve on the drop; it never sits in the path of a working flow. One retry, then fall back.

---

## 3. Architecture — four layers

```
inbound message
  │
  ▼
InfoGatherer deterministic matching  ── matched ──► normal scripted flow   [LLM never called]
  │ (no match; would go IGNORE / off_script_no_answer)
  ▼
[Layer 0] deterministic slot extraction (§7)  ── any slot filled ──► advance / RecEngine  [LLM never called]
  │ (no slot filled)
  ▼
[Layer 1] Classifier  divergence_classifier.classify(message) ─► intent enum        [state-blind, LLM]
  │
  ▼
[Layer 2] Router  divergence_router.route(intent, flow_state) ─► RoutingDecision       [pure code]
  │        (missing (intent,state) row → escalate)
  ▼
[Layer 3] Executor (in info_gatherer) performs the action, pulling canned text by FK   [code + DB]
      action = activate_flow       → start/continue funnel to earliest empty slot
      action = answer_and_reanchor → send canned (primary|alt by repeat counter), re-anchor to pending slot
      action = ignore              → no message, state unchanged
      action = escalate            → _escalate_human_needed(internal_class="divergence_unhandled")
```

**Division of responsibility (do not blur):**
- **Classifier (LLM):** message → one intent string. Knows nothing about state, actions, or canned content.
- **Router (code):** `(intent, flow_state)` → action + which canned FKs. Holds 100% of policy. Unit-testable without the LLM.
- **Canned (DB):** the actual Turkish messages. Adding a new answerable case = add canned rows + a routing row. No logic change.
- **Executor (code):** drives the real state machine, manages the persistence counter, picks primary vs alternate phrasing.

---

## 4. The intent enum (frozen contract)

The classifier MUST emit exactly one of these strings. This list is the shared vocabulary between the prompt (Doc 4) and the routing table (Doc 2). Adding/removing a value requires touching both.

| intent | Meaning | Answerable? |
|---|---|---|
| `housing` | Generic accommodation intent, no specific question ("yurt arıyorum") | Re-anchor only |
| `price` | Cost / fee / rate questions | Yes (flow) |
| `location` | District / proximity / "where" questions | Yes (flow) |
| `vacancy` | Availability / free-space questions | Yes (flow) |
| `parent_shopping` | Third party (parent/relative) seeking for a student | Re-anchor only |
| `logistics_coverage` | Geographic coverage ("only Istanbul?") | Yes (canned) |
| `logistics_payment` | Payment cadence / terms | Yes (canned) |
| `logistics_eligibility` | Who may stay (student requirement, outsiders, family visits) | Yes (canned) |
| `no_intent` | Junk, noise, abuse, bare acknowledgments ("peki", "teşekkürler", spam) | No — ignore |
| `complex` | Answerable only by a human, novel/off-catalog questions (visit scheduling, contracts), OR low confidence | No — escalate |
| `non_turkish` | Message not written in Turkish | No — escalate (EN support deferred to a later version) |

**Low-confidence rule:** when the classifier is unsure between an activating intent and `no_intent`/`complex`, it MUST emit `complex`. Unsure never activates the flow. (Asymmetric cost: wrongly escalating a real lead costs one human-handled chat; wrongly activating on abuse sends "hangi üniversite?" to a spammer.)

---

## 5. Actions

| action | Behavior | Canned FKs required |
|---|---|---|
| `activate_flow` | Begin/continue the normal funnel toward the earliest empty slot (send the standard slot question). No digression answer. | none (null) |
| `answer_and_reanchor` | Send the canned message (which both addresses the intent and re-asks the pending slot), then remain in / move to the pending-slot state. | both `canned_response_id` and `canned_response_alt_id` |
| `ignore` | No outbound message, state unchanged. (Matches today's silent `IGNORE`.) | none (null) |
| `escalate` | `_escalate_human_needed`. | none (null) |

---

## 6. Routing table semantics

Table: `divergence_routing` (schema in Doc 2). One row per `(intent, flow_state)`, unique.

- **Lookup:** `route(intent, flow_state)` selects the row. 
- **Missing row → `escalate`.** This is the safe default and is handled in code — do NOT seed escalate rows. `complex` and `non_turkish` therefore need no rows.
- **`no_intent` needs explicit `ignore` rows** for each firing state, because the missing-row default is escalate and junk must not escalate.
- **CHECK constraint:** `answer_and_reanchor` rows must have both canned FKs non-null; all other actions must have both null. A half-populated row cannot ship.
- **Re-anchor targets the pending slot, never the flow top.** The pending slot is a function of `flow_state`: `awaiting_university` → university, `awaiting_gender` → gender, `awaiting_university_clarification` → university (full name), `awaiting_campus_clarification` → campus. In `new`, re-anchor asks for university (+ opportunistic gender). Re-anchoring must not discard already-resolved slots (e.g. a campus-clarification digression re-asks the campus, preserving the resolved parent university).

Firing states (the only `flow_state` values the router will ever be called with): `new`, `awaiting_university`, `awaiting_gender`, `awaiting_university_clarification`, `awaiting_campus_clarification`.

---

## 7. Deterministic slot extraction & state-skip (NOT LLM)

This runs before the classifier and is a general InfoGatherer capability, not classifier-specific.

**Rule:** After any inbound message in a firing state, attempt to extract **every** slot present, using the existing deterministic matchers only:
- University: `match_university()` → `match_out_of_city()` (unchanged logic, incl. parent-alias/campus).
- Gender: existing `GENDER_FEMALE` / `GENDER_MALE` regexes.

Then:
1. Set whichever slots resolved (`university_id`, `gender`), writing `*_set_by`/`*_set_at` companions.
2. **Advance to the earliest still-empty slot**, or fire RecEngine if none remain empty.
3. Only if **no** slot resolved from this message does control fall through to the classifier.

This single rule yields, with no special-casing:
- **Skip-both:** "marmara üniversitesi Göztepe, erkek öğrenci" → both slots fill → straight to RecEngine.
- **Skip-one:** university given while gender still empty → advance to `awaiting_gender`.
- **Normal:** one slot at a time.

The classifier and re-anchor path feed back into this same "what's still empty?" check. The LLM is never involved in parsing "marmara Göztepe, erkek" into slots — that is `match_university` + gender regex.

---

## 8. Loop behavior

Two independent mechanisms. Implementers must not conflate them.

### 8.1 Different-question loop — UNCAPPED
As long as the bot can answer, it answers and re-anchors, indefinitely. A lead who asks price, then rooms, then rules, then location gets four answers and four re-anchors. There is **no** cap on the number of *different* answered questions. The only exit is an unanswerable message → `escalate`. The bot's job is to provide information; answering many questions is success, not failure.

### 8.2 Same-question persistence — CAP AT 2 PHRASINGS
When the lead repeats the **same intent with no slot progress** on consecutive divergence turns:
- Repeat 1 → send `canned_response_id` (primary phrasing).
- Repeat 2 → send `canned_response_alt_id` (alternate phrasing, same meaning).
- Repeat 3 → `escalate` (ignore both FKs).

**Detection:** persistence = the classifier returns the **same** intent on consecutive turns AND no slot was filled in between. It is NOT "turns without a slot" (that would be a funnel-goal cap, which we explicitly rejected).

**Reset:** the counter resets to zero on ANY of: a different intent, any slot progress (university or gender resolved), or a successful advance. A lead cycling through *different* questions never trips this; only the *same* question hammered ≥3× does.

**State:** stored on `conversations` as `last_divergence_intent` (text) + `divergence_repeat_count` (int). On each divergence turn: if `intent == last_divergence_intent` → increment; else → set `last_divergence_intent = intent`, `divergence_repeat_count = 1`. On any slot progress or advance → reset both (`last_divergence_intent = NULL`, `divergence_repeat_count = 0`).

---

## 9. Prerequisite / adjacent fixes (in scope for this build)

### 9.1 Off-script marker false positives — token-boundary fix (HIGH priority)
`answer_classifier._offscript_markers` currently does `fold(phrase) in folded` (substring) for all markers. Short markers collide with legitimate Turkish place/campus answers: `Cihangir` contains `hangi`, `Kağıthane`/`Güneşli` contain `ne`. These are valid answers to the university question, silently escalated today.

**Fix:** apply word-boundary matching (`(?<!\w)…(?!\w)` on folded text, the same pattern `_contains_keyword` uses for boundary greetings) to the short/whole-word markers: all `_QUESTION_CLITICS`, and the `_QUESTION_WORDS` entries `ne`, `nerede`, `nerde`, `neden`, `niye`, `nicin`, `kac`, `kim`, `hangi`, `nasil`. Keep substring matching only for unambiguous long phrases (`istiyorum`, `ariyorum`, `bakiyorum`, `alabilir`, `mumkun mu`, the third-person referents). This must land before the classifier is wired, or false-positive escalations will pollute the divergence path.

### 9.2 Greeting variants leak
`sa`, `slm`, `salam`, `heyy` miss `_GREETING_WORDS`. Add as **boundary-matched** tokens (not substrings — `sa` as a substring would match inside `sabah`, `masa`). Add to `_GREETING_WORDS` + `_BOUNDARY_GREETINGS`: `sa`, `slm`, `slm.`→ handled by boundary, `salam`, `heyy` (or make `hey` a stem allowing trailing repeats).

### 9.3 Outbound-first conversations — `bot_enabled`
10.7% of conversations are salesperson-initiated. The bot must not run in these. Set `conversations.bot_enabled = false` when the first event on a conversation is an outgoing (agent) message; detect once at conversation creation, store the flag, and gate all InfoGatherer processing on it. Do not re-derive per message.

### 9.4 Opener university detection (phrase gate)
When the opener contains a university (Filter 2 entity match today only accepts-as-greeting), resolve and route it: Istanbul university → proceed to gender ask; out-of-city university → send `istanbul` canned and complete. Add `match_out_of_city()` as a pre-`IGNORE` step in `_handle_new` so a bare out-of-city opener ("Trakya üniversitesi") reaches the out-of-city path instead of `IGNORE`. This makes bare-uni openers behave like the `awaiting_university` handler already does.

---

## 10. Files to create / touch

| File | Change |
|---|---|
| `app/layers/divergence_classifier.py` | **New.** `classify(message) -> Intent`. Builds Gemini payload from `system_prompts/divergence_classifier_prompt.md`, calls Gemini via existing client infra with `MODEL_ID`, parses `{"intent": "..."}`, validates against enum, returns `complex` on any parse/validation failure after one retry. State-blind. |
| `app/layers/divergence_router.py` | **New.** Pure function `route(intent, flow_state) -> RoutingDecision(action, canned_short_code, canned_alt_short_code)`. Reads `divergence_routing`. Missing row → `escalate`. No LLM, no I/O beyond the routing query (may be cached at boot like other reference tables). |
| `app/layers/info_gatherer.py` | Wire the executor: at each current `IGNORE`/`off_script_no_answer` site, call slot-extraction (§7), then classifier→router→execute. Manage persistence counter (§8.2). Preserve pending slot on re-anchor. Gate on `bot_enabled`. |
| `app/layers/answer_classifier.py` | Fix 9.1 (token-boundary markers). |
| `app/layers/phrase_gate.py` | Fix 9.2 (greeting variants), 9.4 (opener uni routing hook). |
| `app/db/queries.py` | Add: routing-table read, `bot_enabled` read/write, divergence-counter read/write, canned lookup by short_code (exists). |
| `app/db/models.py` | DTOs: `RoutingDecision`, routing row. |
| `system_prompts/divergence_classifier_prompt.md` | **New.** Doc 4. |
| `migrations/018_divergence_routing.sql` | **New.** Doc 2. |
| `tests/test_divergence_classifier.py` | **New.** Enum validation, fallback-on-failure, JSON parsing (mock Gemini). |
| `tests/test_divergence_router.py` | **New.** `(intent×state)→action` table, missing-row→escalate, CHECK behavior. |
| `tests/test_slot_skip.py` | **New.** Extract-both / extract-one / extract-none. |
| `tests/test_divergence_persistence.py` | **New.** Same-intent 1→primary, 2→alt, 3→escalate; reset on intent change / slot progress. |

**Constants:** keep `MODEL_ID` as the env constant (never hardcode the Gemini model). Keep the enum defined once (a Python `Enum` in `divergence_classifier.py`), imported by the router so a typo can't split the contract.

---

## 11. Non-goals (this build)

- English/other-language serving (non_turkish → escalate; EN is a later version).
- Post-`completed` re-recommendation ("show me another hotel" without naming one) — unchanged, still deferred.
- Sales-action labels, NetGSM/CRM integration.
- Full free-form conversational recovery — the LLM only classifies into the fixed enum; it never authors customer text.
- Clarification/campus-state canned coverage for every intent — the migration seeds the high-value matrix; unseeded `(intent, clar_state)` combos safely escalate until rows are added.

---

## 12. Acceptance criteria

1. Every deterministic happy-path case behaves identically to today (regression: existing 198 tests pass unchanged).
2. LLM outage / invalid output → identical to today's silent behavior for that state (verified by fault-injection test).
3. `(intent × flow_state)` with a seeded row produces its action; unseeded → escalate.
4. Slot-skip: a single message filling both slots reaches RecEngine without asking either question.
5. Persistence: identical repeated intent yields primary, then alternate, then escalate; a different intent mid-sequence resets.
6. §9.1 fix: `Cihangir`, `Kağıthane`, `Güneşli` as replies in `awaiting_university` are NOT escalated as off-script (they proceed to matching; escalation only if genuinely unmatched and off-script by boundary markers).
7. `bot_enabled=false` conversations receive no bot messages.
8. Live suite (Doc 3) passes on allowlisted phones.
