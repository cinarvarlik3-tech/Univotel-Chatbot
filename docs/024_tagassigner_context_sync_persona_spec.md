# Spec 024 — TagAssigner Full-Context Backfill, DB↔Chatwoot Attribute Sync, Persona & University Prompt Hardening

**Status:** Draft for review. Follows Spec 023 (university matching, `hizmet-veremiyoruz`, gender prompt, merge logging). Depends on Spec 018 (attribute merge pipeline) and Spec 021 (sweeps / manual `tag`).

**Origin:** Sweep-10 live test (2026-07-12). Data-backed post-mortem cross-referenced the chatbot `messages` table against the CRM `lead_messages` table (Çınar Varlık org). Findings drove this spec.

**Governing principles (unchanged from prior specs):**
- **Gemini proposes, Router validates.** The LLM never writes DB or Chatwoot directly.
- **`set_by='human'` is sacred.** No automated path overwrites a human-set attribute.
- **Add-only labels stay add-only.** `deal_awaiting`, `kapora-alindi`, terminals unchanged.
- **No new tagging pipeline.** All changes layer onto the existing Router → merge → write path.

---

## 0. Root causes (locked — from Sweep-10 data)

Cross-DB message-count reconciliation (chatbot `messages` vs CRM `lead_messages`, non-private):

| Lead | cwid | Msgs TagAssigner saw | True non-private | Coverage |
|---|---|---|---|---|
| Musa | 1142 | 1 | 2 | 50% |
| Taha | 1141 | 1 | 2 | 50% |
| Eray | 1130 | 3 | 6 | 50% |
| Bülent Öztürk | 1134 | 14 | 13 | full (replayed) |
| Sevcan | 1118 | 5 | 11 | 45% |
| Deniz | 1140 | 2 | 4 | 50% |
| 🐞 | 1132 | 1 | 8 | 13% |
| Handan Ayan | 1137 | 2 | 14 | 14% |
| . | 1139 | 2 | 3 | 67% |
| ✨ | 1135 | 1 | 3 | 33% |
| **Total** | | **32** | **66** | **~48%** |

| # | Root cause | Evidence | Fix |
|---|---|---|---|
| 1 | **Context truncation.** TagAssigner reads only the local webhook-fed `messages` table; it holds ~48% of the true transcript. | 32 vs 66 messages. Sevcan/Handan/✨/🐞 missed attributes stated in un-ingested messages. | Part A |
| 2 | **DB↔Chatwoot attribute sync gap.** `merge_attributes` diffs Gemini's proposal against **DB** fields, not Chatwoot's actual `custom_attributes`. DB-set-but-Chatwoot-empty → no diff → never repaired. | 1139 `university_id` set in DB, absent in Chatwoot; 1132 `gender=female` in DB, absent in Chatwoot. | Part B |
| 3 | **University from district name.** Gemini derived `Arel Üniversitesi - Cevizlibağ` from "cevizlibağ tarafında var mı". The hallucinated string was a valid canonical map value → passed resolution → wrong FK written. | 1134 `gemini_result.university = "Arel Üniversitesi - Cevizlibağ"`. | Part C |
| 4 | **Persona over-inference.** (a) Auto-filled widget intro is first-person and identical for all leads → read as student self-statement. (b) First-person accommodation search treated as student even for parents. | 1141/1140/1134 `ogrenci` added on thin/templated evidence. | Part D |
| 5 | **Stale `info_check_fingerprint`.** Fingerprint not cleared when a later run resolves the university or drops the conflict. | 1130 (`Marmara…validation_failed`) and 1141 (`Kahramanmaraş…validation_failed`) still carried July-11 fingerprints after July-12 resolved/cleared. | Part E |

**Sequencing:** Part A gates everything — no valid accuracy measurement is possible until TagAssigner sees the full transcript. Build order: **A → B → C → D → E**, tests alongside. Retest (§7) only after A + B land.

---

## 1. Existing mechanisms (context for the implementer)

**Message ingestion (webhook-only, idempotent):**
```601:623:app/db/queries.py
async def insert_message(
    ...
        INSERT INTO messages
            (conversation_id, chatwoot_message_id, content, message_type,
             sender_type, sender_id, sender_name, is_private, sent_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (chatwoot_message_id) DO NOTHING
```
`ON CONFLICT DO NOTHING` on `chatwoot_message_id` makes re-insertion safe — the backfill can call it freely.

**Transcript read (local table only):**
```638:650:app/db/queries.py
async def get_messages_for_conversation(
    conversation_id: uuid.UUID,
    since: Optional[datetime] = None,
) -> list[Message]:
    ...
            SELECT * FROM messages
            WHERE conversation_id = $1 AND created_at > $2 AND is_private = false
            ORDER BY created_at
```

**Router path (where the transcript is built):**
```90:99:app/tagassigner/router.py
    if read_full_history:
        messages = await queries.get_messages_for_conversation(conversation_id)
    else:
        last_run = await _get_last_successful_run(conversation_id)
        since = last_run.completed_at if last_run else None
        messages = await queries.get_messages_for_conversation(conversation_id, since=since)
```
`read_full_history` is `True` for `manual`, `scheduled`, and `sweep` triggers (set in `queue.py`).

**Merge diffs against DB, not Chatwoot:**
```89:90:app/tagassigner/attribute_merger.py
    if not values_differ(current_display, proposed_raw):
        return
```
`current_display` for university comes from `_university_display_for_conv(conv)` (derived from `conv.university_id`); gender from `gender_enum_to_display(conv.gender)`. Neither reflects Chatwoot's live `custom_attributes`.

**Chatwoot client (already available):** `fetch_conversation()` returns the conversation JSON including `custom_attributes` (see `app/webhooks/chatwoot.py:628` reading `conv_data.get("custom_attributes")`); `set_custom_attributes()` writes multiple keys in one POST. **No** "list messages" function exists yet — Part A adds one.

**InfoGatherer already writes attributes at flow completion** (`attribute_resolver.write_attributes_at_flow_completion`) with `set_by=infoGatherer`, but only on that path; conversations that never complete the InfoGatherer flow (or complete before a Chatwoot write) leave the sync gap that Part B repairs.

---

# PART A — Full-context backfill from Chatwoot

## A.1 Goal

Before any full-history TagAssigner run, ensure the local `messages` table holds the complete non-private transcript by pulling it from Chatwoot's messages API and upserting it. Idempotent, safe to run every time.

## A.2 New Chatwoot client function — `app/chatwoot_client.py`

```python
async def fetch_all_messages(chatwoot_conversation_id: int) -> Optional[list[dict]]:
    """
    Fetch the full message history for a conversation, paging backward.

    Chatwoot returns newest-last pages of ~20; page backward with the `before`
    query param (smallest message id seen) until a page returns no new messages.
    Returns the raw message dicts (oldest-first), or None on hard failure.
    """
```

**Endpoint:** `GET {BASE}/api/v1/accounts/{ACCOUNT}/conversations/{id}/messages`
**Pagination:** pass `?before=<lowest_message_id_seen>` to walk backward; stop when a page is empty or the lowest id stops decreasing. Cap at a sane page limit (e.g. 25 pages / 500 messages) to avoid runaway loops; log a warning if the cap is hit.

**Return shape:** each dict carries `id`, `content`, `message_type` (int), `private` (bool), `created_at` (epoch seconds), `sender`.

## A.3 Chatwoot `message_type` → local mapping

| Chatwoot `message_type` | Meaning | Local `message_type` | Ingest? |
|---|---|---|---|
| 0 | incoming (lead) | `inbound` | yes |
| 1 | outgoing (agent/bot) | `outbound` | yes |
| 2 | activity (system events) | — | **skip** |
| 3 | template | `outbound` | yes |

Skip any message with `private == true` (private notes). This mirrors the existing webhook logic and keeps the transcript lead-facing only.

## A.4 New backfill function — `app/tagassigner/context_backfill.py` (new module)

```python
"""
TagAssigner full-context backfill.

Pulls the complete Chatwoot transcript and upserts it into the local messages
table before a full-history run, so the Router never tags on partial context.
Idempotent: insert_message uses ON CONFLICT (chatwoot_message_id) DO NOTHING.
"""

async def backfill_conversation_messages(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
) -> int:
    """
    Fetch all Chatwoot messages and upsert missing ones into `messages`.
    Returns the number of newly inserted rows (0 if already complete).
    Best-effort: logs and returns 0 on Chatwoot fetch failure (never blocks a run).
    """
```

**Behavior:**
1. `raw = await fetch_all_messages(chatwoot_conversation_id)`; if `None`, log a warning and return `0` (do not abort the run — degrade to whatever is local).
2. For each non-skipped message, call `queries.insert_message(...)` with:
   - `chatwoot_message_id = raw["id"]`
   - `content = raw["content"]`
   - `message_type` per A.3 mapping
   - `sender_type` / `sender_id` / `sender_name` from `raw["sender"]` (best-effort; `None` allowed)
   - `is_private = False`
   - `sent_at = datetime.fromtimestamp(raw["created_at"], tz=utc)` — **authoritative send time from Chatwoot.**
3. Count and return inserts.

**`created_at` subtlety (must not break incremental runs):** the local `messages.created_at` records persist-time and is used by the `since` filter for **message-triggered incremental** runs. Backfill inserts old messages with a *new* `created_at`, which is harmless for full-history runs (they ignore `since`) but could momentarily inflate an incremental window. **Mitigation:** backfill is invoked **only on full-history runs** (`manual`/`scheduled`/`sweep`), never on `message`-triggered runs. Incremental runs already have complete recent context from live webhooks. Document this constraint in the module header.

## A.5 Router wiring — `app/tagassigner/router.py`

In `run_tagging()`, immediately before the transcript read, when `read_full_history` is true:

```python
if read_full_history:
    inserted = await backfill_conversation_messages(conversation_id, conv.chatwoot_conversation_id)
    logger.info(
        "TagAssigner router: context backfill conversation=%s inserted=%d",
        conversation_id, inserted,
    )
    messages = await queries.get_messages_for_conversation(conversation_id)
else:
    ...
```

## A.6 Coverage guard (observability, not a hard gate)

After backfill, log a coverage line so partial-context runs are visible:

```python
logger.info(
    "TagAssigner router: transcript coverage conversation=%s local_msgs=%d",
    conversation_id, len(messages),
)
```

**Non-goal:** do not block a run on low coverage. If Chatwoot is unreachable, tagging on local context is still better than skipping. The guard is diagnostic.

## A.7 Alternative considered (rejected for v1)

Reading `lead_messages` from the CRM DB would also yield full history, but couples TagAssigner to a second database and depends on the CRM "Conversation tab opened" sync trigger. Chatwoot is the authoritative source and already the system's write target. **Use Chatwoot.**

---

# PART B — DB↔Chatwoot attribute sync repair

## B.1 Goal

TagAssigner must **reconcile Chatwoot to the intended attribute state**, not merely diff against the DB. When the DB (or a just-accepted Gemini proposal) holds a value that Chatwoot is missing, push it — without ever overwriting a human-set Chatwoot value.

## B.2 Read live Chatwoot attributes at run start

In `apply_tagassigner_result()`, fetch the current Chatwoot custom attributes once:

```python
fetch = await fetch_conversation(conv.chatwoot_conversation_id)
chatwoot_attrs = (fetch.data.get("custom_attributes") or {}) if fetch.ok else {}
```

Pass `chatwoot_attrs` into the merge/reconciliation step. On fetch failure, fall back to current behavior (DB-relative diff) and log — never abort.

## B.3 Reconciliation pass (new, additive to `merge_attributes`)

Keep `merge_attributes` as-is for the Gemini-proposal path (Parts of Spec 018/023 unchanged). Add a **reconciliation step** after it, computing the *desired* Chatwoot value for each bot-writable key and emitting a patch when Chatwoot differs:

For each of `university`, `ogrenci_cinsiyet`, `oda_tiipi`:
1. **Desired value** = the post-merge DB value rendered as its Chatwoot list string
   (university → `get_chatwoot_list_value_for_university(university_id)`; gender → `gender_enum_to_display`; room → `oda_tiipi`).
2. **Chatwoot current** = `chatwoot_attrs.get(key)`.
3. **Emit a patch** iff *all* hold:
   - desired is a real value (not `bilinmiyor` / `boş` / `None`), **and**
   - `values_differ(chatwoot_current, desired)` is true, **and**
   - the field is **not** human-set with a *conflicting* Chatwoot value (i.e. respect `*_set_by == 'human'`; if Chatwoot already shows the human value, no patch).

**Precedence:** a Gemini-accepted change (existing `chatwoot_patches`) already covers the "value changed" case. Reconciliation covers the **"value unchanged but Chatwoot empty/stale"** case. Merge the two patch sets; the reconciliation value equals the desired DB value, so there is no conflict between them.

## B.4 Human-safety invariant

Reconciliation **never** overwrites a Chatwoot attribute that a human set to a different value. Concretely: if `conv.<field>_set_by == 'human'`, the DB already holds the human value (webhook path writes it), so desired == human value and any push is a no-op or a re-assertion of the human's own value. Do not push a bot value over a differing human Chatwoot value. Add an explicit guard + test.

## B.5 Logging

Extend the Spec 023 merge log to distinguish reconciliation patches:

```python
logger.info(
    "TagAssigner router: merge conversation=%s gemini_patches=%s recon_patches=%s blocked=%s",
    conversation_id, gemini_keys or "none", recon_keys or "none", blocked or "none",
)
```

## B.6 Scope guard

Reconciliation applies **only to the three bot-writable keys** (`university`, `ogrenci_cinsiyet`, `oda_tiipi`). It never touches `ilgili_otel`, `tasinma_tarihi`, `kayip_nedeni`, `butce` (human/CRM-owned).

---

# PART C — University matching: district / neighborhood guard (prompt)

## C.1 Problem

Gemini mapped a district mention ("cevizlibağ tarafında var mı") to `Arel Üniversitesi - Cevizlibağ`. Because that campus string is canonical, it resolved cleanly and wrote a wrong FK. Matching logic (Spec 023) cannot catch this — the string is legitimate; the **inference** is wrong. Fix is prompt-side.

## C.2 Prompt rule — `system_prompts/tagassigner_prompt.md` (Attribute rules → university)

Add, as an explicit sub-rule under `university`:

> **District, neighborhood, area, or landmark names are NOT university statements.** Names like *Cevizlibağ, Kadıköy, Avcılar, Beşiktaş, Mecidiyeköy* refer to locations the lead is asking about — never infer a `university` value from them, even when a campus in the list contains that place name. Set `university` **only** when the lead names the institution itself (e.g. "Marmara'da okuyorum", "Beykent Ayazağa kampüsü"). If the lead only mentions a district/area, leave `university` as its current value (echo, usually `bilinmiyor`).

**Worked example (add to prompt):**
```
# Lead: "cevizlibağ tarafında yeriniz var mı?"
# Correct: "university": "bilinmiyor"   (district ≠ university)
# WRONG:   "university": "Arel Üniversitesi - Cevizlibağ"
```

## C.3 No code change

The guard is purely instructional. The Spec 023 resolver still handles legitimate institution mentions. No migration, no resolver change.

---

# PART D — Persona hardening (prompt)

## D.1 Problem

Two persona over-inferences:
- **(a) Widget template.** The auto-filled widget intro *"Merhabalar, bana en yakın Univotel'i öğrenmek istiyorum. Üniversitem: <X>"* is identical for every lead and first-person. Gemini reads it as a student self-statement → adds `ogrenci`.
- **(b) First-person = student.** A parent may also say *"1 kişilik yurt odası arıyorum"*. First-person accommodation search is not proof the texter is the student.

## D.2 Prompt rules — `system_prompts/tagassigner_prompt.md` (Lead identity section)

Add a **Persona evidence discipline** block:

> **Ignore the widget intro template for persona.** The opening message *"…bana en yakın Univotel'i öğrenmek istiyorum. Üniversitem: …"* (and close variants) is an auto-generated widget prefill, identical for all leads. It is **not** evidence that the texter is the student. You **may** still read the `Üniversitem:` value in it for the `university` attribute, but you must **not** assign `ogrenci` on the basis of this template alone.
>
> **First person is not proof of student identity.** Searching for a room in the first person ("bakıyorum", "arıyorum", "kalacağım") does not by itself make the texter a student — a parent searches the same way. Assign:
> - **`ogrenci`** only when the texter clearly identifies as the person who will stay AND there is evidence beyond the widget template (e.g. "ben okuyorum", "1. sınıfım", "kendim için bakıyorum").
> - **`veli`** when the texter refers to a child/student they are researching for ("oğlum/kızım/öğrencim için").
> - **Neither** when identity is genuinely unclear — do not guess.

**Worked examples (add to prompt):**
```
# Only the widget template is present, nothing else.
#   Correct labels: []  (no ogrenci — template is not persona evidence)
#   May still set: "university": "<the Üniversitem: value if a clear institution>"

# "oğlum için 1 kişilik yurt odası arıyorum"
#   Correct: "veli"     (parent, despite first-person search verb)

# "ben Beykent'te okuyorum, tek kişilik bakıyorum"
#   Correct: "ogrenci"  (explicit self-identification beyond the template)
```

## D.3 No code change

Persona is a Gemini `labels` decision; `label_resolver` already governs `ogrenci`/`veli`/`ogrenci-degil` mutex. No taxonomy change needed — only evidence discipline in the prompt.

---

# PART E — Clear `info_check_fingerprint` on resolve (minor)

## E.1 Problem

`conversations.info_check_fingerprint` persists a stale `…:validation_failed` after a later run resolves the university or drops the conflict. Observed on 1130 and 1141 post-fix.

## E.2 Investigate + fix — `app/tagassigner/info_check.py` / `router.py`

Review `apply_info_check`: when the new run produces **no** blocked mismatches for a field that previously failed (e.g. university now resolves, or Gemini now emits `bilinmiyor` with `hizmet-veremiyoruz`), the decision must set `clear_active` so `update_info_check_state(clear_active=True)` runs. Confirm the clear path fires whenever the current run has an empty `blocked_mismatches` set and the label is no longer present.

Low risk; label removal already works (confirmed on Eray). This is data-hygiene on the stored fingerprint only.

---

# PART F — Tests

Mirror source structure. Unit tests for deterministic logic; mock Chatwoot I/O. No tests asserting Gemini output.

## F.1 `tests/test_context_backfill.py` (new)
- `should_insert_missing_messages_when_local_table_is_partial` (mock `fetch_all_messages` → N msgs; assert `insert_message` called for missing ids)
- `should_skip_private_and_activity_messages`
- `should_map_message_type_incoming_to_inbound_and_outgoing_to_outbound`
- `should_return_zero_when_chatwoot_fetch_fails` (fetch → None)
- `should_be_idempotent_when_all_messages_already_present` (ON CONFLICT → 0 inserts)

## F.2 `tests/test_attribute_merger.py` (extend) — reconciliation
- `should_emit_patch_when_db_has_value_and_chatwoot_is_empty`
- `should_not_emit_patch_when_chatwoot_already_matches_db`
- `should_not_overwrite_human_set_chatwoot_value`
- `should_only_reconcile_bot_writable_keys`

## F.3 `tests/test_chatwoot_client.py` (new or extend)
- `should_page_backward_until_no_new_messages` (mock paged HTTP)
- `should_stop_at_page_cap` (runaway guard)

## F.4 Router integration (extend existing)
- Mock `fetch_all_messages` + `fetch_conversation`; assert backfill runs before transcript read on full-history triggers, and NOT on `message` triggers.

**Full suite must stay green** (313 tests at Spec 023 close).

---

## 2. Files touched (summary)

| File | Part |
|---|---|
| `app/chatwoot_client.py` | A (`fetch_all_messages`) |
| `app/tagassigner/context_backfill.py` | A (new) |
| `app/tagassigner/router.py` | A, B, E |
| `app/tagassigner/attribute_merger.py` | B (reconciliation pass) |
| `app/tagassigner/info_check.py` | E |
| `system_prompts/tagassigner_prompt.md` | C, D |
| `tests/test_context_backfill.py` | F (new) |
| `tests/test_attribute_merger.py` | F |
| `tests/test_chatwoot_client.py` | F (new/extend) |

**Explicitly NOT changed:** `label_resolver.py` taxonomy, `get_university_id_for_chatwoot_list_value()` (webhook path), Spec 023 `university_resolver.py`, migrations. No DB migration in this spec.

---

## 3. Risk register

| Change | Risk | Mitigation |
|---|---|---|
| A — backfill | Chatwoot API load / slow runs | Page cap; best-effort (never blocks); full-history triggers only (not per-message) |
| A — `created_at` on backfilled rows | Skews incremental `since` window | Backfill only on full-history runs; incremental untouched |
| B — reconciliation | Overwriting human Chatwoot edits | `set_by='human'` guard + explicit test; bot-writable keys only |
| B — extra `fetch_conversation` per run | +1 API call | One call per run; acceptable at sweep volume; fall back to DB-diff on failure |
| C — district guard | Gemini over-corrects, misses real campus mentions | Rule scoped to district/area names only; institution mentions still assigned |
| D — persona discipline | Under-labeling `ogrenci` | Explicit positive examples; `veli`/neither only when evidence supports |

---

## 4. Retest protocol (after A + B land)

1. Restart uvicorn with the new build; keep `OUTBOUND_BLOCK=true`.
2. Optionally raise `LIVE_TESTING_LIMIT` for broader inbound coverage over time (not required for re-sweeping existing convos).
3. `./scripts/tag sweep --10` (or the current cohort size).
4. Confirm from logs, per conversation:
   - `context backfill … inserted=N` and `transcript coverage … local_msgs=M` (M should now ≈ CRM non-private count).
   - `merge … gemini_patches=… recon_patches=… blocked=…`.
5. Re-score against transcripts using the §5 rubric, **excluding** conversations still lacking signal. Coverage should be ≥95% before trusting any accuracy number.
6. Verify specific cases:
   - **1134 (Bülent):** university no longer forced to `Arel … Cevizlibağ`; district guard holds.
   - **1139 (.) / 1132 (🐞):** Chatwoot now shows the DB-known university/gender (reconciliation).
   - **1141 (Taha) / 1140 (Deniz):** `ogrenci` not applied on widget/thin evidence.
   - **1130 (Eray) / 1141:** stale `info_check_fingerprint` cleared.

---

## 5. Scoring rubric (unchanged intent, coverage-gated)

Score per conversation against the **full** transcript. Denominator excludes conversations with no university/gender/persona signal.

| Signal | Pass | Fail |
|---|---|---|
| University | Canonical value written or already correct; no `validation_failed`; district not mistaken for campus | Wrong campus, freeform, or missed despite clear mention |
| Gender | Terse/explicit answer → `Erkek`/`Kız` written or reconciled into Chatwoot | `bilinmiyor` despite clear answer, or DB-set value absent from Chatwoot |
| Persona | `ogrenci`/`veli` only on real evidence; neither when unclear | Persona from widget template or bare first-person |
| Out-of-city | `hizmet-veremiyoruz` + `university: bilinmiyor` | Missing or misapplied |

---

## IMPLEMENTATION CHECKLIST

1. Add `fetch_all_messages()` to `app/chatwoot_client.py` (backward pagination, page cap, message dicts).
2. Create `app/tagassigner/context_backfill.py` with `backfill_conversation_messages()` (map types per A.3, skip private/activity, `sent_at` from Chatwoot, best-effort).
3. Wire backfill into `run_tagging()` before the transcript read, full-history triggers only; add backfill + coverage log lines.
4. Add `tests/test_context_backfill.py` and message-pagination tests in `tests/test_chatwoot_client.py`.
5. In `apply_tagassigner_result()`, fetch live Chatwoot `custom_attributes` via `fetch_conversation()`; fall back to DB-diff on failure.
6. Add reconciliation pass (Part B.3) emitting patches for bot-writable keys when Chatwoot differs from desired DB value; enforce human-safety guard (B.4).
7. Extend merge log to `gemini_patches` / `recon_patches` / `blocked`.
8. Extend `tests/test_attribute_merger.py` for reconciliation + human-safety.
9. Add district/neighborhood guard rule + worked example to `system_prompts/tagassigner_prompt.md` (university).
10. Add persona-evidence discipline (widget exclusion, first-person≠student) + worked examples to `system_prompts/tagassigner_prompt.md` (lead identity).
11. Fix `info_check` clear-on-resolve (Part E); confirm `clear_active` fires when blocked set is empty and label absent.
12. Run full `pytest`; confirm green.
13. Retest per §4; verify coverage ≥95% and the six named cases.

---

## 6. Deferred / out of scope

- **Raising `LIVE_TESTING_LIMIT`** — a config change, not code; do it independently when broader inbound coverage is wanted.
- **Backfilling `created_at` from Chatwoot for incremental correctness** — only needed if backfill is ever extended to `message`-triggered runs; not required now.
- **Map-completeness audit** — universities absent from `university_chatwoot_label_map` (e.g. Kahramanmaraş) are a data/ops task, not fixable by matching or prompt logic.
- **CRM `lead_messages` as a context source** — rejected in favor of Chatwoot (A.7).
