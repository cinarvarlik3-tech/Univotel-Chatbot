# InfoGatherer Drop / Accept / Escalate Decision Specification

**Purpose:** Literal reference for every rule that determines whether an inbound lead message is (a) accepted into the scripted flow, (b) silently ignored, or (c) escalated to `human_needed`. Extracted from source as of the current codebase.

**Source files:** `app/layers/phrase_gate.py`, `app/layers/answer_classifier.py`, `app/layers/matching.py`, `app/layers/info_gatherer.py`

**Three fates used in this document:**

| Fate | Code behavior |
|------|----------------|
| **(a) Accept / advance** | State changes and/or outbound canned message; flow continues |
| **(b) Silently ignore** | No Chatwoot outbound; no `human_needed`; state unchanged (may log to `chatbot_logs`) |
| **(c) Escalate** | `_escalate_human_needed()` — `flow_state → human_needed`, `human_needed` Chatwoot label, fatal log; **no Chatwoot message** |

---

## 1. Phrase gate (`evaluate_phrase_gate`)

**Module:** `app/layers/phrase_gate.py`  
**Called from:** `info_gatherer._handle_new()` only (i.e. when `process_message` falls through to `_handle_new`; see §4 `new` state).

**Inputs loaded from DB in `_handle_new`:**
- `hotels` ← `queries.get_all_hotels()` → table `hotels`
- `universities` ← `queries.get_all_universities()` → table `universities`
- `aliases` ← `queries.get_all_university_aliases()` → table `university_aliases`

**`is_first_inbound`:** `True` when `queries.is_first_inbound_message(conversation_id, chatwoot_message_id)` **or** (if `chatwoot_message_id is None`) when `conversation.flow_state == "new"`.

### 1.1 Global evaluation order (`evaluate_phrase_gate`)

```
1. Pre-condition B — match_hotel_by_ngram(content, hotels)
   → if match: HOTEL_PATH (any message, first or not)

2. if not is_first_inbound:
   → IGNORE (reason: "not_first_inbound_and_no_hotel_match")

3. Filter 1 — _filter1_widget_match(content)
   → if match: GREETING (reason: "filter1_widget")

4. Filter 2 — scan_entities_by_ngram(content, universities, aliases)
   → if entity.confidence != MatchConfidence.NONE: GREETING (reason: "filter2_entity")

5. normalized_text = normalize(content)

6. Filter 3 — _filter3_greeting(normalized_text)
   → if match: GREETING (reason: "filter3_greeting")

7. Filter 4 — _filter4_housing(normalized_text)
   → if match: GREETING (reason: "filter4_housing")

8. Filter 5 — _filter5_staj(normalized_text)
   → if match: GREETING (reason: "filter5_staj")

9. Filter 6 — _filter6_proximity(normalized_text)
   → if match: GREETING (reason: "filter6_proximity")

10. Filter 7 — _filter7_price_info(normalized_text)
    → if match: GREETING (reason: "filter7_price_info")

11. IGNORE (reason: "first_inbound_but_no_filter_matched")
```

**Note:** `_any_keyword_filter()` exists in the same file but is **not** called by `evaluate_phrase_gate`.

**Outcome enum `PhraseGateAction`:**
- `IGNORE` = `"ignore"`
- `GREETING` = `"greeting"`
- `HOTEL_PATH` = `"hotel_path"`

### 1.2 Pre-condition B — hotel n-gram (any inbound message)

**Function:** `match_hotel_by_ngram(text, hotels)` in `matching.py`  
**Gate:** Runs **before** first-inbound check; applies to **every** message that reaches `_handle_new`.

**Logic:**
- Scan `scan_ngrams(text)` — contiguous word n-grams, `min_n=1`, `max_n=4`, **longest n first**
- For each n-gram candidate, for each hotel in `hotels`:
  - Skip if `hotel.is_visible` is false
  - `normalized_candidate = normalize(candidate)`
  - `normalized_name = normalize(hotel.name)`
  - **Exact match:** `normalized_candidate == normalized_name` → return hotel
  - **Levenshtein match:** `levenshtein_distance(normalized_candidate, normalized_name) <= _get_levenshtein_cutoff(normalized_candidate)` → return hotel
- First matching hotel wins (longest n-gram order, then hotel iteration order)

**Hotel names:** From DB table `hotels`, column `name` (via `queries.get_all_hotels()`).

**Outcome:** `HOTEL_PATH`, `reason="precondition_b_hotel_match"`

**InfoGatherer follow-up:** `_fire_hotel_path` → send hotel `response_schemas`, `flow_state → completed` (if not already).

### 1.3 Filter 1 — widget templates

**Function:** `_filter1_widget_match(content)`  
**Pre-condition:** First inbound only (step 3+ in §1.1).

**Complete `_WIDGET_TEMPLATES` list (exact strings in code):**

```
"Merhaba! Bunun hakkında daha faza bilgi alabilir miyim?"
"Merhabalar Univotel!"
"Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum."
"Bana en yakın Univotel neresi?"
"Hello! Can I get more info on this?"
"Hello Univotel!"
```

**Match logic (any one triggers match):**

1. **Raw substring:** `template in content` (case-sensitive, on raw `content`, not normalized)
2. **Levenshtein on full message:** `levenshtein_distance(normalize(template), normalize(content)) <= LEVENSHTEIN_CUTOFF`
   - `LEVENSHTEIN_CUTOFF = 2` (defined in `matching.py`, imported into `phrase_gate.py`)
3. **Wildcard pair (both required, on normalized full message):**
   - `_WILDCARD_PREFIX = normalize("Merhaba!")`  → computed at import
   - `_WILDCARD_SUFFIX = normalize("yakınında öğrenci konaklaması")`  → computed at import
   - Match if: `_WILDCARD_PREFIX in normalized_full AND _WILDCARD_SUFFIX in normalized_full`
   - where `normalized_full = normalize(content)`

**Outcome:** `GREETING`

### 1.4 Filter 2 — entity n-gram

**Function:** `scan_entities_by_ngram(content, universities, aliases)` in `matching.py`  
**Pre-condition:** First inbound only.

**Logic:**
- For each n-gram from `scan_ngrams(text)` (1–4 words, longest first)
- Run full `match_university(candidate, universities, aliases)` (see §3)
- Return first result where `confidence != MatchConfidence.NONE`

**University / alias data:** DB tables `universities`, `university_aliases` (not hardcoded).

**Outcome:** `GREETING`, `reason="filter2_entity"`

### 1.5 Filter 3 — greetings

**Function:** `_filter3_greeting(normalized_text)`  
**Pre-condition:** First inbound only; input is `normalize(content)`.

**Complete `_GREETING_WORDS` list:**

```
"merhaba"
"merhabalar"
"selam"
"selamlar"
"hi"
"hello"
"hey"
"iyi günler"
"iyi akşamlar"
"iyi sabahlar"
"günaydın"
"kolay gelsin"
```

**`_BOUNDARY_GREETINGS` (word-boundary match via regex):**

```
"hi"
"hey"
```

**Match helper `_contains_keyword(normalized_text, keyword, boundary_tokens)`:**
- `kw = normalize(keyword)`
- If `kw in boundary_tokens`: match `(?<!\w){kw}(?!\w)` in `normalized_text`
- Else: substring `kw in normalized_text`

**Outcome:** `GREETING`

### 1.6 Filter 4 — housing intent

**Complete `_HOUSING_WORDS` list:**

```
"konaklama"
"yurt"
"oda"
"öğrenci oteli"
"residence"
```

**`_BOUNDARY_HOUSING`:**

```
"oda"
"yurt"
```

**Match logic:** Same `_contains_keyword` as Filter 3 on `normalize(content)`.

**Outcome:** `GREETING`

### 1.7 Filter 5 — staj / dönem

**Complete `_STAJ_WORDS` list:**

```
"staj"
"stajyer"
"yaz dönemi"
"güz dönemi"
"sonbahar dönemi"
"dönem için"
```

**`_BOUNDARY_STAJ`:**

```
"staj"
```

**Match logic:** Same `_contains_keyword` on `normalize(content)`.

**Outcome:** `GREETING`

### 1.8 Filter 6 — proximity

**Complete `_PROXIMITY_WORDS` list:**

```
"yakınında"
"yakın"
"bölgesinde"
"en yakın"
"üniversiteme yakın"
```

**Match logic:** For each word `w` in list: `normalize(w) in normalized_text` (substring on normalized full message). **No** word-boundary special case.

**Outcome:** `GREETING`

### 1.9 Filter 7 — price / info

**Complete `_FILTER7_TERMS` tuple:**

```
"fiyat"
"bilgi"
"icin"
```

**Match logic:** `hits = count of terms where term in normalized_text`; match if `hits >= 2` (at least **2 of 3** terms as substrings in normalized text).

**Note:** `icin` is ASCII form; `normalize()` folds Turkish diacritics so `için` in user text becomes comparable via normalized pipeline for other filters; Filter 7 checks literal `"icin"` in `normalized_text` after `normalize()` (which maps `ç→c`, so `için` → `icin`).

**Outcome:** `GREETING`

### 1.10 First inbound, no filter matched

**Outcome:** `IGNORE`, `reason="first_inbound_but_no_filter_matched"`

**InfoGatherer follow-up:** `_log_phrase_gate_ignore()` — info log + `chatbot_logs` entry; **no state change, no Chatwoot message**.

### 1.11 Not first inbound, no hotel match

**Outcome:** `IGNORE`, `reason="not_first_inbound_and_no_hotel_match"`

**InfoGatherer follow-up:** Same silent ignore as §1.10.

---

## 2. Answer classifier (`classify_university_reply`)

**Module:** `app/layers/answer_classifier.py`

### 2.1 Where it runs (flow states)

| `flow_state` | Classifier invoked? |
|--------------|---------------------|
| `awaiting_university` | **Yes** — only after `match_university()` returns `NONE` AND `match_out_of_city()` returns no match |
| `awaiting_university_clarification` | **No** |
| `awaiting_campus_clarification` | **No** |
| `awaiting_gender` | **No** (separate gender regex path in `info_gatherer`) |
| `new` / `_handle_new` | **No** |
| All other states | **No** |

### 2.2 `AnswerAssessment` enum

```
ANSWER_ATTEMPT = "answer_attempt"
NOT_AN_ANSWER    = "not_an_answer"
```

### 2.3 `classify_university_reply(content, universities)` — full decision order

**Precondition (enforced by caller):** Istanbul `match_university` already returned `NONE`; out-of-city already checked.

**Step 1 — `_offscript_markers(content)`**

If `True` → `NOT_AN_ANSWER`

**Step 2 — `is_near_miss_university(content, universities)`**

If `True` → `ANSWER_ATTEMPT`

**Step 3 — `word_count_after_normalize(content) <= _SHORT_ANSWER_MAX_WORDS`**

`_SHORT_ANSWER_MAX_WORDS = 2`

If `True` → `ANSWER_ATTEMPT`

**Step 4 — `_has_education_anchor(_fold_diacritics(content))`**

If `True` → `ANSWER_ATTEMPT`

**Step 5 — default**

→ `NOT_AN_ANSWER`

### 2.4 `_offscript_markers(content)` — complete marker sets

Returns `False` if `content.strip()` is empty.

**Trigger A — trailing question mark**

```
content.strip().rstrip().endswith("?")
```

**Trigger B — question clitics (standalone tokens)**

Tokenization: `_tokenize_for_markers(content)` → split `_fold_diacritics(stripped)` on regex `[^\w]+`, drop empty tokens.

**`_QUESTION_CLITICS` frozenset:**

```
"mi"
"mı"
"mu"
"mü"
```

Match if **any token** is in `_QUESTION_CLITICS`.

**Trigger C — phrase substring on folded text**

`folded = _fold_diacritics(stripped)` — lowercase + diacritic fold **without** university suffix stripping.

**Complete `_QUESTION_WORDS` tuple:**

```
"ne"
"nerede"
"nerde"
"nasil"
"neden"
"nicin"
"niye"
"kac"
"kim"
"ne zaman"
"ne kadar"
"hangi"
```

**Complete `_REQUEST_VERBS` tuple:**

```
"istiyorum"
"ariyorum"
"bakiyorum"
"bakiyoruz"
"alabilir"
"olur mu"
"mumkun mu"
"var mi"
```

**Complete `_THIRD_PERSON_REFERENTS` tuple:**

```
"kizim"
"oglum"
"cocugum"
"kardesim"
"arkadasim"
"yegenim"
"esim"
```

**Phrase match:** For each phrase in `_QUESTION_WORDS + _REQUEST_VERBS + _THIRD_PERSON_REFERENTS`:

```
_fold_diacritics(phrase) in folded
```

(substring on diacritic-folded text)

### 2.5 `_has_education_anchor(folded_text)` — complete `_EDUCATION_ANCHORS` tuple

```
"universite"
"university"
"fakulte"
"kampus"
"yuksekokol"
"myo"
```

Match: any anchor as **substring** in `folded_text`.

### 2.6 `_fold_diacritics(text)` (classifier token folding)

```
text.replace("İ", "i").replace("I", "ı")
text.lower().translate(_DIACRITIC_MAP)
```

**`_DIACRITIC_MAP`:**

```
"şŞğĞıİöÖüÜçÇ" → "sSgGiIoOuUcC"
```

### 2.7 InfoGatherer mapping of classifier result (`_handle_awaiting_university`)

| `AnswerAssessment` | InfoGatherer action |
|--------------------|---------------------|
| `NOT_AN_ANSWER` | `_escalate_human_needed(..., internal_class="off_script_no_answer")` → **(c)** |
| `ANSWER_ATTEMPT` | `_handle_university_no_match()` → **(a)** clarify path (see §4) |

### 2.8 Gender path (separate from `answer_classifier.py`)

**Module:** `info_gatherer._handle_awaiting_gender`  
**Flow state:** `awaiting_gender` only

**`GENDER_FEMALE` regex** (case-insensitive, word boundaries):

```
\b(kiz|kız|bayan|kadın|kadin)\b
```

**`GENDER_MALE` regex** (case-insensitive, word boundaries):

```
\b(bay|erkek|oglan|oğlan)\b
```

**Decision order:**
1. If `GENDER_FEMALE.search(content)` → `gender = "female"`
2. Elif `GENDER_MALE.search(content)` → `gender = "male"`
3. Else → `_escalate_human_needed(..., internal_class="off_script_no_answer")` → **(c)**

**No** `classify_university_reply` call on gender path.

**Early gender capture in `_handle_new`:** `_extract_gender(content)` using same regexes; if match, `queries.set_conversation_gender(cid, gender)` **before** university routing; does not skip `hangi` if university not resolved.

---

## 3. `matching.py` — normalization, tiers, cutoffs

### 3.1 Constants

```python
LEVENSHTEIN_CUTOFF = 2          # used by phrase_gate Filter 1 widget Levenshtein only
NEAR_MISS_BAND = 2              # is_near_miss_university default band
NEAR_MISS_MIN_LEN = 4           # normalized length minimum for near-miss
```

### 3.2 `normalize(text)` steps (in order)

1. `text.replace("İ", "i").replace("I", "ı")`
2. `text.lower().translate(_DIACRITIC_MAP)` where map is `"şŞğĞıİöÖüÜçÇ" → "sSgGiIoOuUcC"`
3. `.strip()`
4. If text **ends with** any suffix in `_SUFFIXES` (first match only, single strip), remove that suffix and `.strip()` again:

**Complete `_SUFFIXES` list:**

```
"üniversitesi"
"universitesi"
"university"
"uni"
"üni"
```

### 3.3 `match_university(raw_text, universities, aliases)` tier order

**Empty/whitespace-only after normalize → `MatchConfidence.NONE`**

**Tier 0 — Parent alias (before Tier 1):**

- For each row in `aliases` (`university_aliases`):
  - If `normalize(alias.alias) == normalized` **and** `alias.parent_university_id` is set
  - → `MatchConfidence.ALIAS`, `parent_university_id=alias.parent_university_id`

**Tier 1 — Exact name / short_name:**

- For each row in `universities`:
  - `normalize(uni.name) == normalized` → `MatchConfidence.EXACT`, `university_id=uni.id`
  - If `uni.university_short_name` and `normalize(uni.university_short_name) == normalized` → `EXACT`

**Tier 2 — Campus-level alias:**

- For each row in `aliases`:
  - If `normalize(alias.alias) == normalized` **and** `alias.university_id` is set
  - → `MatchConfidence.ALIAS`, `university_id=alias.university_id`

**Tier 3 — Levenshtein:**

- `cutoff = _get_levenshtein_cutoff(normalized)`
- For each `uni` in `universities`: compare `normalized` to `normalize(uni.name)` only (not short_name in Tier 3)
- Collect hits where `levenshtein_distance <= cutoff`
- If no hits → `NONE`
- If one unique minimum distance → `LEVENSHTEIN`
- If tie at minimum distance → `AMBIGUOUS`

**DB sources:** `universities` table (`name`, `university_short_name`), `university_aliases` table (`alias`, `university_id`, `parent_university_id`).

### 3.4 `_get_levenshtein_cutoff(normalized: str)` — length → cutoff mapping

Based on `len(normalized)` **after** `normalize()`:

| Condition | Cutoff |
|-----------|--------|
| `length <= 3` | `0` (Tier 3 disabled) |
| `length <= 5` | `1` |
| `length <= 7` | `2` |
| else | `3` |

Used by: `match_university` Tier 3, `match_out_of_city` fuzzy pass, `match_hotel_by_ngram`, `is_near_miss_university`.

### 3.5 `is_near_miss_university(raw_text, universities, band=NEAR_MISS_BAND)`

**Returns `False` if:**
- `len(normalize(raw_text)) < NEAR_MISS_MIN_LEN` (i.e. `< 4`)

**Otherwise:**

- `cutoff = _get_levenshtein_cutoff(normalized)`
- `max_dist = cutoff + band` (default `band=2`)
- For each `uni` in `universities`, for each of `(uni.name, uni.university_short_name)` if not empty:
  - `dist = levenshtein_distance(normalized, normalize(candidate))`
  - **`True` if:** `cutoff < dist <= max_dist`

**DB:** Istanbul universities from `universities` table only (not aliases table directly).

### 3.6 `match_out_of_city(raw_text, out_of_city_unis)`

**Called when:** Istanbul `match_university` returned `NONE`.

**DB:** `queries.get_all_out_of_city_universities()` → table `out_of_city_universities` (`name`, `short_name`, `city`).

**Logic:**

1. Exact: `normalize(uni.name) == normalized` or `normalize(uni.short_name) == normalized`
2. If `cutoff > 0`: fuzzy against `name` and `short_name`; pick lowest distance hit (first after sort)

**Trigger in InfoGatherer:** `_fire_out_of_city` → canned `istanbul` (`CANNED_ISTANBUL`), `flow_state → completed` — **(a)**, not `human_needed`.

### 3.7 `word_count_after_normalize(text)`

`len(tokenize(text))` where `tokenize` = `normalize(text).split()` on whitespace.

---

## 4. State-by-state inbound message fate table

**Entry:** `process_message(conversation, chatwoot_conversation_id, message_content, chatwoot_message_id)`

**Global pre-checks (all states):**

| Condition | Fate |
|-----------|------|
| `flow_state in ("stopped", "human_needed")` | **(b)** Log info, return — no action |
| `content.strip()` empty | **(b)** Log info, keep state, return |

**Escalation helper `_escalate_human_needed`:** Always **(c)** — DB `human_needed`, label `human_needed`, no outbound message.

---

### 4.1 `new` (and any non-listed state routed to `_handle_new`)

Includes: initial `new`, `NULL`/unset flow_state if routed here, any state not explicitly handled below.

**Handler:** `_handle_new`

#### Step A — Phrase gate

See §1. Outcomes in InfoGatherer:

| Gate action | Fate |
|-------------|------|
| `IGNORE` | **(b)** `_log_phrase_gate_ignore` — no state change, no Chatwoot message |
| `HOTEL_PATH` | **(a)** `_fire_hotel_path` → hotel schemas, `completed` |
| `GREETING` | Continue to Step B |

#### Step B — Second hotel scan (redundant safety)

`match_hotel_by_ngram(content, all_hotels)` — if match → **(a)** `_fire_hotel_path`

#### Step C — Early gender write (non-terminal)

If `_extract_gender(content)` matches → write `gender` to DB; **continue** (does not exit handler).

Gender regexes: see §2.8.

#### Step D — University resolution from greeting

`_resolve_university_from_greeting(content, all_unis, all_aliases)`:

1. `_extract_university_candidate(text)`:
   - Line contains `"Üniversitem:"` or `"My University:"` → text after `:`, or next line if empty
   - Else `UNIVERSITY_KEYWORDS.search(text)` where pattern is:

     ```
     (Üniversitesi|Universitesi|Üni|uni\b)   [re.IGNORECASE]
     ```

     - Take up to last 4 words before keyword match; if empty, join lines `[i-1:i+2]` around matching line
   - Run `match_university(candidate, ...)` if candidate non-empty and confidence != NONE
2. Else `scan_entities_by_ngram(content, all_unis, all_aliases)`

If `_route_university_match` returns True → **(a)** (see §4.1 routing table below)

#### Step E — Default: ask university

`update_conversation_state(cid, "awaiting_university", ...)` + send canned `hangi` (`CANNED_HANGI`) → **(a)**

#### `_route_university_match` outcomes (used in Steps D and elsewhere)

| `MatchResult.confidence` | Action | Fate |
|--------------------------|--------|------|
| `NONE` | return False | (caller continues) |
| `AMBIGUOUS` | state → `awaiting_university_clarification`, send `clarify_uni` (`CANNED_CLARIFY`) | **(a)** |
| `parent_university_id` set | `_handle_parent_match` | **(a)** campus question or single-campus → gender |
| `university_id` set | `_handle_post_match` | **(a)** state → `awaiting_gender`, send `kiz-erkek` |

**`_handle_parent_match` failures → (c):** no campus rows; failed to build campus question.

---

### 4.2 `awaiting_university`

**Handler:** `_handle_awaiting_university`

#### Path 1 — `match_university` succeeds (not NONE)

→ `_route_university_match` — same as §4.1 table → **(a)**

#### Path 2 — `match_university` returns NONE

1. `match_out_of_city(content, all_ooc)` — if match → **(a)** `_fire_out_of_city` (canned `istanbul`, `completed`)

2. `classify_university_reply(content, all_unis)`:
   - `NOT_AN_ANSWER` → **(c)** `internal_class="off_script_no_answer"`
   - `ANSWER_ATTEMPT` → `_handle_university_no_match`:

#### `_handle_university_no_match` (answer attempt, no Istanbul/ooc match)

| `clarification_attempt` | Action | Fate |
|-------------------------|--------|------|
| `>= 1` | `_escalate_human_needed` (FallBack stub message) | **(c)** silent |
| `0` | Send `clarify_uni_name` (`CANNED_CLARIFY_UNI_NAME`), increment `clarification_attempt` | **(a)** clarify |
| After clarify, if `word_count_after_normalize(content) > 2` | Also state → `awaiting_university_clarification` | **(a)** |
| After clarify, if `<= 2` words | Stay `awaiting_university` | **(a)** |

**Classifier not invoked** when Istanbul match or out-of-city match succeeds first.

---

### 4.3 `awaiting_university_clarification`

**Handler:** `_handle_clarification`  
**Classifier:** **Not invoked**

| Condition | Action | Fate |
|-----------|--------|------|
| `match_university` → `NONE` or `AMBIGUOUS` | Try `match_out_of_city`; if ooc → `_fire_out_of_city` | **(a)** if ooc |
| Still no Istanbul match | `_escalate_human_needed` (FallBack stub) | **(c)** silent — **first failure** (no second clarify) |
| `parent_university_id` | `_handle_parent_match` | **(a)** |
| `university_id` | `_handle_post_match` | **(a)** |

---

### 4.4 `awaiting_campus_clarification`

**Handler:** `_handle_awaiting_campus_clarification`  
**Classifier:** **Not invoked**

**Requires:** `conversation.pending_parent_university_id` set.

**Campus match logic** (exact normalized equality only — no Levenshtein):

- Load campuses: `queries.get_campuses_for_parent(parent_id)` → `university_parent_map` + related rows
- Load aliases: `queries.get_all_university_aliases()`
- `normalized_reply = normalize(content)`
- Match if:
  - `normalize(campus.campus_label) == normalized_reply`, OR
  - any alias where `alias.university_id == campus.university_id` and `normalize(alias.alias) == normalized_reply`

| Condition | Action | Fate |
|-----------|--------|------|
| No `pending_parent_university_id` | `_escalate_human_needed`, `internal_class="missing_pending_parent"` | **(c)** |
| No campus rows for parent | `_escalate_human_needed` | **(c)** |
| Campus matched | clear pending parent, reset clarification, `_handle_post_match` | **(a)** → gender ask |
| No campus match, `clarification_attempt >= 1` | `_escalate_human_needed` | **(c)** silent |
| No campus match, `clarification_attempt == 0` | increment attempt, send `clarify_campus_name` (`CANNED_CLARIFY_CAMPUS_NAME`) | **(a)** |

---

### 4.5 `awaiting_gender`

**Handler:** `_handle_awaiting_gender`  
**Classifier:** **Not invoked** (gender regex only)

| Condition | Action | Fate |
|-----------|--------|------|
| `GENDER_FEMALE.search(content)` | set gender female, verify DB attrs | **(a)** → `recengine_running`, fire RecEngine |
| `GENDER_MALE.search(content)` | set gender male, verify DB attrs | **(a)** → `recengine_running` |
| Neither regex matches | `_escalate_human_needed`, `internal_class="off_script_no_answer"` | **(c)** silent |
| Gender set but `university_id` or `gender` missing on re-read | `_escalate_human_needed`, `internal_class="attr_write_failed"`, `status_code="500"` | **(c)** |

---

### 4.6 `recengine_running`

| Condition | Action | Fate |
|-----------|--------|------|
| Any inbound text | Log info, return | **(b)** ignore (wait for callback / ladder) |

---

### 4.7 `completed`

**Handler:** `_handle_post_completion`

| Condition | Action | Fate |
|-----------|--------|------|
| `match_hotel_by_ngram(content, all_hotels)` matches | `_fire_hotel_path` | **(a)** |
| No hotel name match | `_escalate_human_needed` (post-completion deferred to human) | **(c)** silent |

---

### 4.8 `human_needed`

| Condition | Action | Fate |
|-----------|--------|------|
| Any inbound | Log terminal, return | **(b)** ignore |

---

### 4.9 `stopped`

| Condition | Action | Fate |
|-----------|--------|------|
| Any inbound | Log terminal, return | **(b)** ignore |

*(Human agent outbound sets `stopped` elsewhere in webhook handler, not in these four files.)*

---

## 5. Canned response short codes referenced

| Constant | `short_code` value | Typical trigger |
|----------|-------------------|-----------------|
| `CANNED_HANGI` | `"hangi"` | `_handle_new` default |
| `CANNED_KIZ_ERKEK` | `"kiz-erkek"` | `_handle_post_match` |
| `CANNED_ISTANBUL` | `"istanbul"` | `_fire_out_of_city` |
| `CANNED_CLARIFY` | `"clarify_uni"` | Levenshtein `AMBIGUOUS` |
| `CANNED_CLARIFY_UNI_NAME` | `"clarify_uni_name"` | `_handle_university_no_match` first strike |
| `CANNED_CLARIFY_CAMPUS_NAME` | `"clarify_campus_name"` | campus first strike |

Content loaded from DB table `canned_responses` by `short_code`.

---

## 6. DB-backed lists (not hardcoded in these modules)

| Data | Query function | Table(s) |
|------|----------------|----------|
| Istanbul universities | `queries.get_all_universities()` | `universities` |
| University aliases | `queries.get_all_university_aliases()` | `university_aliases` |
| Out-of-city universities | `queries.get_all_out_of_city_universities()` | `out_of_city_universities` |
| Hotels | `queries.get_all_hotels()` | `hotels` |
| Campus rows | `queries.get_campuses_for_parent(parent_id)` | `university_parent_map` (+ joins) |
| Parent question template | `queries.get_parent_university_by_id(parent_id)` | `parent_universities` |
| Canned message text | `queries.get_canned_response_by_short_code(short_code)` | `canned_responses` |
| Hotel response sequences | `queries.get_canned_responses_for_hotel(hotel_id)` | `response_schemas` → `canned_responses` |

---

## 7. Intent-classifier design notes (derived from code)

1. **Phrase gate `GREETING` ≠ answer classifier** — gate only runs on first inbound in `_handle_new`; classifier only on failed uni match in `awaiting_university`.

2. **Housing/price tokens appear in both phrase gate (accept) and answer classifier off-script markers (reject mid-flow)** — e.g. `"arıyorum"` is in `_REQUEST_VERBS` but `"konaklama"` is in `_HOUSING_WORDS` for first message only.

3. **`_any_keyword_filter` is dead code** relative to `evaluate_phrase_gate` — filters are evaluated in fixed order §1.1, not OR-of-all.

4. **Gender path has no reprompt** — first non-match → immediate **(c)** with `off_script_no_answer`.

5. **`awaiting_university_clarification` has no second-chance clarify** — first miss after ambiguous prompt → **(c)**.
