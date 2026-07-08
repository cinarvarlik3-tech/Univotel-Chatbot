# Implementation Spec — TagAssigner Custom Attributes & `info-check`

**Depends on:** TagAssigner v1 (live path), migration 008 (`conversations` attribute columns), `university_chatwoot_label_map`  
**Target files:** `migrations/017_tagassigner_attributes.sql`, `app/tagassigner/*`, `app/webhooks/chatwoot.py`, `app/db/queries.py`, `app/db/models.py`, `system_prompts/tagassigner_prompt.md`, `README.md`, `tests/`  
**Supersedes:** Attribute sections of `docs/tagassigner-v1-spec.md` §6.9 (deterministic-only writes), draft notes at bottom of `tagassigner_prompt.md` (lines 186+)

---

## Overview

TagAssigner currently writes `university`, `ogrenci_cinsiyet`, and `ilgili_otel` to Chatwoot **deterministically from DB** after every run, with no Gemini input. This spec introduces:

1. **Gemini-proposed attributes** for three bot-writable fields, merged by the Router under hard gates.
2. **`set_by` / `set_at` companions** on bot-writable fields (human-set protection).
3. **Two-way sync** between DB and Chatwoot for bot/human-managed fields.
4. **Router-owned `info-check` label** when chat evidence conflicts with DB/labels and a fix is blocked.
5. **Removal of `ilgili_otel` from the TagAssigner write path** (InfoGatherer-only).

### Canonical data flow

```
DB ──► Router ──► Gemini ──► Router ──► DB ──► Chatwoot
         ▲                              │
         └──────── read payload ────────┘

Human CRM edits (Chatwoot UI):
Chatwoot ──► conversation_updated webhook ──► DB  (when not bot-authored)
```

**DB is always the hub.** Gemini never reads Chatwoot directly and never writes anywhere. The Router is the sole authority on what gets persisted and pushed.

---

## Field ownership

| Field | Chatwoot key | DB column | Primary bot writer | TagAssigner may write? | Human CRM sync |
|-------|--------------|-----------|-------------------|------------------------|----------------|
| University | `university` | `university_id` | InfoGatherer | Yes — mismatch fix or add-if-missing | Yes — reverse-map list string → FK |
| Gender | `ogrenci_cinsiyet` | `gender` | InfoGatherer | Yes — mismatch fix or add-if-missing | Yes — Erkek/Kız/Bilinmiyor ↔ enum |
| Interested hotel | `ilgili_otel` | `ilgili_otel` | InfoGatherer (RecEngine callback) | **No** | Yes (existing webhook) |
| Room type | `oda_tiipi` | `oda_tiipi` | TagAssigner | Yes — explicit chat only, add-if-missing | Yes — with `set_by` |
| Move-in date | `tasinma_tarihi` | `tasinma_tarihi` | Human only | **No** | Yes (existing) |
| Budget | `butce` | `butce` | Human only | **No** | Yes (existing) |
| Loss reason | `kayip_nedeni` | `kayip_nedeni` | Human only | **No** — exclude from Gemini output | Yes (existing) |

### Bot-writable attribute rules (Router-enforced)

| Field | Set when | Do not set when |
|-------|----------|-----------------|
| `university` | Chat states **one** university that contradicts DB, or DB is empty and chat has a single unambiguous university | Multiple universities mentioned; `university_set_by = 'human'`; proposed value fails map lookup |
| `ogrenci_cinsiyet` | Chat **directly contradicts** DB gender, or DB gender empty and chat states student gender explicitly | `gender_set_by = 'human'`; ambiguous / inferred only |
| `oda_tiipi` | Lead **explicitly** stated room type and DB is empty | `oda_tiipi_set_by = 'human'`; inferred/vague preference; value not in allowed list (TBD) |

**Universal rules:**

- **No clearing** — bot never nulls or removes an attribute value.
- **No override of human-set values** — when `*_set_by = 'human'`, Router blocks the write.
- **Router is authority** — Gemini proposes; Router validates, merges, and decides `info-check`.

### Semantic note: student profile

`university` and `ogrenci_cinsiyet` describe the **student** (the person who will stay), not necessarily the texter. When the texter is `veli`, infer the child's university/gender from chat.

---

## Schema — migration 017

**File:** `migrations/017_tagassigner_attributes.sql`

```sql
-- set_by companions for bot-writable fields (mirrors ilgili_otel pattern)
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS university_set_at  timestamptz,
    ADD COLUMN IF NOT EXISTS university_set_by  text
        CHECK (university_set_by IN ('tagAssigner', 'infoGatherer', 'human')),
    ADD COLUMN IF NOT EXISTS gender_set_at      timestamptz,
    ADD COLUMN IF NOT EXISTS gender_set_by      text
        CHECK (gender_set_by IN ('tagAssigner', 'infoGatherer', 'human')),
    ADD COLUMN IF NOT EXISTS oda_tiipi_set_at     timestamptz,
    ADD COLUMN IF NOT EXISTS oda_tiipi_set_by    text
        CHECK (oda_tiipi_set_by IN ('tagAssigner', 'human'));

-- info-check router state (label lives on Chatwoot; fingerprint lives in DB)
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS info_check_fingerprint            text,
    ADD COLUMN IF NOT EXISTS info_check_added_at               timestamptz,
    ADD COLUMN IF NOT EXISTS info_check_suppressed_fingerprint text;
```

**`set_by` values:**

| Value | Set when |
|-------|----------|
| `infoGatherer` | InfoGatherer flow completion write (uni/gender/`ilgili_otel`) |
| `tagAssigner` | Router accepted Gemini proposal and persisted |
| `human` | Human `conversation_updated` webhook (non-bot-authored) |

**Backfill:** Existing rows with non-null values and null `*_set_by` may be left null (legacy) — Router treats null `set_by` as overwritable by bot (same as Option A for `ilgili_otel` with null `_set_at`).

---

## Gemini I/O contract

### Input (payload_builder)

Context block continues to show all attributes for labelling judgement. Update wording:

- Human-only fields remain **read-only context** for labelling (never in output).
- Bot-writable fields are **read for context; proposed in output** (full snapshot).

Include resolved display values where helpful:

```
university:       <Chatwoot list string or "bilinmiyor">   # derived from university_id via map
ogrenci_cinsiyet: <Erkek | Kız | Bilinmiyor or "bilinmiyor">
oda_tiipi:        <value or "boş">
... (human-only fields unchanged) ...
mevcut_etiketler: ...
```

Keep `university_id` in context optionally for debugging, but Gemini output must use **Chatwoot list strings** for `university`.

### Output (full snapshot — same semantics as labels)

```json
{
  "labels": ["ogrenci", "1-sinif", "fiyat-soruyor"],
  "attributes": {
    "university": "Boğaziçi Üniversitesi",
    "ogrenci_cinsiyet": "Kız",
    "oda_tiipi": "boş"
  }
}
```

| Key | Required in `attributes` every run? | Notes |
|-----|-------------------------------------|-------|
| `labels` | Yes | Full desired label state (existing contract) |
| `attributes` | Yes | Full desired state for **bot-writable keys only** |
| `university` | Yes | Exact Chatwoot list string, or echo current, or `"bilinmiyor"` if unknown |
| `ogrenci_cinsiyet` | Yes | `Erkek` / `Kız` / `Bilinmiyor` |
| `oda_tiipi` | Yes | Exact list string or `"boş"` if unset |

**Excluded from output entirely:** `ilgili_otel`, `tasinma_tarihi`, `butce`, `kayip_nedeni`.

**Snapshot rule for attributes:** Echo current DB-derived values when unchanged. Use `"boş"` (or equivalent sentinel agreed in prompt) for unset — **never omit a bot-writable key** (omitting would be ambiguous with label-style removal; we do not allow attribute clearing).

**`info-check`:** Gemini must **not** add or remove `info-check`. Router owns it entirely.

### Parser changes (`payload_builder.parse_gemini_response`)

Return a structured result, e.g.:

```python
@dataclass
class GeminiTagResult:
    labels: list[str]
    attributes: dict[str, str]  # only bot-writable keys
```

Return `None` if malformed. Backward compatibility: if `attributes` key missing, treat as `{}` and skip attribute merge (log warning) — or fail the run; **prefer fail** so partial deploys are visible.

---

## Router pipeline (revised per run)

Replace current step 6 (“deterministic attribute writes from DB”) with:

```
1. Read current labels live from Chatwoot
2. Load conversation from DB
3. Build payload from DB + messages + labels
4. Call Gemini → GeminiTagResult (labels + attributes)
5. Resolve labels (existing label_resolver + info-check pass — see §8)
6. Merge attributes (attribute_merger — see §7)
7. Persist accepted attribute changes to DB (with set_by = tagAssigner)
8. Push changed labels to Chatwoot (if diff) + record_self_write
9. Push changed attribute keys to Chatwoot (if diff) + record_self_write
10. Reset message counter; mark run success
```

**`tag_assigner_runs.gemini_result`:** Store both `labels` and `attributes` from Gemini for write-back retry.

**InfoGatherer path unchanged for flow completion:** Still calls `write_attributes_at_flow_completion()` for `university`, `ogrenci_cinsiyet`, `ilgili_otel` — but must set `university_set_by` / `gender_set_by` / `ilgili_otel_set_by` to `infoGatherer` and timestamps on write.

**TagAssigner path:** Remove `ilgili_otel` from TagAssigner attribute push entirely.

---

## Attribute merge (`app/tagassigner/attribute_merger.py` — new module)

Pure merge logic + async validation helpers. Router calls I/O; merger returns decisions.

### Per-field merge algorithm

For each bot-writable field `F`:

1. Read `current` from DB (resolve university to Chatwoot string for comparison).
2. Read `proposed` from Gemini snapshot.
3. If `proposed` equals `current` (normalized) → **no-op**.
4. If `proposed` is empty/`boş` and `current` is set → **no-op** (no clearing).
5. If `*_set_by == 'human'` → **block** → record blocked mismatch fingerprint.
6. Apply field-specific gates:
   - **university:** block if Gemini proposal implies multiple universities (detect in proposal metadata or Router rejects if chat has multiple — prefer Router scan of transcript for multi-uni phrases as belt-and-suspenders); validate proposed string ∈ `university_chatwoot_label_map`; resolve to `university_id`.
   - **ogrenci_cinsiyet:** map Erkek/Kız/Bilinmiyor → `male`/`female`/null; block if not a valid enum.
   - **oda_tiipi:** block unless explicit-statement rule satisfied (Router may trust Gemini proposal only if prompt says explicit-only; optional transcript keyword check in V2).
7. If all gates pass → **accept** → DB update with `*_set_by = 'tagAssigner'`, `*_set_at = now()`.
8. If blocked and `proposed ≠ current` → contribute to **info-check** evaluation (§8).

### Output of merge

```python
@dataclass
class AttributeMergeResult:
    db_updates: dict          # column → value for accepted changes
    chatwoot_patches: dict    # Chatwoot key → value (changed keys only)
    blocked_mismatches: list[BlockedMismatch]  # for info-check

@dataclass
class BlockedMismatch:
    field: str
    current: str
    proposed: str
    reason: str  # human_set | multi_university | never_touch | validation_failed | ...
```

---

## Two-way sync

### DB → Chatwoot (Router push)

After DB updates, push **changed keys only** via `set_custom_attributes`:

| DB | Chatwoot key | Transform |
|----|--------------|-----------|
| `university_id` | `university` | `get_chatwoot_list_value_for_university()` |
| `gender` | `ogrenci_cinsiyet` | male→Erkek, female→Kız, else Bilinmiyor |
| `oda_tiipi` | `oda_tiipi` | passthrough |

Call `record_self_write(chatwoot_conversation_id)` before each Chatwoot attribute write (same as labels).

### Chatwoot → DB (human webhook)

Extend `_process_conversation_updated` in `app/webhooks/chatwoot.py` when **not** bot-authored:

| Chatwoot key | DB update | Companions |
|--------------|-----------|------------|
| `university` | Resolve via **new** `get_university_id_for_chatwoot_list_value()` | `university_set_by='human'`, `university_set_at=now()` |
| `ogrenci_cinsiyet` | Map to `gender` enum | `gender_set_by='human'`, `gender_set_at=now()` |
| `oda_tiipi` | `oda_tiipi` | `oda_tiipi_set_by='human'`, `oda_tiipi_set_at=now()` |
| (existing) | `tasinma_tarihi`, `kayip_nedeni`, `butce`, `ilgili_otel` | unchanged |

**New query:** `get_university_id_for_chatwoot_list_value(chatwoot_list_value: str) -> Optional[UUID]`

If reverse lookup fails, log warning and skip DB update (do not corrupt FK).

---

## `info-check` label (Router-owned)

### Definition

New **List 1** label: `info-check`

- Router may add and remove.
- **No exclusivity** — coexists with any other labels.
- Gemini must never propose it.

Add to `LIST_1_USABLE` in `label_resolver.py`.

### Fingerprint format

Stored in `conversations.info_check_fingerprint`:

```
{field}:{current}:{proposed}:{block_reason}
```

Examples:

- `university:abc-uuid:def-uuid:human_set`
- `ogrenci_cinsiyet:Erkek:Kız:human_set`
- `oda_tiipi:Tek Kişilik:Çift Kişilik:human_set`

Use stable serializations (UUIDs for university, normalized strings elsewhere).

### Add rule

After attribute merge and label resolution, if **any** `blocked_mismatches` entry exists:

1. Compute fingerprint for the **primary** mismatch (see priority below).
2. If fingerprint == `info_check_suppressed_fingerprint` → **do not add** (human dismissed this exact issue).
3. Else if `info-check` not already on resolved labels → add it.
4. Set `info_check_fingerprint` and `info_check_added_at = now()`.

**Priority when multiple blocked mismatches:** university > ogrenci_cinsiyet > oda_tiipi > label-only blocked conflicts (if any added later). Store one active fingerprint at a time.

### Remove rules

| Condition | Action |
|-----------|--------|
| **Mismatch resolved** — merge would now accept the change (or proposed == current) | Remove `info-check` from labels; clear `info_check_fingerprint` and `info_check_added_at` |
| **Human removed `info-check`** from Chatwoot (webhook, not bot-authored) | Set `info_check_suppressed_fingerprint = info_check_fingerprint`; clear active fingerprint + added_at |
| **48h TTL** — `info_check_added_at + 48h < now()` and label still present | Router removes label; clear fingerprint + added_at; **do not** set suppressed (stale-flag cleanup; same mismatch may re-flag on a later run) |

### Human dismiss detection

In `_process_conversation_updated`:

- If `"info-check"` was in previous DB `labels` (or tracked prior state) and absent in new labels, and not bot-authored → treat as human dismiss → update suppressed fingerprint.

Alternative: detect at Router start by comparing live Chatwoot labels to DB `info_check_fingerprint` state. **Prefer webhook** for immediacy.

### README note (required on implement)

Document under TagAssigner section:

> **`info-check`** is added by the bot when chat evidence conflicts with a label or attribute but the Router cannot fix it (e.g. human-set field). It auto-expires after **48 hours** if a salesperson has not cleared it — this is intentional stale-flag cleanup, not an indication the mismatch was resolved. If a human removes the label, the bot will not re-add it for the **same** mismatch fingerprint unless a **different** conflict appears.

---

## Label resolution integration

Order within Router:

1. `resolve_labels(before, gemini.labels)` — existing pipeline.
2. `apply_info_check(resolved_labels, conv, blocked_mismatches, now)` — add/remove `info-check` per §8.
3. Write labels if changed.

Do **not** let Gemini's label snapshot include or exclude `info-check` — strip it from Gemini proposed set before merge if present (log warning), then apply Router decision.

---

## Prompt updates (`system_prompts/tagassigner_prompt.md`)

1. **Remove** draft notes at lines 186+ (superseded by this spec).
2. **Update INPUT** — bot-writable vs human-only fields clearly separated.
3. **Update OUTPUT CONTRACT** — add `attributes` object with full snapshot semantics.
4. **Add ATTRIBUTE RULES section** — per-field rules from §Field ownership.
5. **Add explicit exclusions** — never output human-only keys; never output `info-check`.
6. **Add LIST 1 entry** for `info-check` — *for human reference only; TagEngine must never assign it* (Router assigns).

**Allowed string tables:** See §Chatwoot `oda_tiipi` list (confirmed from live Chatwoot, 2026-07-06).

---

## Chatwoot `oda_tiipi` list (confirmed)

| Property | Value |
|----------|-------|
| Display name | Oda Tipi |
| Key | `oda_tiipi` (double-i — must match exactly) |
| Type | List |
| Description | Öğrenci hangi oda tipine okey? |

**Allowed values** (exact strings — Router and Gemini must use these verbatim):

1. `Tek Kişilik`
2. `Çift Kişilik`
3. `Yurt Tipi`
4. `Fark Etmez`
5. `Üç Kişilik`
6. `Dört Kişilik`
7. `Beş Kişilik`
8. `1+1`
9. `2+1`
10. `3+1`

Router rejects any proposed `oda_tiipi` not in this set. Prompt must include this table for TagEngine.

---

## Config

**`TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES`** (new config list):

```python
TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES = ["university", "ogrenci_cinsiyet", "oda_tiipi"]
```

**`TAGASSIGNER_ATTRIBUTE_KEYS`** — unchanged (all attrs still sent as context).

**`TAGASSIGNER_ROOM_TYPE_VALUES`** (confirmed — Router validation + prompt):

```python
TAGASSIGNER_ROOM_TYPE_VALUES: list[str] = [
    "Tek Kişilik",
    "Çift Kişilik",
    "Yurt Tipi",
    "Fark Etmez",
    "Üç Kişilik",
    "Dört Kişilik",
    "Beş Kişilik",
    "1+1",
    "2+1",
    "3+1",
]
```

---

## Batch path

`batch_client.process_batch_results` → `apply_resolved_labels` must be extended to `apply_resolved_result(conversation_id, run_id, gemini_result)` accepting labels + attributes. Same merge pipeline as live path.

No change to batch **submit** stub in this spec — but merge code must be shared so batch and live stay identical.

---

## Tests

| File | Coverage |
|------|----------|
| `tests/test_attribute_merger.py` | Unit: each gate, no clearing, human-set block, multi-uni block, accept paths |
| `tests/test_info_check.py` | Unit: add/remove/suppress/48h TTL fingerprint logic |
| `tests/test_payload_builder.py` | Parse new JSON shape; context display values |
| `tests/test_tagassigner_router.py` (new or extend) | Integration: DB→Gemini→DB→Chatwoot mock chain |
| `tests/test_chatwoot_webhook.py` (extend) | Human sync for university/gender/oda_tiipi; info-check dismiss |
| `tests/test_attribute_resolver.py` (extend/refactor) | InfoGatherer writes set `infoGatherer` companions; TagAssigner path skips ilgili_otel |

---

## Manual test scenarios

1. **InfoGatherer sets uni/gender/hotel** → Chatwoot has values; TagAssigner run echoes same attributes; no `info-check`.
2. **Chat contradicts university; DB bot-set** → TagAssigner updates `university_id` in DB + Chatwoot.
3. **Chat contradicts university; human-set** → no DB change; `info-check` added.
4. **Human dismisses `info-check`** → same mismatch does not re-add; different mismatch does.
5. **`info-check` older than 48h** → Router removes label on next run (mismatch may still exist).
6. **Multiple universities in chat** → no university change; no `info-check` unless other blocked mismatch.
7. **Explicit room type; DB empty** → `oda_tiipi` set with `tagAssigner`.
8. **Human sets `oda_tiipi` in Chatwoot** → webhook syncs + `human`; bot blocked from override.
9. **TagAssigner run** → does not touch `ilgili_otel`, `tasinma_tarihi`, `butce`, `kayip_nedeni`.
10. **Human edits university in Chatwoot** → reverse-map to `university_id`, `university_set_by=human`.

---

## Out of scope

- Nightly batch API submit wiring (separate work).
- Budget / move-in date bot inference (explicitly human-only).
- `ilgili_otel` preference-from-chat (InfoGatherer + RecEngine only).
- Custom attribute cleanup / rename in Chatwoot (config-driven keys already supported).

---

## Implementation plan

Execute in order. Each phase should leave tests green before proceeding.

### Phase 1 — Schema & models

1. Create `migrations/017_tagassigner_attributes.sql` with all columns from §Schema.
2. Apply migration to dev Supabase.
3. Extend `Conversation` model in `app/db/models.py` with new columns.
4. Extend `sync_conversation_labels_and_attributes()` and add focused update helpers in `queries.py`:
   - `update_conversation_university(id, university_id, set_by)`
   - `update_conversation_gender(id, gender, set_by)`
   - `update_conversation_oda_tiipi(id, value, set_by)`
   - `update_info_check_state(id, fingerprint, added_at, suppressed_fingerprint)`
5. Add `get_university_id_for_chatwoot_list_value()`.

### Phase 2 — InfoGatherer companion writes

6. Update `write_attributes_at_flow_completion()` to set `university_set_by`, `gender_set_by`, `ilgili_otel_set_by` = `infoGatherer` with timestamps when writing.
7. Ensure InfoGatherer university/gender DB updates (`set_university`, `set_gender`) set companions when values first captured (or delegate to completion write only — pick one path, avoid double-write races).
8. Tests: InfoGatherer completion write sets companions.

### Phase 3 — Human two-way sync (webhook)

9. Extend `_process_conversation_updated` to read `university`, `ogrenci_cinsiyet` from Chatwoot attrs.
10. Reverse-map and persist with `set_by='human'`.
11. Extend `oda_tiipi` sync to set `oda_tiipi_set_by='human'`.
12. Implement human dismiss detection for `info-check` label removal → `info_check_suppressed_fingerprint`.
13. Tests: webhook human sync + dismiss.

### Phase 4 — Attribute merger (pure logic)

14. Create `app/tagassigner/attribute_merger.py` with merge algorithm §7.
15. Create `app/tagassigner/info_check.py` with fingerprint builder + add/remove/suppress/TTL logic §8.
16. Unit tests for merger and info-check (no I/O).

### Phase 5 — Gemini I/O

17. Update `parse_gemini_response` → `parse_gemini_tag_result()` returning `GeminiTagResult`.
18. Update `gemini_client.call_gemini()` return type.
19. Update `payload_builder._build_context()` to show resolved university string + Turkish gender.
20. Rewrite `tagassigner_prompt.md` per §Prompt updates; remove draft lines 186+.
21. Tests: payload + parser.

### Phase 6 — Router integration

22. Refactor `apply_resolved_labels` → `apply_tagassigner_result(conversation_id, run_id, result: GeminiTagResult)`.
23. Pipeline order: label resolve → strip Gemini `info-check` if present → attribute merge → DB persist accepted attrs → info-check label pass → Chatwoot label write → Chatwoot attribute patch (changed keys only, `record_self_write` on both).
24. **Remove** TagAssigner path writing `ilgili_otel` (delete or gate in `resolve_and_write_attributes` — split InfoGatherer-only function from TagAssigner push).
25. Store full `gemini_result` `{labels, attributes}` on run row for retry.
26. Integration tests with mocked Gemini + Chatwoot.

### Phase 7 — Batch path alignment

27. Update `batch_client.process_batch_results` to parse and call `apply_tagassigner_result`.
28. Verify retry path uses cached full result.

### Phase 8 — Documentation & ops

29. Update `README.md` — attribute flow, field ownership, `info-check` 48h behavior.
30. Add cross-reference in `docs/tagassigner-v1-spec.md` pointing to this spec as amendment.
31. Add `TAGASSIGNER_ROOM_TYPE_VALUES` to `app/config.py` (values confirmed — §Chatwoot `oda_tiipi` list).

### Phase 9 — Manual verification

32. Run manual test scenarios §Manual test scenarios via ngrok/local Chatwoot.
33. Confirm `record_self_write` prevents feedback-loop double-sync on attribute writes.

---

## IMPLEMENTATION CHECKLIST

1. Migration 017 — `set_by` columns + info-check state columns
2. Models + query helpers + reverse university map
3. InfoGatherer `set_by=infoGatherer` on completion writes
4. Webhook two-way sync (university, gender, oda_tiipi) + human `info-check` dismiss
5. `attribute_merger.py` — pure merge with all gates
6. `info_check.py` — fingerprint, add/remove/suppress/48h TTL
7. Gemini parser + payload + prompt rewrite
8. Router refactor — full DB hub pipeline; remove TagAssigner `ilgili_otel` write
9. `record_self_write` on attribute Chatwoot pushes
10. Batch path uses same `apply_tagassigner_result`
11. Unit + integration tests
12. README + v1-spec cross-reference
13. Manual test pass
14. ~~Room type allowed strings~~ → **done** — see §Chatwoot `oda_tiipi` list
