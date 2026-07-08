# Suite D — Divergence Recovery — Live WhatsApp Test Plan

**Scope:** End-to-end validation of Spec 019 on live WhatsApp with allowlisted phones, `TESTING_LIMITATIONS_MODE=true`. Complements F-suite (functional flow) and O-suite (off-script detection). Run after Migration 018 is applied and the divergence classifier/router are wired.

**Prereqs**
- Migration 018 applied; verification queries in the migration return clean.
- §9.1 (token-boundary markers) and §9.2 (greeting variants) fixes deployed.
- `MODEL_ID` set; Gemini reachable; divergence classifier live.
- Two allowlisted phones: `905551839644`, `905445545244`.

**Mandatory teardown between tests** (run before each fresh case):
```sql
UPDATE conversations
SET flow_state = NULL, university_id = NULL, gender = NULL,
    pending_parent_university_id = NULL, ilgili_otel = NULL,
    ilgili_otel_set_at = NULL, ilgili_otel_set_by = NULL,
    auto_run_count = 0, manual_run_count = 0, clarification_attempt = 0,
    last_divergence_intent = NULL, divergence_repeat_count = 0,
    bot_enabled = true
WHERE chatwoot_conversation_id = <your_test_cw_id>;
```
Also clear Chatwoot labels/attributes in the UI before each run.

**How to read expected results**
- **Bot sends X** = an outbound canned message must appear.
- **Silent escalate** = `flow_state=human_needed`, `human_needed` label, **no** outbound message.
- **Silent ignore** = no outbound, state unchanged, no label.
- After each test, confirm `chatbot_logs` shows the intended intent + action (the classifier's returned intent and the router's action should be logged for every divergence turn).

---

## Group D1 — Opener divergence (state `new`, classifier fills the IGNORE stub)

Each opener below currently returns `IGNORE` (verified against the gate). The classifier should now recover it.

| ID | Send (opener) | Expected intent | Expected action | Pass condition | Result |
|----|---------------|-----------------|-----------------|----------------|--------|
| D1.1 | `fiyatlarınız neler` | `price` | answer_and_reanchor | Bot sends `div_price_new`; state → `awaiting_university` | PASSED |
| D1.2 | `yeriniz nerede` | `location` | answer_and_reanchor | Bot sends `div_location_new`; state → `awaiting_university` | PASSED |
| D1.3 | `boş yeriniz var mı` | `vacancy` | answer_and_reanchor | Bot sends `div_vacancy_new` | PASSED |
| D1.4 | `Uygulamanız yalnızca İstanbul'da mı?` | `logistics_coverage` | answer_and_reanchor | Bot sends `div_coverage_new` | PASSED |
| D1.5 | `Ödeme aylık mı oluyor` | `logistics_payment` | answer_and_reanchor | Bot sends `div_payment_new` | PASSED |
| D1.6 | `Öğrenci olmam şart mı, ben çalışanım` | `logistics_eligibility` | answer_and_reanchor | Bot sends `div_eligibility_new` | PASSED |
| D1.7 | `140 kız 60 erkek kapasiteli oteliniz var mı? konum önemli değil` | `vacancy` | answer_and_reanchor | Bot sends a vacancy re-anchor (acceptable if classified `vacancy`) | NO RESPONSE (acceptable) |
| D1.8 | `dskjgs` | `no_intent` | ignore | No outbound, state stays `new`, no label | PASSED |
| D1.9 | `siz dolandırıcısınız` | `no_intent` | ignore | No outbound, no escalate | PASSED | 
| D1.10 | `yüz yüze görüşebilir miyiz` | `complex` | escalate (no row) | Silent escalate | PASSED |

---

## Group D2 — Mid-flow divergence in `awaiting_university`

Setup for each: send an accepted opener (`merhaba`) so the bot asks university (`hangi`), landing in `awaiting_university`. Then send the divergence message.

| ID | After `hangi`, send | Expected intent | Expected action | Pass condition | Result |
|----|---------------------|-----------------|-----------------|----------------|--------|
| D2.1 | `fiyat ne kadar` | `price` | answer_and_reanchor | Bot sends `div_price_await_uni`; stays `awaiting_university` | PASSED |
| D2.2 | `Avcılar tarafında var mı peki` | `location` | answer_and_reanchor | Bot sends `div_location_await_uni` | TECHNICAL PASS BUSINESS FAIL |
| D2.3 | `konaklama arıyorum` | `housing` | answer_and_reanchor | Bot sends `div_housing_await_uni` | PASSED | 
| D2.4 | `Oğlum 11. sınıfta, üniversite için bakıyoruz` | `parent_shopping` | answer_and_reanchor | Bot sends `div_parent_await_uni` (NOT silent escalate) | TECHNICAL PASS BUSINESS FAIL |
| D2.5 | `beykoz'a yakın şubeniz var mı anadolu yakasında` | `location` | answer_and_reanchor | Bot sends `div_location_await_uni` | TECHNICAL PASS BUSINESS FAIL |
| D2.6 | `sadece İstanbul'da mısınız` | `logistics_coverage` | answer_and_reanchor | Bot sends `div_coverage_await_uni` |

D2.2 EXPLANATION: The bot sent "Size en yakın konumu önerebilmem için hangi üniversitede okuduğunuzu öğrenebilir miyim efendim?" which seems correct.
However, there are some districts we serve and some we don't. But I don't see the point in detailing this since we coded the deal_awaiting segregation
in the RecEngine expansion and I really don't wanna write the same logic again for this layer too. So let's just change the message the bot sends to
"İstanbul'un pek çok yerinde şubemiz bulunuyor efendim, üniversitenizi ve kız mı erkek için mi baktığınızı söylerseniz en uygun şubeyi iletebilirim."

D2.4 EXPLANATION: The logic works fine but the message needs to be changed. If the student is not in university yet, don't ask this. Ask instead
"Tabii efendim o zaman genel bilgi oluşması için popüler bir şubemizi gönderiyorum" and then should send GK Residence. If the student is in university,
this message works fine. Don't ask if the parent provided the university too, like "Oğlum Marmara Üniversitesi'ne başladı onun için bakıyoruz". In that 
case ask only for campus clarification or uni clarification if needed. If not needed, then you have university and gender; send RecEngine. If you get
something like "Çocuğum İTÜ'yü kazandı onun için bakıyoruz" then ask for campus clarification, then gender and send RecEngine. Always tailor the
reactions to the context the lead has sent. 

D2.5 EXPLANATION: Exactly the same as D2.2, very same fix needed. Works as intended, simple string change needed.

---

## Group D3 — Mid-flow divergence in `awaiting_gender`

Setup: `merhaba` → `hangi` → answer with a valid Istanbul university (bot asks gender, lands in `awaiting_gender`). Then send divergence.

| ID | In `awaiting_gender`, send | Expected intent | Expected action | Pass condition | Result |
|----|----------------------------|-----------------|-----------------|----------------|--------|
| D3.1 | `fiyat ne kadar` | `price` | answer_and_reanchor | Bot sends `div_price_await_gender`; stays `awaiting_gender` | PASSED |
| D3.2 | `en yakın konum neresi` | `location` | answer_and_reanchor | Bot sends `div_location_await_gender` | PASSED |
| D3.3 | `boş yer var mı` | `vacancy` | answer_and_reanchor | Bot sends `div_vacancy_await_gender` | PASSED |
| D3.4 | `ödeme nasıl` | `logistics_payment` | answer_and_reanchor | Bot sends `div_payment_await_gender` | PASSED |

NOTE: Current messages at this stage make it sound like we're discriminating against customers based on gender, we have GOTTA change them. 

---

## Group D4 — Deterministic slot-skip (LLM must NOT be involved)

Verifies §7. The classifier should never fire when a slot is extractable.

| ID | Setup | Send | Pass condition | Result |
|----|-------|------|----------------|--------|
| D4.1 | Opener `fiyat ne` → bot sends `div_price_new`, state `awaiting_university` | `Marmara Üniversitesi Göztepe, erkek öğrenci` | BOTH slots extracted deterministically; **RecEngine fires**; bot never re-asks university or gender; `chatbot_logs` shows no classifier call on this turn | FAILED |
| D4.2 | In `awaiting_university` | `İTÜ, kız` | Uni + gender both set; RecEngine fires directly | FAILED |
| D4.3 | Opener `merhaba` → `hangi`, in `awaiting_university` | `Boğaziçi` | University resolves deterministically; advance to `awaiting_gender`; no classifier call | PASSED |
| D4.4 | In `awaiting_gender` (uni already set) | `erkek` | Gender resolves; RecEngine fires; no classifier call | PASSED |

D4.1 EXPLANATION: The bot asked div_price_new state awaiting_university no problem. But when provided with both the 
university and gender in the same message, because it's the behaviour for awaiting_university flow stage, it tried
to parse the whole message as a university name; which failed and triggered university name clarification message. 
Then when clarified as "Marmara Üniversitesi Göztepe" because match_university() function uses full string match
(terrible design choice, need to use trigram; tokenizing or something else that can handle these things) it failed
to recognize this as "marmara göztepe" and silently escalated. Failure on 2 dimensions: The flow cannot comprehend
extracting both answers from the same message on awaiting_university stage, and it can't match "Marmara Üniversitesi
Göztepe" because it uses full string match.

D4.1 SOLUTION IDEA: Change the behaviour of every flow stage before RecEngine to be able to extract any piece of 
information, skip the flow stage the info of which has been priorly extracted. Also switch over to trigram or 
tokenizer match to resolve the name matching. 

D4.1 QUESTION: Do we not already have multiple layers of fuzzy search if full string match fails? It should be
full string match against universities.name, full str match against universities.short_name, fuzzy match via
Levenshtein distance 0-3 based on char count, then compare against out of city universities. Did we forget to 
implement fuzzy matching fallbacks on the divergence flows, or do they just not work?

D4.2 EXPLANATION: Similar to the issue in D4.1, the bot was expecting only university information in awaiting_university
flow stage; so it parsed the entirety of the response as university name candidate and failed to match to anything because
it says "İTÜ, kız". Even if fuzzy matching is implemented here, it still wouldn't have worked because the stage simply
doesn't expect gender so it'll treat it all as one university and not be able to match to anything because for 6 characters
Levenshtein distance is 2. 

D4.2 SOLUTION IDEA: The solution is the same as D4.1's first issue. We make the flow stages expecting of both gender
and university. Once we make sure the words "kız", "erkek" etc. are extracted when they're isolated characters, 
the script will be allow to partition "İTÜ, kız" into "there is kız here so I must remove it and parse into field. 
Gender = kız. İTÜ is left, this matches a school from the DB. So school = İTÜ but campus is unclear, must ask
campus clarification.". We must implement this on every stage before RecEngine. 

---

## Group D5 — Same-intent persistence (cap at 2 phrasings → escalate)

Verifies §8.2. Each step is the SAME intent with no slot progress.

| ID | Sequence (all in `awaiting_university`, after `hangi`) | Pass condition | Result |
|----|--------------------------------------------------------|----------------|--------|
| D5.1 | (1) `fiyat ne kadar` → (2) `fiyat söyle fiyat` → (3) `ya fiyat` | Turn 1: `div_price_await_uni` (primary). Turn 2: `div_price_await_uni_alt` (alternate). Turn 3: **silent escalate** (`divergence_repeat_count` reached 3). `divergence_repeat_count` increments 1→2→3 in DB. | PASSED |
| D5.2 | (1) `fiyat ne kadar` → (2) `peki nerede` → (3) `fiyat` | Turn 2 is a DIFFERENT intent (`location`) → counter resets; bot sends `div_location_await_uni`. Turn 3 `price` again → counter=1 again, sends `div_price_await_uni` (primary, not alt). No escalate. | PASSED |
| D5.3 | (1) `fiyat ne kadar` → (2) `Marmara` | Turn 2 fills the university slot → counter resets to 0, `last_divergence_intent` NULL, advance to `awaiting_gender`. | PASSED |

NOTE: At any point during InfoGatherer + RecEngine flow, before RecEngine is sent the info to make a recommendation; 
if a customer interrupts the flow with an inquiry about a specific hotel, the response schema for that hotel should
immediately be served. I'd reckon this would need another intent type at divergence handler's system prompt and 
a new "all stages" type on the router table. 

---

## Group D6 — Different-question loop is UNCAPPED (must NOT escalate)

Verifies §8.1. Distinct answerable questions, each answered, indefinitely.

| ID | Sequence in `awaiting_university` | Pass condition | Result |
|----|-----------------------------------|----------------|--------|
| D6.1 | `fiyat ne` → `oda kaç kişilik` (→ if classified answerable) → `konum neresi` → `sadece İstanbul mu` → `ödeme nasıl` | Each turn: appropriate canned + re-anchor. **No escalate** across 5 different questions. State remains `awaiting_university` throughout. Counter never exceeds 1 (each intent differs from the previous). | FAILED |

D6.1 EXPLANATION: After the first divergent question is answered the script asks and expects university name in 
"awaiting_university". The second question is treated as an answer to the university question and when it inevitably
can't be parsed, the lead is reprompted for university name. I don't exactly know why this is happening, the previous
tests proved that the same question can be answered multiple times; mid-flow divergence works as well, but the 
moment we tested 2 different questions back to back it failed. 

D6.1 SOLUTION IDEA: It's good behaviour to try to match the response to the current question's answer. But for ALL 
messages before RecEngine we could run this: Do normal thing, try to get match, if no match, send to divergence 
handler. We'd integrate it into the current flow not have this simple and undetailed flow replace the whole 
divergence handling flow. It might be overkill as well, something to talk about. 

*(Note: intents without a seeded answer, e.g. a room-detail question that classifies `complex`, will escalate — that's correct. D6.1 should use intents that have rows: price/location/coverage/payment.)*

---

## Group D7 — Escalation & abstention

| ID | Setup | Send | Pass condition | Result |
|----|-------|------|----------------|--------|
| D7.1 | `awaiting_university` | `sözleşme şartlarınız neler` (novel/contractual) | `complex` → silent escalate | PASSED |
| D7.2 | opener | `Is the dorm available for international students?` | `non_turkish` → silent escalate | PASSED |
| D7.3 | opener | `Привет! Можно узнать подробнее?` | `non_turkish` → silent escalate | FAILED |
| D7.4 | `awaiting_gender` | `asdf qwer zxcv` (ambiguous noise) | Low-confidence → `complex`/`no_intent`; must NOT activate flow. Either silent escalate or silent ignore — never a spurious canned answer. | PASSED |

D7.3 EXPLANATION: Did not respond as scripted, but it also failed to add human_needed label. 

---

## Group D8 — Prerequisite fixes

### D8.1 — Off-script substring false positives (§9.1) — HIGH priority
Setup: `merhaba` → `hangi`, in `awaiting_university`.

| ID | Send | Pass condition | Result |
|----|------|----------------|--------|
| D8.1a | `Cihangir` | NOT escalated as off-script. Proceeds through matching (accepted if it resolves as a location/campus answer per DB; if genuinely unmatched, may clarify — but must NOT trip `hangi` marker). | PASSED |
| D8.1b | `Kağıthane` | Same — `ne` marker must not fire on a boundary. | PASSED |
| D8.1c | `Güneşli` | Same — `ne` must not fire. | PASSED |
| D8.1d (control) | `ne kadar` | SHOULD still classify/handle as before — the boundary `ne` legitimately present as a standalone token. | UNCLEAR |

ABOUT D8.1a: I'm not certain I completely understand but I think it is checking if Cihangir will crash the script or 
get a legit clarification response. It triggered clarification so success. 

ABOUT D8.1d: The question 'ne kadar' was handled as a price inquiry and returned "Fiyatlarımız şubeye göre değişiyor efendim..."


### D8.2 — Greeting variants (§9.2)
| ID | Opener | Pass condition | Result |
|----|--------|----------------|--------|
| D8.2a | `sa` | Accepted as greeting → bot proceeds (asks university), NOT ignored | PASSED |
| D8.2b | `slm` | Accepted as greeting | PASSED | 
| D8.2c | `Heyy` | Accepted as greeting | PASSED |
| D8.2d (control) | `masa` | NOT falsely accepted (boundary `sa` must not match inside a word) | PASSED |

### D8.3 — Outbound-first gating (§9.3)
| ID | Setup | Pass condition | Result |
|----|-------|----------------|--------|
| D8.3a | Create a conversation where the FIRST message is an agent outgoing, then lead replies `merhaba` | `bot_enabled=false`; bot sends nothing; lead's `merhaba` gets no bot response | PASSED |
| D8.3b (control) | Normal inbound-first conversation | `bot_enabled=true`; bot behaves normally | PASSED |

### D8.4 — Opener university detection (§9.4)
| ID | Opener | Pass condition | Result |
|----|--------|----------------|--------|
| D8.4a | `Bahçeşehir Üniversitesi` (Istanbul, no greeting) | Resolves → bot asks gender (NOT `IGNORE`) | PASSED |
| D8.4b | `Trakya üniversitesi` (out-of-city, no greeting) | Out-of-city path → bot sends `istanbul` canned → `completed` (NOT `IGNORE`) | PASSED |

NOTE: If InfoGatherer currently can't, (probably can't) it should be able to parse university name from block of text. 

---

## Group D9 — Failure / resilience (fault injection) -- Cancelled because no need, waste of time. 

| ID | Condition | Pass condition |
|----|-----------|----------------|
| D9.1 | Point `MODEL_ID`/key at an invalid value (simulate Gemini down); send `fiyat ne kadar` opener | After one retry, falls back to **current behavior**: silent `IGNORE` in `new`. No crash, no partial write. |
| D9.2 | Force classifier to return an unknown label (e.g. temporarily stub `"pricing"`) | Router lookup miss → escalate; no exception surfaced to webhook path |
| D9.3 | Send divergence while a RecEngine run is in progress (`recengine_running`) | Classifier NOT invoked (non-firing state); message ignored per current behavior |

---

## Regression gate (must pass before widening allowlist)

- [ ] All existing F-suite and O-suite cases behave identically (no regression from slot-skip or marker changes).
- [ ] `pytest` full suite green (198 existing + new divergence tests).
- [ ] D1–D9 all pass on both allowlisted phones.
- [ ] `chatbot_logs` shows intent + action for every divergence turn (observability for post-launch tuning).
- [ ] Manual spot-check: 10 real historic opener/divergence phrasings from the corpus replayed live produce sensible intents.

## Post-launch instrumentation (first week)
Track, from `chatbot_logs`: divergence intent distribution, action distribution, escalate-rate within divergence, persistence-escalation frequency (how often leads hit the 3-strike cap), and any `complex`/`non_turkish` volume. Use this to decide which clarification-state cells to seed next and whether any `complex` sub-cluster recurs enough to promote to an answerable intent.
