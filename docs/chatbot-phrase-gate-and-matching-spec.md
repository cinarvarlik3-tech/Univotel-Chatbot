# Chatbot — Phrase Gate & Matching Improvements Spec

**Scope:** InfoGatherer phrase gate expansion, `matching.py` alias normalization fix, and invalid input handling for university/campus.
**Status:** Pre-implementation — addresses blockers listed in `docs/v1-audit.md` and F-suite failures.
**Amends:** `docs/univotel-chatbot-spec.md` §8.1 (InfoGatherer ContextRun Step 1) and `app/layers/matching.py`.

---

## 1. Phrase Gate Overhaul (`app/layers/info_gatherer.py`)

### 1.1 Non-Negotiable Pre-conditions

Both of the following pre-conditions are evaluated before any keyword matching. At least one must be satisfied for a message to be considered a greeting. If neither is satisfied, the message is silently ignored — no `human_needed`, no outbound message.

| Pre-condition | Logic |
|---|---|
| **A — First message** | This is the first inbound `message_type = incoming` message in the conversation (lowest `chatwoot_message_id` among all incoming messages for this `cw_id`). |
| **B — Specific hotel inquiry** | Message matches `hotels.name` via n-gram Levenshtein (see §3). |

Pre-condition A and B are independent — either alone is sufficient. Both being true is valid.

**Special behavior when B is satisfied:** Regardless of whether A is also true, trigger the direct hotel-name path immediately — RecEngine is bypassed, the matched hotel's `response_schemas` are sent. This applies even mid-conversation on a `completed` flow (existing behavior, now explicitly gated through B). State is updated: `ilgili_otel` is reset to the newly matched hotel; `university_id` and `gender` are not cleared.

### 1.2 Keyword Filters (applied after pre-conditions)

If pre-condition A is satisfied (first message), at least one of the following keyword filters must also match. If pre-condition B is satisfied, keyword filters are skipped entirely — the hotel path fires unconditionally.

**Filter 1 — Fixed widget match**

Exact substring match OR Levenshtein distance ≤ 2 against the full message against the following templates:

```
"Merhaba! Bunun hakkında daha faza bilgi alabilir miyim?"
"Merhabalar Univotel!"
"Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum."
"Bana en yakın Univotel neresi?"
"Hello! Can I get more info on this?"
"Hello Univotel!"
"Merhaba! [x] yakınında öğrenci konaklaması hakkında bilgi alabilir miyim?"
"Merhaba! [x] yakınında öğrenci konaklaması arıyorum."
```

For the last two templates, `[x]` is a wildcard — match the prefix `"Merhaba!"` + suffix `"yakınında öğrenci konaklaması"` as anchors.

**Filter 2 — Entity match**

N-gram Levenshtein scan (see §3) finds a match in any of:

- `universities.name`
- `universities.university_short_name`
- `university_aliases.alias`
- `hotels.name`

A match in any of these four sources satisfies Filter 2.

**Filter 3 — Greeting word**

Message contains any of the following as a substring (case-insensitive, diacritic-insensitive after `normalize()`):

```
merhaba, merhabalar, selam, selamlar, hi, hello, hey,
iyi günler, iyi akşamlar, iyi sabahlar, günaydın, kolay gelsin
```

**Filter 4 — Housing intent keyword**

Message contains at least one of:

```
konaklama, yurt, oda, öğrenci oteli, residence
```

**Filter 5 — Staj/dönem context**

Message contains at least one of:

```
staj, stajyer, yaz dönemi, güz dönemi, sonbahar dönemi, dönem için
```

**Filter 6 — Proximity intent**

Message contains at least one of:

```
yakınında, yakın, bölgesinde, en yakın, üniversiteme yakın
```

**Filter 7 — Price/info intent (conjunction required)**

Message contains at least **2** of:

```
fiyat, bilgi, için
```

Standing alone, none of these three words triggers the gate. At least two together are required.

### 1.3 Decision Table

```
Pre-condition A met AND (Filter 1 OR 2 OR 3 OR 4 OR 5 OR 6 OR 7 matched)
  → Greeting confirmed. Extract context (§1.4), run flow.

Pre-condition B met (hotel name match)
  → Hotel path fires. Skip keyword filters. Skip university/gender. Send response_schemas.

Neither A nor B met
  → Ignore. No DB write. No outbound message.

A met but no filter matched
  → Ignore. No DB write. No outbound message.
```

### 1.4 Context Extraction on Greeting Confirmation

When a greeting is confirmed (pre-condition A path), extract whatever context is available from the message before asking questions. This avoids asking for information the lead already provided.

Extract in this order:

1. **Hotel name** (n-gram Levenshtein against `hotels.name`) → if matched, go to hotel path (same as pre-condition B).
2. **Gender** (`kız`, `bayan`, `kadın` → `female`; `erkek`, `bay`, `oğlan` → `male`).
3. **University** (n-gram Levenshtein against all four entity sources — see §3).

Write any extracted values to `conversations` immediately. Only ask for what is still missing.

---

## 2. Invalid Input Handling (`app/layers/info_gatherer.py`)

Applies when the flow is in `awaiting_university`, `awaiting_campus_clarification`, or when the matched university has multiple campuses requiring disambiguation.

### 2.1 University Not Matched

When a message arrives in `awaiting_university` or `awaiting_university_clarification` and matching returns `MatchConfidence.NONE`:

**If input is 2 words or fewer (word count after `normalize()`):**

Send: `"Efendim üniversite ismini çıkaramadım, resmi adı neydi okulunuzun?"`

State stays in `awaiting_university`. This is the first clarification attempt.

**If input is more than 2 words:**

Send the same message. State moves to `awaiting_university_clarification` (one round only).

**On second failure (state was already `awaiting_university_clarification`):**

Send the out-of-Istanbul canned response. State → `completed`. No `human_needed`.

Rationale: A university not in the DB is safe to treat as out-of-Istanbul — any Istanbul university Univotel serves is in the DB. See F10 annotation in `docs/wa_test_links.md`.

### 2.2 Campus Not Matched

When a message arrives in `awaiting_campus_clarification` and no campus within the pending parent university matches:

Send: `"Efendim kampüs ismini çıkaramadım, resmi adı neydi kampüsünüzün?"`

State stays in `awaiting_campus_clarification`. This is the first clarification attempt.

**On second failure:**

FallBack is called with full conversation context. Until FallBack V2 is implemented: set `flow_state = human_needed`. No outbound message (consistent with existing `_escalate_human_needed` behavior — see Known Issues in README).

### 2.3 Retry Counter

Add a `clarification_attempt` counter to `conversations` (or track via existing `flow_state` transitions — implementation detail). The counter resets on any successful match. It does not need to persist across sessions.

---

## 3. Matching — Alias Normalization Fix (`app/layers/matching.py`)

### 3.1 Problem

`normalize()` is applied to raw input before comparison, but `alias.alias` values in DB are stored in their original form (with Turkish diacritics). The comparison `alias.alias == normalized` fails when the alias contains diacritics.

Example:
- DB stores: `taşkışla`
- `normalize("taşkışla")` → `taskisla`
- `normalize(input "taşkışla")` → `taskisla`
- Current comparison: `"taşkışla" == "taskisla"` → `False`

### 3.2 Fix

Apply `normalize()` to both sides of every alias comparison. Two locations in `matching.py`:

**Parent alias check (runs before Tier 1):**

```python
# Before
if alias.alias == normalized and alias.parent_university_id:

# After
if normalize(alias.alias) == normalized and alias.parent_university_id:
```

**Tier 2 — campus-level alias lookup:**

```python
# Before
if alias.alias == normalized and alias.university_id:

# After
if normalize(alias.alias) == normalized and alias.university_id:
```

No other changes to `matching.py`. The `normalize()` function itself is correct and unchanged.

### 3.3 N-gram Levenshtein Scan (phrase gate §1.2 Filter 2)

For phrase gate entity matching (not the existing InfoGatherer university extraction, which operates on a narrow window), scan the message using a sliding window of 1–4 word n-grams:

```
tokenize(message) → word list
for n in [4, 3, 2, 1]:           # longest match first
    for each n-gram window:
        candidate = join(n-gram)
        normalized = normalize(candidate)
        run match_university(normalized, universities, aliases)
        if result.confidence != NONE → return result
return NONE
```

Longest window first — prevents `"İstanbul"` from matching as a university before `"İstanbul Teknik Üniversitesi"` can be attempted.

This scan is used only for phrase gate Filter 2. The existing InfoGatherer extraction logic (keyword window search) is unchanged for the main flow.

---

## 4. RecEngine — Runtime Parameter Override

### 4.1 Context

When a `completed` conversation receives a mid-conversation university reference (pre-condition A not met, B not met, but the lead names a different university), the scripted flow cannot restart cleanly. This is a known gap deferred to FallBack V2.

However, when the flow does restart legitimately (pre-condition A on a new conversation, or B firing), RecEngine must be callable with runtime parameters rather than exclusively reading from DB.

### 4.2 Change

`rec_engine.py` already receives `conversation_id` and resolves `university_id` and `gender` from DB. Add an optional override:

```python
async def run_rec_engine(
    conversation_id: uuid.UUID,
    idempotency_key: str,
    university_id_override: uuid.UUID | None = None,
    gender_override: str | None = None,
) -> None:
    university_id = university_id_override or (read from DB)
    gender = gender_override or (read from DB)
    ...
```

When called with overrides, DB values are not written before the run — overrides are runtime-only. DB is written only on RecEngine completion (existing `write_attributes_at_flow_completion` behavior).

This enables the future FallBack V2 path where a mid-conversation university reference triggers a fresh recommendation without DB state contamination.

---

## 5. Files Changed

| File | Change |
|---|---|
| `app/layers/info_gatherer.py` | Phrase gate rewrite (§1), invalid input handling (§2), context extraction on greeting (§1.4) |
| `app/layers/matching.py` | `normalize(alias.alias)` on both alias comparison sites (§3.2) |
| `app/layers/rec_engine.py` | Optional `university_id_override` / `gender_override` parameters (§4.2) |
| `app/db/queries.py` | Query support for first-message check (lowest `chatwoot_message_id` among incoming for a `cw_id`) if not already present |
| `migrations/014_clarification_attempt.sql` | Add `clarification_attempt integer NOT NULL DEFAULT 0` to `conversations` (or handle in flow state — implementation decision) |

---

## 6. Test Coverage

### F-suite cases now expected to pass

| Test | Step | Was | Expected |
|---|---|---|---|
| F1 | Step 1: `Merhabalar, üniversiteme yakın konaklama arıyorum` | Phrase gate fail | Pass — Filter 6 (`yakın`) |
| F2 | Step 1: `merhaba` | Phrase gate fail | Pass — Filter 3 |
| F3 | Step 1: `Merhabalar konaklama için yazıyorum` | Phrase gate fail | Pass — Filter 4 (`konaklama`) |
| F4 | Step 1: `selam` | Phrase gate fail | Pass — Filter 3 |
| F5 | Step 1: `Merhaba, yurt arıyorum` | Phrase gate fail | Pass — Filter 3 + Filter 4 |
| F5b–f | Step 1: `merhaba` | Phrase gate fail | Pass — Filter 3 |
| F6 | Step 2: `taşkışla` | Alias match fail | Pass — §3.2 fix |
| F8 | Step 3: invalid campus | Freeze | Pass — §2.2 sends clarification message |

### New unit tests (`tests/test_matching.py`)

- `test_alias_normalization_diacritic`: assert `taşkışla` input resolves to İTÜ Maçka `university_id`
- `test_alias_normalization_stored_diacritic`: assert stored alias `taşkışla` normalizes correctly on both sides

### New unit tests (`tests/test_info_gatherer.py`)

- `test_phrase_gate_merhaba`: bare `merhaba` on first message → greeting confirmed
- `test_phrase_gate_selam`: bare `selam` → greeting confirmed
- `test_phrase_gate_konaklama`: `konaklama için yazıyorum` → greeting confirmed
- `test_phrase_gate_yakın`: `üniversiteme yakın yer arıyorum` → greeting confirmed
- `test_phrase_gate_mid_conversation_ignored`: same messages not on first inbound → ignored
- `test_invalid_university_short_input`: ≤2 words, no match → clarification message sent
- `test_invalid_university_long_input`: >2 words, no match → clarification message sent
- `test_invalid_university_second_failure`: second failure → out-of-Istanbul canned response
- `test_invalid_campus_first_failure`: bad campus → clarification message sent
- `test_invalid_campus_second_failure`: second bad campus → `human_needed` (FallBack stub)

---

## 7. Out of Scope

The following are explicitly not addressed in this spec:

- **Silent `human_needed`** — escalations still produce no outbound message. Documented as a known issue in README.
- **FallBack V2** — all FallBack call sites remain stubbed as `human_needed`.
- **RecEngine geography / `hotel_accessible_universities` narrowing** — open product decision (F3 annotation).
- **Mid-conversation university re-reference** — deferred to FallBack V2 (§4.1).
- **Out-of-Istanbul vs. nonsense university disambiguation** — current behavior (treat both identically) is acceptable per F10 annotation.
- **`deal_awaiting_msg` copy** — separate open item, unchanged.
