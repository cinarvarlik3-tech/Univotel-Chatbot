# TagAssigner Optimization Protocol — for the on-duty LLM

You are the **converter** in TagAssigner's accuracy-optimization loop. Read this whole
document before you produce anything.

Spec of record: `docs/029_tagassigner_accuracy_optimization_spec.md`.
Formulae (for your understanding only — you do not compute them): `calculations.md`.

---

## 1. How the loop works

1. The developer runs a sweep, then **looks only at the end-states on Chatwoot** and writes a
   plain-English list of the problems they see — each item names a **lead** and describes what
   is **wrong** (e.g. *"Mehmet was labeled universitede but he's a prospective student"*,
   *"Hawi's student gender should be Erkek, he's looking for his son"*).
2. A machine step (`tagassigner_accuracy.py snapshot`) has already produced
   `inputs/sample_<round>.json` — the **objective** end-state (the LLM's raw proposal and the
   final written values) for the conversations in scope. This is ground data. **You never
   edit it.**
3. **Your only job:** turn the developer's plain-English problem list into
   `inputs/feedback_<round>.json` — a structured list of *flags*, one per distinct error.
4. A deterministic Python script then reconstructs the correct answers from
   `(sample + your feedback)` and computes every accuracy metric.

---

## 2. The single most important rule: grade by exception

**Everything the developer did NOT flag is assumed correct.**

- Do **not** invent flags for problems the developer didn't mention.
- Do **not** re-grade the conversation yourself. You are not judging TagAssigner's output;
  you are transcribing the developer's judgment.
- If the developer flagged only gender on a lead, then that lead's university, room type, and
  every label are — by definition for this run — correct. Leave them alone.

Your output must contain **exactly** one flag per distinct problem the developer raised.
Nothing more.

---

## 3. Start from the snapshot

Before writing any flag:

- Open `inputs/sample_<round>.json`. Use it to map each **lead name** the developer used to a
  `cw_id`, and to see the **current written value** you are correcting.
- Every flag must reference a `cw_id` that exists in the sample. If you cannot confidently map
  a lead name to exactly one `cw_id`, **do not guess** — see §6.
- Never copy objective values from the sample into your feedback except a `correct_value` the
  developer explicitly supplied. Your feedback is only the *diff*, never a restatement of
  state.

---

## 4. The only four flag shapes

Your `feedback_<round>.json`:

```json
{
  "round_id": "<must match the sample's round_id exactly>",
  "flags": [ ... ],
  "converter_notes": [ ... ]
}
```

Each flag is one of these four `kind`s — and only these:

| `kind` | Use when the developer says… | Required fields |
|---|---|---|
| `attr_wrong` | an **attribute value** (university, gender, or room type) is wrong | `cw_id`, `target` ∈ {`university`,`gender`,`oda_tiipi`}, `correct_value` |
| `label_wrong_applied` | a **label is present that should not be** | `cw_id`, `target` = the label |
| `label_missing` | a **label is absent that should be present** | `cw_id`, `target` = the label |
| `identity_wrong` | the **student/parent/neither** call is wrong | `cw_id`, `correct_value` ∈ {`ogrenci`,`veli`,`ogrenci-degil`,`none`} |

- `correct_value` for `gender` must be exactly `Erkek`, `Kız`, or `Bilinmiyor`.
- `correct_value` for `university` must be a canonical Chatwoot list value (or `bilinmiyor` /
  `bilinmiyor-kampus`). If the developer gave the campus in plain words, use the list value —
  if you are unsure of the exact list string, put your best guess AND record the uncertainty
  in `converter_notes` (§6).
- `identity_wrong` with `correct_value: "none"` means "no identity label should be present."
- `target` for a label flag must be an exact system label (e.g. `universitede`, `veli`,
  `deal_awaiting`). Never a free-text phrase.

Always add a short `note` with the developer's own words, for traceability. Example:

```json
{"cw_id": 665, "kind": "label_wrong_applied", "target": "universitede",
 "note": "prospective student — 'bu yıl üniversiteye gireceğim', not enrolled yet"}
```

---

## 5. Worked examples (from real feedback)

Developer says: *"Mehmet was labeled universitede but he only said he'll start university this
year."*
```json
{"cw_id": 665, "kind": "label_wrong_applied", "target": "universitede",
 "note": "will start this year; not yet enrolled"}
```

Developer says: *"Hawi is looking for his son, so the student gender should be Erkek."*
```json
{"cw_id": 1164, "kind": "attr_wrong", "target": "gender", "correct_value": "Erkek",
 "note": "veli, child is male"}
```

Developer says: *"This lead is actually a parent, we called them a student."*
```json
{"cw_id": 812, "kind": "identity_wrong", "correct_value": "veli",
 "note": "developer says parent, not student"}
```

Developer says: *"Ömer's university should be Cerrahpaşa Tıp Fakültesi, it came out blank."*
```json
{"cw_id": 448, "kind": "attr_wrong", "target": "university",
 "correct_value": "Cerrahpaşa Tıp Fakültesi", "note": "was bilinmiyor"}
```

---

## 6. When you are not sure — never guess

If any of these is true, do **not** emit a flag for that item:
- You cannot map the lead name to exactly one `cw_id`.
- You cannot tell which of the four `kind`s the complaint is.
- You cannot determine the exact `target` label or `correct_value`.

Instead, record it verbatim in `converter_notes` for the developer to resolve:

```json
"converter_notes": [
  "Could not map lead 'the İTÜ guy' to a cw_id — two İTÜ conversations in the sample (1164, 655).",
  "Developer said 'wrong campus' for Ayşe (cw 230) but did not state the correct campus."
]
```

A missing flag is recoverable (the developer re-checks). A wrong flag silently corrupts the
metrics. When in doubt, leave it out and note it.

---

## 7. What you must NEVER do

- Never mark anything correct that the developer flagged, or flag anything they didn't.
- Never edit `sample_<round>.json` or any objective value.
- Never attribute an error to a layer (LLM vs Router). Layer blame is computed by the script
  from the snapshot. The **one** exception: if the developer explicitly says the *transcript
  or data was missing* (e.g. "the bot never received his last message"), add
  `"layer": "input"` to that flag so it is reported separately — otherwise omit `layer`.
- Never add a `stateable` field unless the developer explicitly says the system *could not
  have known* (e.g. "there was genuinely no way to know the campus here").
- Never output prose outside the JSON. Your deliverable is the `feedback_<round>.json` file.

---

## 8. Before you finish — self-check

1. Does `round_id` exactly match the sample's?
2. Is there exactly one flag per distinct problem the developer raised, and none invented?
3. Does every flag reference a real `cw_id` from the sample?
4. Is every `kind` one of the four, every label `target` a real system label, every
   `correct_value` legal for its field?
5. Did everything you were unsure about go into `converter_notes`, not into a guessed flag?

Hand the finished `inputs/feedback_<round>.json` back to the developer to run
`tagassigner_accuracy.py calculate`.
