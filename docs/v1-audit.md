# Univotel Chatbot — V1 Audit

**Created:** 2026-07-04  
**Sources:** Live WhatsApp functional tests (`wa_test_links.md`), conv-52 end-to-end test (`test-and-fix-1.md`), pre-deploy test plan (`test_plan_flags_1_and_2.md`), codebase review, TagAssigner phase plan blockers.

This document consolidates everything that failed or is still open before calling V1 production-ready. Items already fixed in code are noted under **Resolved (conv-52)** so they are not re-opened accidentally.

---

## 1. Live test failures

### 1.1 Still failing or open (F-suite, 2026-07-04)

| ID | Step | Input / scenario | Result | Notes |
|---|---|---|---|---|
| **F6** | 2 | `taşkışla` → should resolve directly to İTÜ Maçka (campus-level alias, no escalation) | **FAIL** | Direct campus alias did not map; escalation fallback also failed. Blocker per test plan exit criteria. |
| **F8** | 3 | After İTÜ campus question, lead replies `Beşiktaş` (not a valid campus) | **FAIL** | Conversation freezes from the lead’s perspective — no bot reply. Code may set `human_needed` internally, but there is no user-visible message. |

### 1.2 Phrase-gate failures (blocked step 1 across most tests)

These are not logic failures in escalation/matching — the bot never entered the flow because step 1 did not pass the phrase gate. Testers worked around by skipping to step 2 with a “guaranteed” opener. See **§3 Phrase gate** for the full treatment.

| Test | Message that failed phrase gate |
|---|---|
| F1 | `Merhabalar, üniversiteme yakın konaklama arıyorum` |
| F2 | `merhaba` |
| F3 | `Merhabalar konaklama için yazıyorum` |
| F4 | `selam` |
| F5 | `Merhaba, yurt arıyorum` |
| F5b–F5f | `merhaba` (each sub-test) |
| F6 | `Merhabalar konaklama bilgisi alabilir miyim` |
| F7 | `Merhaba, üniversiteme yakın yer arıyorum` |
| F8 | `merhaba` |
| F9, F9b, F9c | `merhaba` |
| F10 | `merhaba` |

**Impact:** Any lead who opens with a natural Turkish greeting or inquiry (without `"Merhaba!"`, `"Üniversitem:"`, `"Başvuru Kodu:"`, etc.) is silently escalated to `human_needed` with no outbound message — indistinguishable from a broken bot.

### 1.3 Passed (after workaround or core path OK)

| ID | Outcome |
|---|---|
| F1 | Steps 2–3 pass (Boğaziçi escalation → Ana Kampüs → gender → RecEngine) |
| F2 | Step 2 pass (`bogazici` → escalation) |
| F3 | Steps 2–3 pass (escalation + RecEngine); step 3 flagged for **product decision** (see §2) |
| F4 | Step 2 pass (Doğuş escalation, mu/mü suffixes) |
| F5 | Step 2 pass (`su` → Sabancı, no escalation) |
| F5b–F5f | Abbreviation steps pass when reached |
| F7 | **Critical pass** — Beykent → `Ayazağa` resolves to Beykent Ayazağa, not İTÜ |
| F9 | `kadir has` multi-word alias pass |
| F10 | `qwerty üniversitesi` → out-of-Istanbul path; flagged for **product decision** (see §2) |

F9b (`ibn haldun`) and F9c (`29 mayıs`) were not annotated in the test log — treat as **unverified** until explicitly run and recorded.

### 1.4 Resolved (conv-52 first live test — fixed in code, re-verify)

These were confirmed bugs in the first end-to-end test (conversation 52). Commits address them; re-run conv-52 / F-suite to confirm they stay fixed.

| Item | Symptom | Fix status |
|---|---|---|
| **RecEngine priority** | Wrong hotel recommended (Academia 80 vs GK Regency 100) — missing `ORDER BY priority_score DESC` | Fixed — ordering + candidate logging in `rec_engine.py` / `queries.py` |
| **Parent escalation missing** | `"itü"` went straight to gender with no campus question | Fixed — `awaiting_campus_clarification` flow in `info_gatherer.py` |
| **Orphan universities** | Integrity check CRITICAL for 2 universities without `university_parent_map` rows | Fixed — seed commits + migration 013 |
| **Attribute timing** | Chatwoot attributes blank until first TagAssigner run | Fixed — Option A: `write_attributes_at_flow_completion` on RecEngine callback |
| **Escalation schema gaps** | `flow_state` CHECK constraint rejected `awaiting_campus_clarification`; missing label-map row for Doğuş Kadıköy | Fixed — migration `013_escalation_schema_fixes.sql` (confirm applied on prod DB) |
| **Alias vs short_name precedence** | Parent alias `"itü"` shadowed by campus `short_name` | Fixed — parent alias check hoisted above Tier-1 in `matching.py` |

### 1.5 Not yet run / not confirmed (Suites A & B)

From `test_plan_flags_1_and_2.md` — required before V1 sign-off; no pass record in live test notes yet.

| Suite | What | Pass condition |
|---|---|---|
| **A1–A11** | `hotel_data_state_audit.sql` | Zero rows on every check (GK Regency–class silent misconfigurations) |
| **A12** | Per-campus RecEngine ranking review | Intended winner at `rec_rank = 1` for each actively served campus |
| **B (C1–C6)** | `alias_collision_check.py` | Exit code 0 (no hard collisions after ~200 aliases activated) |

---

## 2. Product decisions needed

Items that are not purely engineering bugs — they need an explicit product/ops choice before or shortly after launch.

### 2.1 RecEngine geography and inventory (F3 — Üsküdar Merkez)

After a successful escalation and gender capture, RecEngine returned a hotel that is technically correct per current rules (`gender` + `hotel_accessible_universities` + `priority_score`), but may be wrong for the business.

**Questions to decide:**

- Should `hotel_accessible_universities` be **narrowed** (fewer hotels linked per campus)?
- Should `priority_score` encode **district / proximity**, not just manual preference?
- Should there be **hard geographic rules** (e.g. campus and property must be in compatible districts — “same continent” was raised informally in testing)?

**Until decided:** Run Suite A12 for Üsküdar Merkez and every other high-traffic campus; confirm the hotel at rank 1 is the one sales would actually send.

### 2.2 Invalid campus reply (F8 — `Beşiktaş` after İTÜ question)

Lead answered the campus escalation with a label that is not in the offered set.

**Options:**

| Option | Behavior |
|---|---|
| **A — Re-ask** | Send the campus question again (possibly with a hint: “Lütfen listedeki kampüslerden birini yazın”) |
| **B — Human handoff with message** | Set `human_needed` **and** send a short outbound (“Sizi yetkiliye aktarıyorum”) |
| **C — Defer to FallBack (V2)** | LLM disambiguation — out of scope for V1 unless explicitly prioritized |

**Current behavior:** Internal escalation only; lead sees silence. **Unacceptable for production** regardless of which option is chosen.

### 2.3 Invalid / unknown university (F10 — `qwerty üniversitesi`)

Both made-up names and real universities outside Istanbul hit the same path today: no DB match → `/istanbul` canned response (when university keywords are present) or `human_needed`.

**Questions to decide:**

- Is “not in our `universities` table” always treated as out-of-Istanbul? (Current tester recommendation: **yes** — safer than guessing.)
- Do we ever need a **national university list** to distinguish “real but not served” from “nonsense”?
- Should the copy differ for “we don’t serve your city” vs “we don’t recognize that name”?

**Current tester view:** Keeping one path is acceptable; document the copy and train sales accordingly.

### 2.4 Phrase gate strategy (see also §3)

When step 1 fails the gate today, the bot escalates to `human_needed` with no message.

**Options:**

| Option | Tradeoff |
|---|---|
| **Extend phrase gate** | Add greetings and inquiry patterns (`merhaba`, `selam`, `yurt arıyorum`, `konaklama`, etc.) — deterministic, auditable, more maintenance |
| **Awaiting-university without gate** | Treat any inbound as start of flow if conversation is `new` — higher false-positive risk |
| **FallBack layer (V2)** | LLM decides intent — flexible, deferred in V0/V1 plan |
| **Hybrid** | Small gate expansion + canned “please tell us your university” for soft openers |

**Decision required before production** — this affects every first message from organic WhatsApp traffic.

### 2.5 Campus list ordering (F-note-1)

`get_campuses_for_parent` may return campuses in nondeterministic order → escalation question order varies run-to-run.

**Decision:** Add `ORDER BY campus_label` (or a deliberate `display_order` column) for consistent UX?

### 2.6 Copy and content TODOs

| Item | Status |
|---|---|
| `deal_awaiting_msg` canned response | Still `<TODO>` in migration 006 — needs final Turkish copy |
| `henuz` / GLOBAL-NULL-STATE copy | Confirm production-ready wording |
| Out-of-Istanbul (`/istanbul`) copy | Confirm acceptable for both unknown and out-of-area cases |

### 2.7 Attribute timing (resolved — record decision)

**Decision taken:** Option A — InfoGatherer writes `university`, `ogrenci_cinsiyet`, and `ilgili_otel` immediately at flow completion via shared attribute resolver. TagAssigner continues to maintain them. No further decision needed; verify on re-test.

---

## 3. Phrase gate

**Standalone item — highest-volume production risk outside F6/F8.**

### 3.1 What it does today

In `app/layers/info_gatherer.py`, `_handle_new` requires the inbound message to contain **at least one exact substring** from:

```
"Üniversitem:"
"Merhaba!"          ← exclamation required; "Merhaba" / "merhaba" fail
"My University:"
"Hello!"            ← exclamation required
"Başvuru Kodu:"
```

If none match → log `InfoGatherer: phrase gate failed` → `_escalate_human_needed` → **no outbound message to the lead**.

### 3.2 Why it exists

V0 spec: only respond to leads arriving from **pre-filled website links** with predictable openers. `"Başvuru Kodu:"` in particular signals a structured hotel inquiry. Reasonable for V0; **not scalable** for general WhatsApp inbound.

### 3.3 Live test evidence

- **11 of 10 test scenarios** hit phrase-gate failure on step 1 (every test that used a natural opener).
- Testers could only proceed by skipping step 1 — **real leads cannot skip step 1**.
- Observed log: `InfoGatherer: phrase gate failed for conversation …` (2026-07-04 20:41:29).

### 3.4 User-visible failure mode

From the lead’s perspective: message sent, no reply, conversation appears dead. Internally: `flow_state = human_needed`. Sales may not notice until much later.

### 3.5 Recommended directions (pick one before go-live)

1. **Minimum viable expansion** — Accept case-insensitive: `merhaba`, `selam`, `merhabalar`, `hello`, plus keyword triggers: `yurt`, `konaklama`, `üniversite`, `basvuru` / `başvuru` without requiring exact punctuation.
2. **Two-tier gate** — Soft opener → send `hangi` (university ask) instead of `human_needed`; hard gate only for clearly irrelevant traffic (optional).
3. **Gate only on first message** — If `flow_state = new`, accept any non-empty text and proceed to university capture (simplest; review spam risk).
4. **Keep strict gate** — Only viable if **100% of production traffic** is guaranteed to use pre-filled link messages; document and enforce at marketing/website layer.

### 3.6 Acceptance criteria (when “done”)

- [ ] F1 step 1 passes without workaround (`Merhabalar, üniversiteme yakın konaklama arıyorum`).
- [ ] F2 step 1 passes (`merhaba` → bot responds, does not silently stop).
- [ ] Failed gate (if any remain) sends a **visible** outbound or re-prompt — never silent `human_needed`.

---

## 4. Other weaknesses to improve

Engineering and operational gaps beyond the live test failures — not all are V1 blockers, but all affect maintainability, safety, or scale.

### 4.1 User experience / observability

| Weakness | Detail |
|---|---|
| **Silent `human_needed`** | `_escalate_human_needed` updates DB only — no Chatwoot message. Affects phrase gate, F8, gender/university parse failures, post-completion free text. |
| **No request/correlation IDs** | Hard to trace one conversation across webhook → InfoGatherer → RecEngine → callback → TagAssigner in logs. |
| **Background task errors** | Some handlers log one line without traceback (`_process_inbound`, sweeps). Failures can look like “bot ignored me.” |

### 4.2 Data and integrity

| Weakness | Detail |
|---|---|
| **Suite A / B not signed off** | Hotel flag audit and alias collision script may still surface blockers (GK Regency class, C1 collisions). |
| **Migration 013** | Must be confirmed applied on production DB (flow_state constraint + Doğuş Kadıköy label map). |
| **Integrity check orphan** | Test plan notes one remaining `university_chatwoot_label_map` gap (`22490d0d…`) — boot must pass with `INTEGRITY_CHECK_BYPASS=off`. |
| **Full-table loads per message** | `get_all_hotels()`, `get_all_universities()`, `get_all_university_aliases()` on every match step — fine now; won’t scale without caching. |

### 4.3 Codebase hygiene

| Weakness | Detail |
|---|---|
| **No README** | `/docs` is strong; no quick “clone, env, migrate, run, test” guide for new engineers. |
| **No CI** | 125 pytest tests exist; nothing runs them on push/PR. HMAC unit test is **stale** (does not include `X-Chatwoot-Timestamp` in signed payload — one test currently fails). |
| **`queries.py` monolith** | ~990 lines — all SQL in one module; slows onboarding and review. |
| **`.env.example` defaults** | `INTEGRITY_CHECK_BYPASS=true` is a risky template default for production. |

### 4.4 Architecture / deployment

| Weakness | Detail |
|---|---|
| **In-memory feedback-loop guard** | `_recent_self_writes` in `chatwoot.py` is not durable and breaks with multiple Railway replicas. |
| **localhost internal HTTP** | RecEngine start/callback loop through `http://localhost:{PORT}` — works on single dyno; fragile if process model changes. |
| **Nightly Gemini batch** | Code present; needs GCP billing, GCS access, public webhook URL, and end-to-end batch verification. Optional for day-one if manual `tag` + idle scan suffice. |
| **Turkish label round-trip** | TagAssigner merge/guard assumes Chatwoot returns labels verbatim (`hazırlık`, `kayıp`, etc.) — must verify against live Chatwoot before trusting List-2 hard guard. |
| **`oda_tiipi` Chatwoot key** | Must exactly match live attribute key (double-i) — mismatch breaks attribute sync silently. |

### 4.5 Spec / content gaps

| Weakness | Detail |
|---|---|
| **`deal_awaiting` copy** | TODO in seed migration |
| **Campus ordering** | Nondeterministic escalation question order (see §2.5) |
| **F6 root cause** | Campus alias `taşkışla` failure not yet diagnosed in code (DB seed? normalization? match tier?) — needs engineering investigation |

---

## 5. Production readiness checklist

Everything that must be true before turning off `TESTING_LIMITATIONS_MODE` and treating V1 as live.

### 5.1 Blockers — must complete

**Live conversational tests**

- [ ] **F6 pass** — `taşkışla` → İTÜ Maçka direct, no escalation
- [ ] **F7 pass** — cross-parent collision (Beykent Ayazağa ≠ İTÜ) — already passed; keep as regression
- [ ] **F1, F3, F5 pass** — full flow without step-1 workaround
- [ ] **Phrase gate (§3)** — product decision implemented; natural openers get a visible bot response
- [ ] **F8** — invalid campus reply has defined, user-visible behavior (§2.2)

**Data audits**

- [ ] **Suite A (A1–A11)** — `hotel_data_state_audit.sql` returns zero rows on every check
- [ ] **Suite A12** — manual review: intended hotel at rank 1 for İTÜ Maslak, İTÜ Maçka, Üsküdar Merkez, and 2–3 other high-traffic campuses
- [ ] **Suite B** — `alias_collision_check.py` exits 0 (C1, C3, C5, C6 clean)

**Infrastructure & config**

- [ ] **`INTEGRITY_CHECK_BYPASS=off`** — app boots cleanly; all integrity checks pass
- [ ] **Migration 013 applied** on production ChatBot DB
- [ ] **All migrations 006–013 applied** and idempotent re-run verified if needed
- [ ] **`TESTING_LIMITATIONS_MODE=off`** only after above pass — or staged rollout with expanded allowlist first
- [ ] **Production env** — `CHATWOOT_*`, `DATABASE_URL`, `INTERNAL_SHARED_SECRET`, `GEMINI_API_KEY`, webhook secrets set; no secrets in repo
- [ ] **`deal_awaiting_msg` and sentinel wiring** — copy finalized; DEAL-AWAITING-STATE integrity check passes

**Regression**

- [ ] **Conv-52 smoke test** — `itü` → campus question → campus → erkek → GK Regency (or current intended winner) → attributes in Chatwoot immediately
- [ ] Re-verify **conv-52 fixes** (§1.4) after any InfoGatherer/RecEngine change

### 5.2 Strongly recommended before go-live

- [ ] **F2, F4, F9** — full pass without phrase-gate workaround
- [ ] **F9b, F9c** — run and record (`ibn haldun`, `29 mayıs`)
- [ ] **Üsküdar / RecEngine product decision** (§2.1) — at minimum A12 sign-off for affected campuses
- [ ] **Out-of-Istanbul copy decision** (§2.3) — document chosen policy for sales
- [ ] **Campus ordering** (§2.5) — if UX consistency matters
- [ ] **Turkish label read-back test** — live Chatwoot label fetch vs List-2 guard
- [ ] **Fix stale HMAC unit test** — keep CI trustworthy when added
- [ ] **README** — local run, migration handoff, testing mode, allowlist numbers
- [ ] **Silent `human_needed` audit** — every escalation path sends at least one outbound OR is explicitly documented as intentional

### 5.3 Can follow shortly after launch (not day-one blockers)

- [ ] CI pipeline running pytest on every push
- [ ] Nightly Gemini batch end-to-end (GCP + GCS + batch webhook)
- [ ] Cache for universities/aliases/hotels lookup
- [ ] Multi-instance safe feedback-loop guard (Redis or DB-backed self-write record)
- [ ] Structured / JSON logging for log aggregation
- [ ] FallBack layer (V2) for off-rails cases F8/F10 expose

### 5.4 Suggested go-live sequence

1. Run Suites A & B; fix every row returned.  
2. Fix F6; implement phrase gate decision (§3); fix F8 user-visible behavior.  
3. Re-run full F-suite + conv-52 with `INTEGRITY_CHECK_BYPASS=off`.  
4. Staged rollout: widen allowlist → monitor logs → `TESTING_LIMITATIONS_MODE=off`.  
5. Monitor first week: RecEngine candidate logs, integrity daily sweep, TagAssigner error rate.

---

## Related documents

| Document | Purpose |
|---|---|
| `wa_test_links.md` | Live test messages, pass/fail annotations |
| `test-and-fix-1.md` | Conv-52 root-cause analysis and fix list |
| `test_plan_flags_1_and_2.md` | Suite A/B/F definitions and exit criteria |
| `tagassigner-phase-plan.md` | TagAssigner phase gates and open blockers |
| `univotel-chatbot-spec.md` | V0 architecture reference |
| `tagassigner-v1-spec.md` | V1 TagAssigner reference |
