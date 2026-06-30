# Univotel Chatbot — V0 Amendment Note: `deal_awaiting` Flow

**Status:** Ready for implementation
**Amends:** V0 spec (InfoGatherer / RecEngine)
**Reason:** The `deal_awaiting` concept surfaced during V1 (TagAssigner) planning, but it is **not** a tagging concern — it is a deterministic InfoGatherer outcome. It belongs in the V0 flow, documented separately so the InfoGatherer logic stays in one place.

---

## 1. What `deal_awaiting` is

A lead is `deal_awaiting` when their university is one **we don't yet have a property for** — but it's a real Istanbul university that's in our `universities` table. It means "we serve this city, just not this school yet."

This is **not a judgment call and not chat-inferred** — it's a deterministic membership lookup: is the lead's `university_id` in the `deal_awaiting_universities` table? Because of that, it is resolved by **InfoGatherer (the Router), never by the LLM** — the same way `university`/`gender` resolution is deterministic.

## 2. Why it lives in InfoGatherer, not TagAssigner

`deal_awaiting` depends only on `university_id`, which InfoGatherer already resolves and stores. There is no reason to wait for a TagAssigner run, an LLM call, or the 5-message trigger. InfoGatherer can resolve it the moment it knows the university — faster and cheaper, with no LLM in the path.

It also maps cleanly onto a pattern V0 already has: the `GLOBAL-NULL-STATE` "we have nothing for you" outcome. `deal_awaiting` is a **second, distinct** no-property reason:

| Outcome | Meaning | When detected |
|---|---|---|
| `GLOBAL-NULL-STATE` | RecEngine ran, found no hotel for this gender/university profile | after RecEngine runs |
| `DEAL-AWAITING-STATE` | We don't serve this university at all | **before** RecEngine runs |

Keeping them distinct matters for business signal: one says "adjust gender/capacity near this school," the other says "expand inventory to cover this school."

## 3. Control-flow placement

The check sits **after a successful university match, before firing RecEngine:**

```
university keyword found in message
  → match against universities table (normalize → exact → alias → Levenshtein ≤2)
     → NO match  → out-of-Istanbul (university not in our table at all) → send /istanbul, stop
     → MATCH:
         → check deal_awaiting_universities membership
             → member     → set `deal_awaiting` label
                            + resolve DEAL-AWAITING-STATE via response_schemas → send → terminal
             → not member → proceed to gender capture → RecEngine (normal flow)
```

**Why this ordering is safe (no collision with out-of-Istanbul):** the data layout guarantees the two cases look different to the matcher —
- `deal_awaiting` universities **ARE** in the `universities` table → they **match** → caught by the membership check.
- out-of-Istanbul universities are **NOT** in the table → they **fail to match** → caught by the `/istanbul` branch.

So a `deal_awaiting` school can never be mistaken for an out-of-Istanbul school, and vice versa. (This is precisely why the full `normalize → alias → Levenshtein ≤2` matching stack must be kept: a typo'd `deal_awaiting` or in-Istanbul university would otherwise fail to match and wrongly fall into `/istanbul`.)

## 4. Behavior on the `deal_awaiting` path

When InfoGatherer hits a `deal_awaiting` university, it does **both**:
1. **Sets the `deal_awaiting` Chatwoot label.** ⚠️ **Net-new Chatwoot write path — build, not reuse.** Earlier framing claimed "this is not a new capability — InfoGatherer already writes labels, e.g. `human_needed`." That was **wrong**: in the V0 codebase `human_needed`/`stopped` are `flow_state` values written to the **DB only** ([`queries.set_conversation_human_needed`](../app/db/queries.py)); nothing is ever pushed to Chatwoot. The `assign_label` helper exists in `chatwoot_client.py` but is **dead code (never called)**. So setting the `deal_awaiting` label requires building a real Chatwoot label-write path first. The work is small, but it is build, not extend — the same root issue applies to the deterministic attribute push (`university`/`gender`) and to TagAssigner's label writes (TagAssigner spec §6.9).
2. **Sends the `DEAL-AWAITING-STATE` canned response** (resolved through `response_schemas`, identical to every other canned-response send — no direct-to-`canned_responses` bypass).

Then the conversation is **terminal** for the scripted flow.

**Resolution goes through `response_schemas` like everything else** — deliberately *not* a direct pull from `canned_responses`. Reasons (consistent with the V0 single-resolution-path decision):
- one resolution path system-wide (no second code path to maintain);
- observability (logs/analytics can count `deal_awaiting` outcomes distinctly);
- flexibility (the `deal_awaiting` message can later differ from the generic "henüz" with no code change — just re-wire its canned response).

## 5. Database changes

```sql
-- Membership list: which universities we don't yet have a property for.
CREATE TABLE deal_awaiting_universities (
    university_id uuid PRIMARY KEY REFERENCES universities(id),
    created_at timestamptz DEFAULT now()
);

-- Second sentinel hotel, parallel to GLOBAL-NULL-STATE, for the deal_awaiting outcome.
-- Reserved fixed UUID so application code can reference it directly.
INSERT INTO hotels (id, name, is_visible, gender_scope, priority_score)
VALUES ('00000000-0000-0000-0000-000000000002', 'DEAL-AWAITING-STATE', false, NULL, NULL);

-- Its canned response (may be the existing "henüz" copy, or a deal_awaiting-specific message).
INSERT INTO canned_responses (id, short_code, content)
VALUES (gen_random_uuid(), 'deal_awaiting_msg', '<TODO: deal_awaiting "we don''t serve your school yet" copy>');

-- Wire the sentinel to its canned response through response_schemas (same path as all sends).
INSERT INTO response_schemas (id, hotel_id, response_id, sending_order)
SELECT gen_random_uuid(), '00000000-0000-0000-0000-000000000002', id, 1
FROM canned_responses WHERE short_code = 'deal_awaiting_msg';
```

Like `GLOBAL-NULL-STATE`, the `DEAL-AWAITING-STATE` sentinel is selected via an explicit code branch (membership check), not a query match — so it needs a row in `hotels` and its `response_schemas` wiring, but **not** a row in `hotel_accessible_universities`.

## 6. Health-check addition

Extend the V0 referential-integrity sweep (boot + daily) to assert `DEAL-AWAITING-STATE` exists in `hotels` **and** has at least one `response_schemas` row wired — same protection already given to `GLOBAL-NULL-STATE`. Fail loudly (`fatal`) if missing. (Bypassable via `INTEGRITY_CHECK_BYPASS`, like all other health checks.)
