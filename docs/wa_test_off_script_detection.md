# Univotel Chatbot — Live WhatsApp Tests: Off-Script Answer Detection (O1–O10)

**Feature under test:** `app/layers/answer_classifier.py` wired into InfoGatherer `awaiting_university` and `awaiting_gender`.

**Goal:** When the bot asks for university or gender, off-script replies (questions, digressions, third-person context) must **silently** hand off to a human — no bot message, no “üniversite ismini çıkaramadım” reprompt. Genuine answer attempts that fail matching must still use the existing two-strike clarify path.

**Companion unit tests:** `tests/test_answer_classifier.py`, `tests/test_matching.py` (near-miss), `tests/test_info_gatherer_handlers.py`.

**Related F-suite:** [`wa_test_links.md`](wa_test_links.md) — run O-suite **after** phrase-gate / matching F-tests pass.

---

## 0. Conventions & environment

**Test IDs:** `O#` = off-script / answer-classifier conversational tests.

**WhatsApp number:** `0212 909 52 44` → `902129095244`

**Preconditions (all O-tests):**
- App deployed and connected to ChatBot DB + Chatwoot.
- `TESTING_LIMITATIONS_MODE = on`; test phone on the 2-number allowlist.
- Migration **014** applied (`clarify_uni_name`, `clarify_campus_name`, `clarification_attempt`).
- Use a **dedicated test conversation** (default `cw_id = 52` in examples below).
- Watch terminal logs live; several pass/fail criteria are log-based.

**Pass convention:** Each step lists **Expected bot**, **Expected DB**, **Expected Chatwoot labels**. All must match unless marked optional.

---

## 1. Teardown (run between every O-test)

State bleeds across tests. Reset before **and** after each scenario.

```sql
-- Replace 52 with your test conversation cw_id.
UPDATE conversations
SET flow_state = NULL,
    university_id = NULL,
    gender = NULL,
    pending_parent_university_id = NULL,
    clarification_attempt = 0,
    ilgili_otel = NULL,
    ilgili_otel_set_at = NULL,
    ilgili_otel_set_by = NULL,
    auto_run_count = 0,
    manual_run_count = 0
WHERE cw_id = 52;
```

Optional: remove `human_needed` label between tests if you need a clean label slate (Chatwoot UI or API).

---

## 2. Verification queries

Run after the **decisive step** of each test (the step that should trigger classify / escalate / clarify).

### 2.1 Conversation state

```sql
SELECT cw_id, flow_state, clarification_attempt, university_id, gender
FROM conversations
WHERE cw_id = 52;
```

### 2.2 Off-script escalation log

```sql
SELECT created_at, log_level, internal_class, explanation
FROM chatbot_logs
WHERE conversation_id = (SELECT id FROM conversations WHERE cw_id = 52)
  AND internal_class = 'off_script_no_answer'
ORDER BY created_at DESC
LIMIT 3;
```

### 2.3 Last outbound messages (Chatwoot UI)

Confirm **no new bot message** after an off-script step. For clarify steps, expect:

| Canned `short_code` | Expected content (migration 014 seed) |
|---------------------|----------------------------------------|
| `hangi` | *(DB seed — university ask after greeting)* |
| `clarify_uni_name` | `Efendim üniversite ismini çıkaramadım, resmi adı neydi okulunuzun?` |
| `kiz-erkek` | *(DB seed — gender ask)* |

---

## 3. Shared setup step (most O-tests)

Steps 1–2 establish `flow_state = awaiting_university` before the message under test.

| Step | Message | wa.me link |
|------|---------|------------|
| 1 | `merhaba` | https://wa.me/902129095244?text=merhaba |
| 2 | *(wait for bot)* | Bot sends university ask (`hangi` canned response) |

**Expected after step 2:**
- `flow_state = awaiting_university`
- `clarification_attempt = 0`

---

## O1 — Off-script WH-question after university ask (primary regression)

**Trigger:** Lead asks “where are you?” instead of naming a university.

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | *(above)* |
| 3 | `yeriniz nerde` | https://wa.me/902129095244?text=yeriniz%20nerde |

**Expected after step 3:**

| Check | Expected |
|-------|----------|
| Bot reply | **None** (silent handoff) |
| `flow_state` | `human_needed` |
| Chatwoot label | `human_needed` present |
| Log | `internal_class = off_script_no_answer`, explanation contains `not a university answer` |

**Must NOT happen:** `clarify_uni_name` outbound (“Efendim üniversite ismini çıkaramadım…”).

RESULT: human_needed tag added without another message. SUCCESS.

*(run teardown)*

---

## O2 — Third-person parent context (edge case)

**Trigger:** Parent describes daughter’s situation — not a direct university-name answer.

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `kızım üniversiteye geçti ona yurt bakıyoruz` | https://wa.me/902129095244?text=k%C4%B1z%C4%B1m%20%C3%BCniversiteye%20ge%C3%A7ti%20ona%20yurt%20bak%C4%B1yoruz |

**Expected after step 3:** Same as O1 — silent `human_needed`, no clarify message.

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O3 — Request verb / housing intent (off-script)

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `konaklama arıyorum` | https://wa.me/902129095244?text=konaklama%20ar%C4%B1yorum |

**Expected after step 3:** Silent `human_needed` (request verb `arıyorum`).

RESULT: As expected. SUCCESS.
CONSIDERATION: Consider phrases like "konaklama arıyorum" to have their own canned responses.

*(run teardown)*

---

## O4 — Question clitic + request (off-script)

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `fiyat bilgisi alabilir miyim` | https://wa.me/902129095244?text=fiyat%20bilgisi%20alabilir%20miyim |

**Expected after step 3:** Silent `human_needed` (clitic `miyim` + request pattern).

RESULT: As expected. SUCCESS.
CONSIDERATION: Consider price inquiry to have its own canned response flow. 

*(run teardown)*

---

## O5 — Long rambling text without answer shape (off-script)

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `bugün çok yorgunum ve parka gittim sonra eve döndüm` | https://wa.me/902129095244?text=bug%C3%BCn%20%C3%A7ok%20yorgunum%20ve%20parka%20gittim%20sonra%20eve%20d%C3%B6nd%C3%BCm |

**Expected after step 3:** Silent `human_needed` (>2 words, no education anchor, no off-script question words but rambling — classifier bucket 5).

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O6 — Short unmatched answer attempt → clarify (must NOT silently escalate)

**Trigger:** Lead tries to name a university we don’t have; should reprompt once.

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `TÖÜ` | https://wa.me/902129095244?text=T%C3%96%C3%9C |

**Expected after step 3:**

| Check | Expected |
|-------|----------|
| Bot reply | `clarify_uni_name` content |
| `flow_state` | `awaiting_university` (≤2 words — stays in same state) |
| `clarification_attempt` | `1` |
| `flow_state` | **NOT** `human_needed` |

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O7 — Second short invalid answer → silent escalate (two-strike regression)

**Trigger:** Same as O6 but second attempt — existing architecture, not classifier.

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `TÖÜ` | https://wa.me/902129095244?text=T%C3%96%C3%9C |
| 4 | *(wait for clarify)* | |
| 5 | `xyz` | https://wa.me/902129095244?text=xyz |

**Expected after step 5:**

| Check | Expected |
|-------|----------|
| Bot reply | **None** |
| `flow_state` | `human_needed` |
| Log | May **not** have `off_script_no_answer` (two-strike path uses FallBack-stub explanation) |

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O8 — Long fake university name → clarify (answer attempt with education anchor)

| Step | Message | Link |
|------|---------|------|
| 1–2 | Shared setup | |
| 3 | `totally fake university name` | https://wa.me/902129095244?text=totally%20fake%20university%20name |

**Expected after step 3:**

| Check | Expected |
|-------|----------|
| Bot reply | `clarify_uni_name` |
| `flow_state` | `awaiting_university_clarification` (>2 words after normalize) |
| `clarification_attempt` | `1` |

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O9 — Valid university still matches first (classifier must NOT run)

**Regression:** Matching hierarchy unchanged — classifier only runs on `MatchConfidence.NONE`.

| Step | Message | Link |
|------|---------|------|
| 1 | `merhaba` | https://wa.me/902129095244?text=merhaba |
| 2 | *(wait for university ask)* | |
| 3 | `boğaziçi` | https://wa.me/902129095244?text=bo%C4%9Fazi%C3%A7i |
| 4 | *(campus question if parent alias)* | e.g. `Ana Kampüs` |
| 5 | `erkek` | https://wa.me/902129095244?text=erkek |

**Expected:** Normal F1-style flow — campus escalation (if applicable) → gender ask → RecEngine. **No** `off_script_no_answer` log at any step.

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## O10 — Gender off-script → silent handoff

**Trigger:** After gender ask, unrelated question.

| Step | Message | Link |
|------|---------|------|
| 1–3 | Reach `awaiting_gender` | Use O9 steps 1–4, or any working path to gender ask |
| 4 | `yeriniz nerede` | https://wa.me/902129095244?text=yeriniz%20nerede |

**Expected after step 4:**

| Check | Expected |
|-------|----------|
| Bot reply | **None** |
| `flow_state` | `human_needed` |
| Log | `internal_class = off_script_no_answer` |

**Regression (optional step 4b):** Repeat O9 through gender ask, send `kız` → flow continues to RecEngine.

RESULT: As expected. SUCCESS.

*(run teardown)*

---

## 4. Sign-off checklist

| ID | Scenario | Pass? | Notes |
|----|----------|-------|-------|
| O1 | WH-question `yeriniz nerde` → silent | ☐ | |
| O2 | Third-person parent context → silent | ☐ | |
| O3 | Request verb → silent | ☐ | |
| O4 | Clitic + request → silent | ☐ | |
| O5 | Long rambling → silent | ☐ | |
| O6 | `TÖÜ` → clarify once | ☐ | |
| O7 | Second invalid → silent (two-strike) | ☐ | |
| O8 | Long fake uni name → clarify | ☐ | |
| O9 | Valid `boğaziçi` → normal flow | ☐ | |
| O10 | Gender off-script → silent | ☐ | |

**Exit criteria:** O1, O2, O6, O9, O10 must pass before merge/deploy. O3–O5, O7–O8 are strongly recommended.

---

## 5. Known limitations (document, do not fail O-suite)

| Case | Current behavior | Why |
|------|------------------|-----|
| Off-script in `awaiting_university_clarification` | Silent escalate on first miss (unchanged) | Classifier not wired in clarification state |
| Off-script in `awaiting_campus_clarification` | Campus two-strike clarify (unchanged) | Out of scope |
| Real typo beyond near-miss band | Clarify → second fail → silent | Acceptable per product bias |
| FallBack V2 | `off_script_no_answer` log is the future LLM hook | Today = silent `human_needed` only |

---

## 6. Terminal log patterns

**Off-script (pass):**
```
InfoGatherer: ... off-script ... silent handoff
```
*(exact line varies; confirm via `chatbot_logs.internal_class = off_script_no_answer`)*

**Wrong behavior (fail — old path):**
```
POST .../conversations/52/messages  (outgoing clarify_uni_name)
```
after O1 step 3 — bot should **not** send.

**Match-first (pass for O9):**
No `off_script_no_answer` log; state advances to `awaiting_campus_clarification` or `awaiting_gender`.

---

## 7. Real terminal output 
2026-07-06 19:30:21,254 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:30:21,254 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:30:21,255 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:30:21,255 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='boğaziçi' conv=52
2026-07-06 19:30:21,793 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:30:22,874 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:30:23,955 INFO app.main ← POST /webhooks/chatwoot 200 2702ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:30:30,224 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:30:30,285 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109361ee0>
2026-07-06 19:30:30,285 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x107608c50> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:30:30,350 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109363770>
2026-07-06 19:30:30,350 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:30:30,351 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:30:30,351 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:30:30,351 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:30:30,351 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:30:30,672 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:30:30 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'428'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"e73f029952ce4d577427509ecce03923"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'f4d9226a-e696-4226-b996-eff71d331734'), (b'x-runtime', b'0.254012'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:30:30,673 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:30:30,673 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:30:30,673 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:30:30,673 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:30:30,674 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:30:30,674 DEBUG httpcore.connection close.started
2026-07-06 19:30:30,674 DEBUG httpcore.connection close.complete
2026-07-06 19:30:31,026 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:30:31,027 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:30:31,039 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:30:31,039 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Hangi Boğaziçi Üniversitesi kampüsü efen' conv=52
2026-07-06 19:30:31,594 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:30:32,669 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:30:33,753 INFO app.main ← POST /webhooks/chatwoot 200 2727ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:30:40,547 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:30:40,548 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:30:40,549 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:30:40,549 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='ana kampüs' conv=52
2026-07-06 19:30:41,088 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:30:42,166 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:30:43,242 INFO app.main ← POST /webhooks/chatwoot 200 2696ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:30:48,659 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:30:48,715 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109363f50>
2026-07-06 19:30:48,715 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x107616250> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:30:48,774 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109360320>
2026-07-06 19:30:48,775 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:30:48,775 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:30:48,775 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:30:48,776 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:30:48,776 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:30:49,077 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:30:49 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"5cb62db79934d04fe17d599bdd35995c"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'ed888cd0-8919-426d-953c-e5abeef70713'), (b'x-runtime', b'0.244303'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:30:49,077 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:30:49,078 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:30:49,078 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:30:49,078 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:30:49,078 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:30:49,078 DEBUG httpcore.connection close.started
2026-07-06 19:30:49,079 DEBUG httpcore.connection close.complete
2026-07-06 19:30:49,475 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:30:49,476 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:30:49,477 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:30:49,477 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Kız öğrenci için mi konaklama arıyordunu' conv=52
2026-07-06 19:30:50,014 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:30:51,091 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:30:52,173 INFO app.main ← POST /webhooks/chatwoot 200 2697ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:30:56,291 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:30:56,292 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:30:56,293 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:30:56,293 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='erkek' conv=52
2026-07-06 19:30:56,831 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:30:57,910 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:30:58,988 INFO app.main ← POST /webhooks/chatwoot 200 2696ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:31:01,450 DEBUG httpcore.connection connect_tcp.started host='localhost' port=8000 local_address=None timeout=5.0 socket_options=None
2026-07-06 19:31:01,454 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1076e6330>
2026-07-06 19:31:01,455 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:01,455 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:01,455 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:01,455 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:01,455 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:01,456 INFO app.main → POST /internal/recengine/start
2026-07-06 19:31:02,274 INFO app.main ← POST /internal/recengine/start 200 818ms
INFO:     127.0.0.1:63833 - "POST /internal/recengine/start HTTP/1.1" 200 OK
2026-07-06 19:31:02,275 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'date', b'Mon, 06 Jul 2026 16:31:01 GMT'), (b'server', b'uvicorn'), (b'content-length', b'20'), (b'content-type', b'application/json')])
2026-07-06 19:31:02,275 INFO httpx HTTP Request: POST http://localhost:8000/internal/recengine/start "HTTP/1.1 200 OK"
2026-07-06 19:31:02,276 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:02,276 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:02,276 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:02,276 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:02,277 DEBUG httpcore.connection close.started
2026-07-06 19:31:02,277 DEBUG httpcore.connection close.complete
2026-07-06 19:31:04,971 INFO app.layers.rec_engine RecEngine: conv=a50b9ad4-6f95-4844-b868-3558c3f03ca6 uni=ffa47477-7504-48b0-8e82-837da80aa646 gender=male candidates=[('GK Regency Suites', 100), ('Academia Residence', 80), ('Academia Seyrantepe Erkek Öğrenci Yurdu', 78)] → selected=GK Regency Suites
2026-07-06 19:31:06,601 DEBUG httpcore.connection connect_tcp.started host='localhost' port=8000 local_address=None timeout=5.0 socket_options=None
2026-07-06 19:31:06,604 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109362960>
2026-07-06 19:31:06,604 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:06,604 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:06,604 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:06,605 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:06,605 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:06,605 INFO app.main → POST /internal/infogatherer/callback
2026-07-06 19:31:08,506 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:31:08,566 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109376e70>
2026-07-06 19:31:08,566 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1075e43d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:31:08,631 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109376db0>
2026-07-06 19:31:08,632 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:08,632 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:08,632 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:08,632 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:08,633 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:08,940 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:31:08 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'1027'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"6cabc142823f57b496f5dbc35f54fa06"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'3e8f4678-0ad5-4059-8822-608b4484afe7'), (b'x-runtime', b'0.246094'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:31:08,941 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:31:08,941 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:08,941 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:08,941 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:08,941 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:08,941 DEBUG httpcore.connection close.started
2026-07-06 19:31:08,941 DEBUG httpcore.connection close.complete
2026-07-06 19:31:08,949 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:31:09,014 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1076e7080>
2026-07-06 19:31:09,014 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1075e6a50> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:31:09,082 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109377b00>
2026-07-06 19:31:09,082 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:09,082 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:09,082 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:09,083 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:09,083 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:09,296 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:31:09 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'409'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"3ad7b2f4dd6007f1428ec0edae70bc25"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'73692e46-0136-408b-86e2-4b7d5ef33e31'), (b'x-runtime', b'0.147211'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:31:09,296 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:31:09,297 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:09,297 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:09,297 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:09,297 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:09,298 DEBUG httpcore.connection close.started
2026-07-06 19:31:09,298 DEBUG httpcore.connection close.complete
2026-07-06 19:31:09,316 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:31:09,316 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:31:09,317 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:31:09,317 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:31:09,317 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content="Efendim GK Rezidans, Şişli/Osmanbey'de b" conv=52
2026-07-06 19:31:09,379 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109375cd0>
2026-07-06 19:31:09,379 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1075e62d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:31:09,446 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109376ae0>
2026-07-06 19:31:09,446 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:09,447 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:09,447 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:09,447 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:09,447 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:09,776 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:31:09,777 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:31:09,779 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:31:09 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'404'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"6aae8b41f27161340eae83f96a7c0b72"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'321be9f3-ad54-4fe6-85f4-0d24305d0f8d'), (b'x-runtime', b'0.249221'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:31:09,780 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:31:09,780 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:09,780 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:09,780 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:09,780 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:09,780 DEBUG httpcore.connection close.started
2026-07-06 19:31:09,781 DEBUG httpcore.connection close.complete
2026-07-06 19:31:09,795 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:31:09,795 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Başka herhangi bir sorunuz olursa her da' conv=52
2026-07-06 19:31:09,853 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:31:10,329 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:31:10,330 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:31:10,331 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:31:10,331 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Yakın zamanda şubemizi gezmeye gelmeyi d' conv=52
2026-07-06 19:31:10,929 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:31:11,605 DEBUG httpcore.http11 receive_response_headers.failed exception=ReadTimeout(TimeoutError())
2026-07-06 19:31:11,605 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:11,606 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:11,606 ERROR app.layers.rec_engine RecEngine: callback delivery failed for conversation a50b9ad4-6f95-4844-b868-3558c3f03ca6: 
2026-07-06 19:31:11,606 INFO app.background.rec_engine_ladder RecEngineLadder: idempotency_key=e2082c2b-67aa-4e8a-9e31-80a88d3d012d resolved as success on attempt 1
2026-07-06 19:31:12,009 INFO app.main ← POST /webhooks/chatwoot 200 2693ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:31:12,265 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:31:12,785 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:31:13,889 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:31:14,211 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:31:14,270 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109362510>
2026-07-06 19:31:14,270 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1076da7d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:31:14,334 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109362930>
2026-07-06 19:31:14,335 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:14,335 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:14,335 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:14,336 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:14,336 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:14,397 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=a50b9ad4-6f95-4844-b868-3558c3f03ca6
2026-07-06 19:31:14,518 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:31:14 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'117'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"015982ecaa7a6f4935d8f0444b03bb41"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'678f10e4-7608-4195-8392-f3ceb91147b7'), (b'x-runtime', b'0.122096'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:31:14,519 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/custom_attributes "HTTP/1.1 200 OK"
2026-07-06 19:31:14,520 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:14,520 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:14,520 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:14,520 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:14,520 DEBUG httpcore.connection close.started
2026-07-06 19:31:14,521 DEBUG httpcore.connection close.complete
2026-07-06 19:31:15,319 ERROR app.main ✗ POST /internal/infogatherer/callback UNHANDLED EXCEPTION after 8697ms
Traceback (most recent call last):
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 157, in call_next
    message = await recv_stream.receive()
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/anyio/streams/memory.py", line 132, in receive
    raise EndOfStream from None
anyio.EndOfStream

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/app/main.py", line 57, in request_diagnostics
    response = await call_next(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 163, in call_next
    raise app_exc
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 149, in coro
    await self.app(scope, receive_or_disconnect, send_no_error)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/middleware/exceptions.py", line 62, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/routing.py", line 715, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/routing.py", line 735, in app
    await route.handle(scope, receive, send)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/routing.py", line 288, in handle
    await self.app(scope, receive, send)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/routing.py", line 76, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/starlette/routing.py", line 73, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/fastapi/routing.py", line 301, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/fastapi/routing.py", line 212, in run_endpoint_function
    return await dependant.call(**values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/app/webhooks/internal.py", line 114, in rec_engine_callback
    await write_attributes_at_flow_completion(body.conversation_id, chatwoot_id)
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/app/tagassigner/attribute_resolver.py", line 71, in write_attributes_at_flow_completion
    await queries.mark_infogatherer_attribute_companions(
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/app/db/queries.py", line 772, in mark_infogatherer_attribute_companions
    await pool.execute(
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/asyncpg/pool.py", line 566, in execute
    return await con.execute(query, *args, timeout=timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/asyncpg/connection.py", line 352, in execute
    _, status, _ = await self._execute(
                   ^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/asyncpg/connection.py", line 1864, in _execute
    result, _ = await self.__execute(
                ^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/asyncpg/connection.py", line 1961, in __execute
    result, stmt = await self._do_execute(
                   ^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/cinarvarlik/Desktop/Univotel Chatbot/venv/lib/python3.12/site-packages/asyncpg/connection.py", line 2024, in _do_execute
    result = await executor(stmt, None)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "asyncpg/protocol/protocol.pyx", line 206, in bind_execute
asyncpg.exceptions.CheckViolationError: new row for relation "conversations" violates check constraint "conversations_ilgili_otel_set_by_check"
DETAIL:  Failing row contains (a50b9ad4-6f95-4844-b868-3558c3f03ca6, 52, 2026-07-06 16:30:04.468223+00, 2026-07-06 16:31:14.640614+00, null, null, completed, {}, ffa47477-7504-48b0-8e82-837da80aa646, male, {}, 8, 0, null, 905551839644, 2026-07-06 16:31:11.59868+00, 0, 0, GK Regency, null, null, null, null, 2026-07-06 16:31:10.312893+00, infoGatherer, null, 0, 2026-07-06 16:31:14.521402+00, infoGatherer, 2026-07-06 16:31:14.521402+00, infoGatherer, null, null, null, null, null).

2026-07-06 19:31:15,508 INFO app.main ← POST /webhooks/chatwoot 200 5732ms
2026-07-06 19:31:16,018 INFO app.main ← POST /webhooks/chatwoot 200 5689ms
2026-07-06 19:31:37,933 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:31:37,936 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:31:37,937 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:31:37,938 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='merhaba' conv=52
2026-07-06 19:31:38,490 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:31:39,563 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=728f7977-e246-4a36-805e-f266be7084d4
2026-07-06 19:31:40,644 INFO app.main ← POST /webhooks/chatwoot 200 2711ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:31:46,341 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:31:46,412 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109361580>
2026-07-06 19:31:46,413 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1097281d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:31:46,477 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1093606e0>
2026-07-06 19:31:46,478 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:31:46,479 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:31:46,479 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:31:46,479 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:31:46,479 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:31:46,788 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:31:46 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"9b6fd253b3f82eaf4250f146abb049cf"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'52ee025f-6bb6-45df-a644-cc2d94e45536'), (b'x-runtime', b'0.247988'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:31:46,789 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:31:46,789 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:31:46,789 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:31:46,790 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:31:46,790 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:31:46,790 DEBUG httpcore.connection close.started
2026-07-06 19:31:46,790 DEBUG httpcore.connection close.complete
2026-07-06 19:31:47,063 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:31:47,064 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:31:47,064 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:31:47,064 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-06 19:31:47,600 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:31:48,677 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=728f7977-e246-4a36-805e-f266be7084d4
2026-07-06 19:31:49,754 INFO app.main ← POST /webhooks/chatwoot 200 2691ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:32:01,023 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:32:01,025 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:32:01,025 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:32:01,026 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='itü ayazağa' conv=52
2026-07-06 19:32:01,562 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:32:02,640 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=728f7977-e246-4a36-805e-f266be7084d4
2026-07-06 19:32:03,717 INFO app.main ← POST /webhooks/chatwoot 200 2694ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:32:08,054 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:32:08,111 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1093606e0>
2026-07-06 19:32:08,112 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x10971f9d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:32:08,173 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x109361280>
2026-07-06 19:32:08,174 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:32:08,174 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:32:08,174 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:32:08,174 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:32:08,175 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:32:08,506 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:32:08 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"161e2b2bda4d0f7fad1850c5d055c2d5"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'20ab1bb7-5497-4729-ad94-d21a77748c36'), (b'x-runtime', b'0.271694'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:32:08,507 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-06 19:32:08,508 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:32:08,508 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:32:08,509 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:32:08,509 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:32:08,509 DEBUG httpcore.connection close.started
2026-07-06 19:32:08,509 DEBUG httpcore.connection close.complete
2026-07-06 19:32:08,774 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:32:08,775 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:32:08,776 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:32:08,776 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Kız öğrenci için mi konaklama arıyordunu' conv=52
2026-07-06 19:32:09,313 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:32:10,387 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=728f7977-e246-4a36-805e-f266be7084d4
2026-07-06 19:32:11,465 INFO app.main ← POST /webhooks/chatwoot 200 2691ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:32:17,125 INFO app.main → POST /webhooks/chatwoot
2026-07-06 19:32:17,147 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-06 19:32:17,149 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-06 19:32:17,150 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='fiyat ne' conv=52
2026-07-06 19:32:17,687 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-06 19:32:18,762 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=728f7977-e246-4a36-805e-f266be7084d4
2026-07-06 19:32:19,843 INFO app.main ← POST /webhooks/chatwoot 200 2720ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-06 19:32:22,011 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:32:22,072 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1076e7ef0>
2026-07-06 19:32:22,072 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x107617bd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:32:22,137 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1076e7b60>
2026-07-06 19:32:22,137 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'GET']>
2026-07-06 19:32:22,138 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:32:22,138 DEBUG httpcore.http11 send_request_body.started request=<Request [b'GET']>
2026-07-06 19:32:22,138 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:32:22,138 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'GET']>
2026-07-06 19:32:22,229 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:32:22 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'14'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"258153158e38e3291e3d48162225fcdb"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'b5c9f4a4-f179-472a-b211-53a923e644e7'), (b'x-runtime', b'0.028843'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:32:22,230 INFO httpx HTTP Request: GET https://marketinguni.app/api/v1/accounts/1/conversations/52/labels "HTTP/1.1 200 OK"
2026-07-06 19:32:22,231 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'GET']>
2026-07-06 19:32:22,231 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:32:22,231 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:32:22,231 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:32:22,232 DEBUG httpcore.connection close.started
2026-07-06 19:32:22,232 DEBUG httpcore.connection close.complete
2026-07-06 19:32:22,249 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-06 19:32:22,314 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x107621820>
2026-07-06 19:32:22,315 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1075e4f50> server_hostname='marketinguni.app' timeout=10.0
2026-07-06 19:32:22,392 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x10758e000>
2026-07-06 19:32:22,392 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-06 19:32:22,392 DEBUG httpcore.http11 send_request_headers.complete
2026-07-06 19:32:22,392 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-06 19:32:22,393 DEBUG httpcore.http11 send_request_body.complete
2026-07-06 19:32:22,393 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-06 19:32:22,616 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Mon, 06 Jul 2026 16:32:22 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'28'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"33be7bb5f6ba0e1c34da5021ab67bb2e"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'b2717b94-79ff-4ac8-89ea-3cad9a44b90e'), (b'x-runtime', b'0.158117'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-06 19:32:22,616 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/labels "HTTP/1.1 200 OK"
2026-07-06 19:32:22,616 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-06 19:32:22,616 DEBUG httpcore.http11 receive_response_body.complete
2026-07-06 19:32:22,617 DEBUG httpcore.http11 response_closed.started
2026-07-06 19:32:22,617 DEBUG httpcore.http11 response_closed.complete
2026-07-06 19:32:22,617 DEBUG httpcore.connection close.started
2026-07-06 19:32:22,617 DEBUG httpcore.connection close.complete
