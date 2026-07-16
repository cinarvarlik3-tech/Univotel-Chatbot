# Spec 023 — TagAssigner University Matching, `hizmet-veremiyoruz`, Gender Prompt, Observability

**Status:** Build-ready. Hand to Claude Code (Cursor). Depends on Spec 018 (attribute merge pipeline) and Spec 021 (sweeps / manual `tag`). Independent of Spec 022.

**Goal:** Fix university attribute write failures caused by Gemini emitting non-canonical Chatwoot list strings; add out-of-İstanbul labeling via `hizmet-veremiyoruz`; harden gender attribute extraction in the prompt; add merge-outcome logging so attribute write skips are observable.

**Governing principles (do not violate):**
- **Gemini proposes, Router validates.** The LLM never writes to DB or Chatwoot directly. All attribute acceptance still flows through `merge_attributes()` and existing gates (`human_set`, add-if-missing for `oda_tiipi`, etc.).
- **Do not import InfoGatherer's full fuzzy stack into TagAssigner.** University resolution gets a narrow fallback (normalized exact + Levenshtein distance 1 with unique-match guard), not `match_university()` tiers.
- **Out-of-İstanbul universities are absent from `university_chatwoot_label_map` by design** (unservable). They must not be written as a university FK. Label `hizmet-veremiyoruz` instead.
- **Gender write path is healthy.** Root cause confirmed: Gemini omits `ogrenci_cinsiyet` from its snapshot. Fix is prompt-only; do not change merger/resolver code for gender unless a separate sync-gap issue is explicitly scoped.

---

## 0. Root causes (locked — source of truth)

Validated during live testing (2026-07-11):

| Symptom | Root cause | Evidence |
|---|---|---|
| University attribute not written despite chat naming a university | Gemini outputs a freeform string; Router does exact-only `WHERE chatwoot_list_value = $1` against `university_chatwoot_label_map` | `info_check_fingerprint = university::…:validation_failed` on Marmara/Beykent-style runs; map has campus-specific strings only |
| `hizmet-veremiyoruz` never applied | Label not in `LIST_1_USABLE`; no prompt rule; TagAssigner has no out-of-city awareness | Label exists in Chatwoot only; not in codebase |
| Gender attribute not written on some runs | Gemini echoes `bilinmiyor` despite terse gender answers in transcript | Conv 1134 manual `tag`: when Gemini output `Erkek`, DB + Chatwoot both wrote (`gender_set_by=tagAssigner`, `POST …/custom_attributes` 200). Pipeline works when Gemini proposes the value. |

**Secondary issue (out of scope for this spec):** DB may hold `gender` while Chatwoot attribute remains unset (e.g. InfoGatherer `set_conversation_gender()` without Chatwoot write). Merger then sees no diff and skips the Chatwoot patch. Track separately; do not fix here.

---

## 1. Work items

| ID | Change | Type | Risk |
|---|---|---|---|
| A | Feed Gemini the Chatwoot university list + typo instruction | Addition | Medium |
| B | Router: normalized-exact + Levenshtein=1 unique-match fallback | Bugfix | Medium |
| C | `hizmet-veremiyoruz` label: prompt rule + resolver allowlist | Addition | Medium |
| D | Gender: prompt hardening for terse answers | Bugfix | Low |
| E | Merge-outcome logging | Observability | Low |
| F | Tests for A–E | Tests | Low |

**Build order:** B → A → C → D → E (resolver first so prompt list has a backstop; gender/logging last).

**No migration required** for any part.

---

# PART A — Give Gemini the Chatwoot university list

## A.1 Problem

`system_prompts/tagassigner_prompt.md` instructs Gemini to use "exact Chatwoot list strings" but does **not** provide the list. Gemini paraphrases from chat text (`Beykent Üniversitesi Ayazağa kampüs` vs canonical `Beykent Üniversitesi - Ayazağa`). Router exact lookup fails → `validation_failed` → no university write.

## A.2 Design

Inject the list **dynamically from DB** at call time (not hardcoded into the static `.md` file) so it stays in sync with `university_chatwoot_label_map`. ~93 entries, avg ~27 chars (~2.5 KB) — negligible token cost.

**Builder stays pure:** `payload_builder` receives pre-fetched data as parameters (same pattern as `university_display`). Router fetches; builder renders.

## A.3 New query — `app/db/queries.py`

```python
async def get_all_university_chatwoot_list_values() -> list[str]:
    """All canonical Chatwoot university list strings, sorted."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT chatwoot_list_value FROM university_chatwoot_label_map ORDER BY chatwoot_list_value"
    )
    return [r["chatwoot_list_value"] for r in rows]
```

Also add (shared with Part B):

```python
async def get_university_chatwoot_label_map() -> list[tuple[uuid.UUID, str]]:
    """(university_id, chatwoot_list_value) pairs for Router resolution."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT university_id, chatwoot_list_value FROM university_chatwoot_label_map"
    )
    return [(r["university_id"], r["chatwoot_list_value"]) for r in rows]
```

## A.4 Payload builder — `app/tagassigner/payload_builder.py`

- Add parameter `university_list_values: list[str]` to `build_payload()` and `build_batch_request()`.
- In `_build_context()`, append a new section after bot-writable attributes:

```
### Geçerli üniversite listesi (yalnızca bu değerlerden birini kullan)
<one line per value, exact string>
```

## A.5 Router wiring — `app/tagassigner/router.py`

In `run_tagging()` (and batch path via `build_batch_request` caller):
1. `list_values = await queries.get_all_university_chatwoot_list_values()`
2. Pass into `build_payload(conv, messages, current_labels_clean, university_display, university_list_values=list_values)`

## A.6 Prompt update — `system_prompts/tagassigner_prompt.md`

Update **Attribute rules → university**:

1. Choose exactly one value from the provided university list, matching **verbatim**.
2. Correct typos, spacing, campus phrasing, and Turkish diacritics to the closest listed value.
3. If chat mentions multiple universities, echo current unchanged.
4. If no listed value clearly matches (including ambiguous campus), output `bilinmiyor`.
5. **Never invent a string not in the list.**

Campus disambiguation: when chat names a parent brand without a clear campus (e.g. "Marmara Üniversitesi" with five campus rows), output `bilinmiyor` rather than guess.

---

# PART B — Router normalized-exact + Levenshtein=1 fallback

## B.1 Problem

Even with the list in context, Gemini may be one character off (hyphen, accent, spacing). Exact SQL lookup still fails.

## B.2 Design

Add a **new dedicated resolver** for TagAssigner only. Do **not** change `get_university_id_for_chatwoot_list_value()` — human webhook path and other callers keep exact-only behavior.

**Resolution order:**
1. **Exact** match on raw proposed string.
2. **Normalized-exact:** apply `normalize()` from `app/layers/matching.py` to both sides; compare.
3. **Levenshtein distance == 1** on normalized strings against all map values — accept **only if exactly one** candidate qualifies.
4. Else → unresolved (`university_id = None` → existing `validation_failed` / `info-check` path).

Reuse `normalize` and `levenshtein_distance` from `app/layers/matching.py`. One-directional import from layers into tagassigner is acceptable; document in module header.

## B.3 New module — `app/tagassigner/university_resolver.py`

```python
"""
TagAssigner university list-value resolution.

Resolves Gemini's proposed university string to a university_id via
university_chatwoot_label_map. Used only by the Router — not by webhooks
or InfoGatherer.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Optional

from app.layers.matching import levenshtein_distance, normalize


@dataclass
class UniversityResolveResult:
    university_id: Optional[uuid.UUID]
    matched_list_value: Optional[str]
    method: str  # exact | normalized | levenshtein | none | ambiguous


def resolve_university_list_value(
    proposed: str,
    label_map: list[tuple[uuid.UUID, str]],
) -> UniversityResolveResult:
    """
    Resolve proposed Chatwoot list string to university_id.
    Returns method='ambiguous' when LD1 matches more than one row.
    """
    ...
```

**Guardrails:**
- Uniqueness required at LD=1. Two candidates at distance 1 → `ambiguous`, treat as unresolved.
- Do not apply LD fallback when proposed is a sentinel (`bilinmiyor`, `boş`, empty).

## B.4 Router wiring — `app/tagassigner/router.py`

Replace (~line 156):

```python
resolved_uni_id = await queries.get_university_id_for_chatwoot_list_value(proposed_uni.strip())
```

With:

```python
label_map = await queries.get_university_chatwoot_label_map()
resolve_result = resolve_university_list_value(proposed_uni, label_map)
resolved_uni_id = resolve_result.university_id
# Optional: log resolve_result.method at DEBUG
```

Downstream `merge_attributes()` and `info_check` behavior unchanged when `resolved_uni_id` is None.

---

# PART C — `hizmet-veremiyoruz` label for out-of-İstanbul universities

## C.1 Problem

Universities outside İstanbul are intentionally absent from `university_chatwoot_label_map`. TagAssigner has no way to label these conversations as unservable. User added `hizmet-veremiyoruz` in Chatwoot.

## C.2 Design decisions

**Prompt-only is insufficient.** Gemini may propose the label, but `resolve_labels()` only adds labels in `LIST_1_USABLE` or `LIST_2_TERMINAL`. Must add to allowlist.

**Out-of-city detection — Option 1 (default for v1):** Do **not** dump all 148 `out_of_city_universities` rows into Gemini context. Instead:

> If the student's university is a real Turkish institution that is **clearly not** in the provided İstanbul university list, add `hizmet-veremiyoruz` and set `university: bilinmiyor`.

**Ordering rule (critical — prevents false positives on typos):**
1. First, try to match a value from the İstanbul list (typo-tolerant per Part A prompt).
2. If Router still cannot resolve and chat **clearly** names a non-İstanbul university → `hizmet-veremiyoruz`.
3. A failed/ambiguous map lookup alone is **not** grounds for `hizmet-veremiyoruz`.

**Option 2 (defer unless Option 1 fails live testing):** Also inject `get_all_out_of_city_universities()` names into context for explicit matching. More tokens; more deterministic. Implement only if Option 1 produces false negatives on known out-of-city chats.

## C.3 Code change — `app/tagassigner/label_resolver.py`

Add `"hizmet-veremiyoruz"` to `LIST_1_USABLE`:

```python
LIST_1_USABLE: frozenset[str] = frozenset([
    ...
    "hizmet-veremiyoruz",
])
```

No mutex group needed — independent state label. Normal List-1 semantics: Gemini must include it in output to add; omission removes it.

## C.4 Prompt update — `system_prompts/tagassigner_prompt.md`

Add to **LIST 1 — Labels you may assign** (new subsection, e.g. **Service area**):

- **`hizmet-veremiyoruz`** — The lead's university is outside Univotel's İstanbul service area. Apply only when chat **clearly** identifies a non-İstanbul Turkish university and no value in the provided İstanbul list applies. Set `university: bilinmiyor` in attributes. Do not apply for typos, ambiguous campus names, or unknown institutions — use `bilinmiyor` / `info-check` path instead.

**No DB migration.** `conversations.labels` is `text[]`; Chatwoot label is free-form.

---

# PART D — Gender prompt hardening

## D.1 Problem (confirmed)

Gender attribute write path works when Gemini proposes the value (conv 1134: `Erkek` → DB `male`, `gender_set_by=tagAssigner`, Chatwoot `custom_attributes` POST 200). Failures occur when Gemini echoes `bilinmiyor` despite terse gender answers in the transcript.

## D.2 Fix — prompt only

Update **Attribute rules → ogrenci_cinsiyet** in `system_prompts/tagassigner_prompt.md`:

1. When current is `bilinmiyor` / `Bilinmiyor` and the transcript contains an **explicit gender answer**, you **must** set `ogrenci_cinsiyet`.
2. A short standalone reply to the bot's gender question counts as explicit:
   - Bot: *"Kız öğrenci için mi… erkek öğrenci mi?"*
   - Lead: `Kız`, `Erkek`, `Kız öğrenci`, `erkek...` → map to `Kız` / `Erkek`.
3. Values: `Erkek`, `Kız`, `Bilinmiyor` only (exact casing).

**Worked examples** (add to prompt):

```
# Context: ogrenci_cinsiyet: bilinmiyor
# Transcript includes: Bot: "Kız öğrenci için mi erkek öğrenci mi?" → Müşteri: "erkek..."
# Correct output: "ogrenci_cinsiyet": "Erkek"
```

**No code changes** in `attribute_merger.py`, `attribute_resolver.py`, or Router for gender.

---

# PART E — Merge-outcome logging

## E.1 Problem

When attributes are not written, there is no log explaining whether `chatwoot_patches` was empty, which fields were blocked, or why. Debugging requires DB inspection of `gemini_result` and `info_check_fingerprint`.

## E.2 Change — `app/tagassigner/router.py`

In `apply_tagassigner_result()`, immediately after `merge_attributes()`:

```python
logger.info(
    "TagAssigner router: merge conversation=%s patches=%s blocked=%s",
    conversation_id,
    list(merge_result.chatwoot_patches.keys()) or "none",
    [(m.field, m.reason) for m in merge_result.blocked_mismatches] or "none",
)
```

Optional DEBUG when skipping Chatwoot attribute write because `not merge_result.chatwoot_patches`.

One INFO line per run. Do not log full attribute values (PII-adjacent).

---

# PART F — Tests

Mirror source structure. Unit tests only for deterministic code; no tests asserting Gemini behavior.

## F.1 `tests/test_university_resolver.py` (new)

| Test name | Behavior |
|---|---|
| `should_match_exact_when_string_is_canonical` | Raw string matches map row |
| `should_match_when_only_diacritics_or_spacing_differ` | Normalized-exact path |
| `should_match_when_single_edit_typo_and_unique` | LD1 with one candidate |
| `should_return_none_when_two_candidates_tie_at_distance_one` | Ambiguity guard |
| `should_return_none_when_no_candidate_within_distance_one` | Unresolved |
| `should_return_none_when_proposed_is_bilinmiyor_sentinel` | No fallback on sentinels |

## F.2 `tests/test_label_resolver.py` (extend)

- `should_allow_hizmet_veremiyoruz_as_assignable_list1_label`
- `should_remove_hizmet_veremiyoruz_when_gemini_omits_it`

## F.3 `tests/test_payload_builder.py` (new or extend)

- `should_include_university_list_values_in_context`
- `should_render_valid_university_list_section_header`

## F.4 Router integration (extend existing sweep/router tests)

- Mock `get_university_chatwoot_label_map` + `resolve_university_list_value`; confirm resolved ID feeds merger.

**Full pytest suite must remain green** (301+ tests at time of writing).

---

## 2. Risk register

| Change | Risk | Mitigation |
|---|---|---|
| A — university list in context | Wrong-campus guess | Prompt: `bilinmiyor` when campus ambiguous |
| B — LD1 fallback | False positive match | Unique-match requirement; normalized comparison |
| C — `hizmet-veremiyoruz` | Label on typo / map miss | Match-İstanbul-first ordering rule |
| D — gender prompt | Over-eager gender on unrelated mentions | Scope to gender-question replies / explicit student descriptor |
| E — logging | Noise | One INFO line per run |

---

## 3. Live validation (post-build)

| Scenario | Conversation | Pass criteria |
|---|---|---|
| Gender terse answer | 1134 (or similar) — `tag` private note | `gemini_result.attributes.ogrenci_cinsiyet` = `Erkek`/`Kız`; `POST …/custom_attributes` in logs; Chatwoot attribute set |
| İstanbul campus typo | Beykent Ayazağa-style chat | `university_id` set; no `validation_failed` fingerprint |
| Out-of-İstanbul | Chat naming e.g. Hacettepe / Trakya | `hizmet-veremiyoruz` label; `university: bilinmiyor`; no university FK |
| Merge logging | Any run | INFO line shows `patches` and `blocked` |

---

## 4. Files touched (summary)

| File | Parts |
|---|---|
| `app/db/queries.py` | A, B |
| `app/tagassigner/university_resolver.py` | B (new) |
| `app/tagassigner/router.py` | A, B, E |
| `app/tagassigner/payload_builder.py` | A |
| `app/tagassigner/label_resolver.py` | C |
| `system_prompts/tagassigner_prompt.md` | A, C, D |
| `tests/test_university_resolver.py` | F (new) |
| `tests/test_label_resolver.py` | F |
| `tests/test_payload_builder.py` | F (new or extend) |

**Explicitly not changed:** `attribute_merger.py`, `get_university_id_for_chatwoot_list_value()` (webhook path), InfoGatherer `matching.py` logic, migrations.

---

## IMPLEMENTATION CHECKLIST

1. Add `get_all_university_chatwoot_list_values()` and `get_university_chatwoot_label_map()` to `app/db/queries.py`.
2. Create `app/tagassigner/university_resolver.py` with `resolve_university_list_value()` (exact → normalized → LD1-unique).
3. Add `tests/test_university_resolver.py` covering exact, normalized, LD1-unique, ambiguous, no-match, and sentinel cases.
4. Wire `resolve_university_list_value()` into `app/tagassigner/router.py`, replacing the direct `get_university_id_for_chatwoot_list_value()` call at university resolution.
5. Add `university_list_values` parameter to `build_payload()` / `build_batch_request()` in `app/tagassigner/payload_builder.py`; render the valid-university-list section.
6. Fetch list values in Router (live + batch paths) and pass into the builder.
7. Update `system_prompts/tagassigner_prompt.md` university rule: verbatim list selection, typo correction, `bilinmiyor` when no clear match.
8. Add `"hizmet-veremiyoruz"` to `LIST_1_USABLE` in `app/tagassigner/label_resolver.py`.
9. Add `hizmet-veremiyoruz` rule to `system_prompts/tagassigner_prompt.md` (Option 1: infer from clearly non-İstanbul university; `university: bilinmiyor`; match-İstanbul-first ordering).
10. Harden `ogrenci_cinsiyet` rule in `system_prompts/tagassigner_prompt.md` with terse-answer handling and worked examples.
11. Add merge-outcome INFO logging in `apply_tagassigner_result()` (`app/tagassigner/router.py`).
12. Extend `tests/test_label_resolver.py` for `hizmet-veremiyoruz` add/remove semantics.
13. Add/extend `tests/test_payload_builder.py` for university-list inclusion.
14. Run full `pytest`; confirm suite green.
15. Live-validate per §3 (gender on 1134, Beykent-style university, out-of-İstanbul label, merge logs).

---

## 5. Deferred (explicitly out of scope)

- **Option 2 out-of-city list injection** into Gemini context — implement only if Option 1 fails live validation.
- **DB→Chatwoot gender sync gap** (Hypothesis B: DB has gender, Chatwoot doesn't, merger no-diff) — separate spec if needed.
- **Importing full `match_university()` into TagAssigner** — not required; LD1 unique-match is sufficient safety net.
- **Map completeness audit** — universities missing from `university_chatwoot_label_map` entirely (e.g. Kahramanmaraş) cannot be fixed by matching logic; data/ops task.
