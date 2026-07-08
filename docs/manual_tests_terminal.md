TEST-1: Flagged as AFTER ATTEMPTED FIX, the fix that was supposed to address the following: "Phrase gate being too strict, response to invalid university submission, response to invalid campus submission, protocol for when invalid submission is repeated." Terminal output is below;


ted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"a51da7beb5b682d2d4eae19cbab14f3b"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'dbe0d019-e8d7-46bb-9500-2d093b3f6c0d'), (b'x-runtime', b'0.296134'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:07:00,483 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:07:00,483 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:07:00,483 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:07:00,484 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:07:00,484 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:07:00,484 DEBUG httpcore.connection close.started
2026-07-05 18:07:00,485 DEBUG httpcore.connection close.complete
2026-07-05 18:07:00,820 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:07:00,821 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:07:00,822 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:07:00,822 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:07:01,458 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:07:02,596 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=858a7b23-fc6f-4eff-9e0e-e3965e9283e0
2026-07-05 18:07:03,811 INFO app.main ← POST /webhooks/chatwoot 200 2991ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:07:46,391 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:07:46,393 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:07:46,394 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:07:46,394 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='Merhaba, üniversiteme yakın yer arıyorum' conv=52
2026-07-05 18:07:47,054 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:07:48,229 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=c7ec9ed4-8621-431f-8959-64cf168b4377
2026-07-05 18:07:49,485 INFO app.main ← POST /webhooks/chatwoot 200 3094ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:07:54,112 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:07:54,174 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11038a8d0>
2026-07-05 18:07:54,175 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119c550> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:07:54,241 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x110388650>
2026-07-05 18:07:54,242 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:07:54,243 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:07:54,243 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:07:54,243 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:07:54,243 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:07:54,536 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:07:54 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"741257dd46c2c49449de4112befc2ac4"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'04a57e1b-2348-40d0-83de-ab4ca3ef57ae'), (b'x-runtime', b'0.231857'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:07:54,537 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:07:54,538 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:07:54,538 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:07:54,538 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:07:54,538 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:07:54,539 DEBUG httpcore.connection close.started
2026-07-05 18:07:54,539 DEBUG httpcore.connection close.complete
2026-07-05 18:07:54,827 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:07:54,828 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:07:54,829 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:07:54,829 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:07:55,387 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:07:56,505 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=c7ec9ed4-8621-431f-8959-64cf168b4377
2026-07-05 18:07:57,730 INFO app.main ← POST /webhooks/chatwoot 200 2903ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:09:02,775 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:02,780 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:02,796 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:02,797 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='konaklama arıyorum' conv=52
2026-07-05 18:09:03,914 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:05,057 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:06,180 INFO app.main ← POST /webhooks/chatwoot 200 3406ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:09:10,327 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:09:10,388 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126e090>
2026-07-05 18:09:10,388 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119c150> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:09:10,452 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126f560>
2026-07-05 18:09:10,453 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:09:10,453 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:09:10,453 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:09:10,453 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:09:10,453 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:09:10,800 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:09:10 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"e6858d5ccf413c3c13909994b2e867ba"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'6a9c1dd3-b792-4f9c-b86a-a0e9c13795a5'), (b'x-runtime', b'0.282977'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:09:10,801 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:09:10,802 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:09:10,802 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:09:10,802 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:09:10,802 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:09:10,802 DEBUG httpcore.connection close.started
2026-07-05 18:09:10,803 DEBUG httpcore.connection close.complete
2026-07-05 18:09:11,066 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:11,067 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:11,067 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:11,068 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:09:11,627 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:16,218 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:18,284 INFO app.main ← POST /webhooks/chatwoot 200 7219ms
2026-07-05 18:09:21,527 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:21,534 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:21,536 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:21,537 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='itü' conv=52
2026-07-05 18:09:22,096 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:23,312 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:24,518 INFO app.main ← POST /webhooks/chatwoot 200 3000ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:09:32,239 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:09:32,301 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126c440>
2026-07-05 18:09:32,301 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119fcd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:09:32,366 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126e2d0>
2026-07-05 18:09:32,367 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:09:32,367 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:09:32,368 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:09:32,368 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:09:32,368 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:09:32,665 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:09:32 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'431'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"ed8d4e37fb7cb1a2083b3039c5eb58a8"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'6906e773-4e19-4dbc-b4cf-75a664ed97b2'), (b'x-runtime', b'0.234433'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:09:32,666 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:09:32,666 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:09:32,667 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:09:32,667 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:09:32,667 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:09:32,667 DEBUG httpcore.connection close.started
2026-07-05 18:09:32,668 DEBUG httpcore.connection close.complete
2026-07-05 18:09:32,988 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:32,989 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:32,990 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:32,990 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Hangi İstanbul Teknik Üniversitesi kampü' conv=52
2026-07-05 18:09:33,654 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:34,884 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:36,084 INFO app.main ← POST /webhooks/chatwoot 200 3096ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:09:41,135 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:41,137 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:41,138 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:41,138 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='beşiktaş' conv=52
2026-07-05 18:09:41,743 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:42,914 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:44,034 INFO app.main ← POST /webhooks/chatwoot 200 2898ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:09:47,126 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:09:47,186 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126fa10>
2026-07-05 18:09:47,186 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11121b250> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:09:47,248 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126f950>
2026-07-05 18:09:47,248 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:09:47,249 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:09:47,249 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:09:47,249 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:09:47,249 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:09:47,760 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:09:47 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"c765f449afa0c6d7d615dc0c9a070bd8"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'a8bdcfab-1d15-457e-acca-a541193a4865'), (b'x-runtime', b'0.446652'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:09:47,761 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:09:47,761 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:09:47,761 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:09:47,761 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:09:47,762 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:09:47,762 DEBUG httpcore.connection close.started
2026-07-05 18:09:47,762 DEBUG httpcore.connection close.complete
2026-07-05 18:09:48,051 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:09:48,051 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:09:48,052 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:09:48,052 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Efendim kampüs ismini çıkaramadım, resmi' conv=52
2026-07-05 18:09:48,860 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:09:50,613 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:09:52,292 INFO app.main ← POST /webhooks/chatwoot 200 4241ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:10:00,841 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:10:00,842 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:10:00,844 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:10:00,845 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='taşkışla' conv=52
2026-07-05 18:10:01,383 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:10:02,558 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=e0235163-42b7-49c0-8a7a-ce0cfa6d47ac
2026-07-05 18:10:03,714 INFO app.main ← POST /webhooks/chatwoot 200 2873ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:11:21,004 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:11:21,006 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:11:21,007 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:11:21,007 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='merhaba' conv=52
2026-07-05 18:11:21,584 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:11:22,814 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:11:23,976 INFO app.main ← POST /webhooks/chatwoot 200 2972ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:11:28,978 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:11:29,056 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126c0e0>
2026-07-05 18:11:29,056 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119df50> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:11:29,125 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126d460>
2026-07-05 18:11:29,125 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:11:29,126 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:11:29,126 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:11:29,126 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:11:29,126 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:11:29,502 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:11:29 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"055426c86e80dea10816e55aa1132270"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'cd380a95-1250-48d3-a674-f0158539ec8f'), (b'x-runtime', b'0.309641'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:11:29,503 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:11:29,504 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:11:29,504 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:11:29,504 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:11:29,505 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:11:29,505 DEBUG httpcore.connection close.started
2026-07-05 18:11:29,506 DEBUG httpcore.connection close.complete
2026-07-05 18:11:29,835 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:11:29,836 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:11:29,836 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:11:29,837 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:11:30,401 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:11:31,617 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:11:32,752 INFO app.main ← POST /webhooks/chatwoot 200 2917ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:11:35,540 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:11:35,542 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:11:35,543 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:11:35,544 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='itü' conv=52
2026-07-05 18:11:36,129 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:11:37,355 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:11:38,584 INFO app.main ← POST /webhooks/chatwoot 200 3044ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:11:44,247 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:11:44,306 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126de20>
2026-07-05 18:11:44,306 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119ccd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:11:44,367 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126ed20>
2026-07-05 18:11:44,368 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:11:44,369 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:11:44,369 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:11:44,369 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:11:44,369 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:11:44,674 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:11:44 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'431'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"325890d8fd64a1b9fa8490614e00f98d"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'476813d3-cd2b-4fbc-a4ee-23042b6fc169'), (b'x-runtime', b'0.245692'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:11:44,676 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:11:44,676 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:11:44,676 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:11:44,677 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:11:44,677 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:11:44,678 DEBUG httpcore.connection close.started
2026-07-05 18:11:44,678 DEBUG httpcore.connection close.complete
2026-07-05 18:11:45,010 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:11:45,010 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:11:45,011 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:11:45,011 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Hangi İstanbul Teknik Üniversitesi kampü' conv=52
2026-07-05 18:11:45,624 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:11:46,852 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:11:47,989 INFO app.main ← POST /webhooks/chatwoot 200 2980ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:12:01,047 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:12:01,049 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:12:01,050 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:12:01,050 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='beşiktaş' conv=52
2026-07-05 18:12:01,727 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:12:02,954 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:12:04,159 INFO app.main ← POST /webhooks/chatwoot 200 3112ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:12:06,539 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:12:06,598 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f0470>
2026-07-05 18:12:06,598 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1103bebd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:12:06,659 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f05f0>
2026-07-05 18:12:06,660 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:12:06,660 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:12:06,660 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:12:06,660 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:12:06,661 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:12:06,987 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:12:07 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"fdebded5e35ac8045ac8d1e11ec6c68a"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'4cf89dfd-de85-4cbf-beab-60cd7c42027f'), (b'x-runtime', b'0.267430'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:12:06,988 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:12:06,988 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:12:06,988 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:12:06,988 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:12:06,988 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:12:06,988 DEBUG httpcore.connection close.started
2026-07-05 18:12:06,989 DEBUG httpcore.connection close.complete
2026-07-05 18:12:07,328 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:12:07,328 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:12:07,329 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:12:07,330 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Efendim kampüs ismini çıkaramadım, resmi' conv=52
2026-07-05 18:12:07,895 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:12:09,053 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:12:10,225 INFO app.main ← POST /webhooks/chatwoot 200 2897ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:12:25,109 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:12:25,112 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:12:25,113 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:12:25,113 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='Maslak' conv=52
2026-07-05 18:12:25,678 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:12:26,892 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:12:28,121 INFO app.main ← POST /webhooks/chatwoot 200 3012ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:12:35,035 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:12:35,112 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f3110>
2026-07-05 18:12:35,112 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1112187d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:12:35,192 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f30e0>
2026-07-05 18:12:35,192 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:12:35,193 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:12:35,193 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:12:35,193 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:12:35,193 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:12:35,562 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:12:35 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"bb2ff22a21b706e05a17b4fb9b601b80"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'b21fbf7d-1bb5-493d-855d-9a28a62dd57a'), (b'x-runtime', b'0.301371'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:12:35,563 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:12:35,563 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:12:35,563 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:12:35,563 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:12:35,563 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:12:35,564 DEBUG httpcore.connection close.started
2026-07-05 18:12:35,564 DEBUG httpcore.connection close.complete
2026-07-05 18:12:36,161 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:12:36,162 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:12:36,167 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:12:36,168 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Kız öğrenci için mi konaklama arıyordunu' conv=52
2026-07-05 18:12:36,737 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:12:37,880 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=25277e28-2771-432d-814f-0b22e3a22873
2026-07-05 18:12:39,017 INFO app.main ← POST /webhooks/chatwoot 200 2855ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:22,969 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:22,971 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:22,972 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:22,973 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='merhaba' conv=52
2026-07-05 18:13:23,654 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:24,811 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:13:26,013 INFO app.main ← POST /webhooks/chatwoot 200 3043ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:30,435 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:13:30,497 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f1a00>
2026-07-05 18:13:30,497 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119ddd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:13:30,558 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x1103f1b80>
2026-07-05 18:13:30,559 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:13:30,560 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:13:30,560 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:13:30,560 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:13:30,560 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:13:30,902 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:13:30 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"1be639184ca3741b3557220a08873470"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'b1b771dd-d421-4f29-bc8b-c84389b0b153'), (b'x-runtime', b'0.281449'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:13:30,904 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:13:30,904 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:13:30,904 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:13:30,904 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:13:30,905 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:13:30,905 DEBUG httpcore.connection close.started
2026-07-05 18:13:30,906 DEBUG httpcore.connection close.complete
2026-07-05 18:13:31,336 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:31,336 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:31,337 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:31,337 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:13:31,906 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:33,042 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:13:34,207 INFO app.main ← POST /webhooks/chatwoot 200 2870ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:36,779 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:36,780 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:36,782 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:36,782 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='itü' conv=52
2026-07-05 18:13:37,381 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:38,611 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:13:39,767 INFO app.main ← POST /webhooks/chatwoot 200 2988ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:44,661 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:44,661 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:44,661 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:44,661 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='Merhabalar Univotel!\n\nacademic house kad' conv=954
2026-07-05 18:13:44,661 INFO app.webhooks.chatwoot WEBHOOK: TESTING_MODE — contact not on allowlist, ignoring (status=ignored)
2026-07-05 18:13:44,662 INFO app.main ← POST /webhooks/chatwoot 200 1ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:45,447 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:13:45,507 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126fbc0>
2026-07-05 18:13:45,507 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119f650> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:13:45,573 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126fb00>
2026-07-05 18:13:45,574 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:13:45,575 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:13:45,575 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:13:45,575 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:13:45,575 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:13:45,885 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:13:45 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'431'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"6b4db0a5a4377d4b63181927b8a86dd6"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'1a1cf30a-cc88-4784-a2c2-c2e4bd7ff546'), (b'x-runtime', b'0.217171'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:13:45,886 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:13:45,887 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:13:45,887 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:13:45,887 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:13:45,887 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:13:45,887 DEBUG httpcore.connection close.started
2026-07-05 18:13:45,888 DEBUG httpcore.connection close.complete
2026-07-05 18:13:46,184 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:46,185 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:46,186 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:46,186 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Hangi İstanbul Teknik Üniversitesi kampü' conv=52
2026-07-05 18:13:46,804 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:48,023 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:13:49,239 INFO app.main ← POST /webhooks/chatwoot 200 3055ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:51,925 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:51,926 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:51,927 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:51,927 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='beşiktaş' conv=52
2026-07-05 18:13:52,491 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:53,668 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:13:54,852 INFO app.main ← POST /webhooks/chatwoot 200 2927ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:13:57,377 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:13:57,441 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126e9f0>
2026-07-05 18:13:57,441 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x1111a1550> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:13:57,503 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126f980>
2026-07-05 18:13:57,504 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:13:57,505 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:13:57,505 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:13:57,505 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:13:57,505 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:13:57,835 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:13:57 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"4c2f71b860fa1688b0fb63a86b4398d0"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'5630bc4b-9b0f-4090-b8a4-27c302cc002a'), (b'x-runtime', b'0.222259'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:13:57,836 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:13:57,836 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:13:57,837 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:13:57,837 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:13:57,837 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:13:57,838 DEBUG httpcore.connection close.started
2026-07-05 18:13:57,838 DEBUG httpcore.connection close.complete
2026-07-05 18:13:58,081 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:13:58,082 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:13:58,083 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:13:58,083 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Efendim kampüs ismini çıkaramadım, resmi' conv=52
2026-07-05 18:13:58,684 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:13:59,840 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:14:01,039 INFO app.main ← POST /webhooks/chatwoot 200 2958ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:14:04,026 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:14:04,027 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:14:04,027 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:14:04,027 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='kadıköy' conv=52
2026-07-05 18:14:05,213 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:14:06,394 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=5f148767-e66e-446d-a69c-33d18bd6a1e4
2026-07-05 18:14:07,696 INFO app.main ← POST /webhooks/chatwoot 200 3670ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:17:38,843 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:17:38,845 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:17:38,846 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:17:38,846 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='merhaba' conv=52
2026-07-05 18:17:39,414 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:17:46,734 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=17fc146e-1f89-41db-9964-a842bc6fcda6
2026-07-05 18:17:48,884 INFO app.main ← POST /webhooks/chatwoot 200 10042ms
2026-07-05 18:17:55,661 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:17:55,742 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126f590>
2026-07-05 18:17:55,742 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119fcd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:17:55,807 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126db20>
2026-07-05 18:17:55,808 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:17:55,808 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:17:55,808 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:17:55,809 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:17:55,809 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:17:56,256 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:17:56 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"2ac676f9b4f423db69c3482826b358d5"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'd3c49e3b-f6a6-4261-858e-97f1757841bc'), (b'x-runtime', b'0.369477'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:17:56,258 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:17:56,258 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:17:56,258 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:17:56,259 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:17:56,259 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:17:56,259 DEBUG httpcore.connection close.started
2026-07-05 18:17:56,260 DEBUG httpcore.connection close.complete
2026-07-05 18:17:56,670 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:17:56,671 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:17:56,671 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:17:56,672 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:17:57,280 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:17:58,459 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=17fc146e-1f89-41db-9964-a842bc6fcda6
2026-07-05 18:17:59,609 INFO app.main ← POST /webhooks/chatwoot 200 2939ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:18:04,039 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:18:04,040 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:18:04,040 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:18:04,040 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='TÖÜ' conv=52
2026-07-05 18:18:04,623 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:18:05,858 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=17fc146e-1f89-41db-9964-a842bc6fcda6
2026-07-05 18:18:07,111 INFO app.main ← POST /webhooks/chatwoot 200 3072ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:18:12,966 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:18:13,026 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126fb60>
2026-07-05 18:18:13,027 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119ddd0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:18:13,089 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126dcd0>
2026-07-05 18:18:13,089 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:18:13,090 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:18:13,090 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:18:13,090 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:18:13,090 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:18:13,459 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:18:13 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"56cd4b5e7298cd29483ddfdf8a91b62d"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'4ecebd1e-d2de-4b8e-a2e6-961e89a22206'), (b'x-runtime', b'0.285040'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:18:13,460 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:18:13,460 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:18:13,460 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:18:13,460 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:18:13,460 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:18:13,461 DEBUG httpcore.connection close.started
2026-07-05 18:18:13,461 DEBUG httpcore.connection close.complete
2026-07-05 18:18:13,872 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:18:13,872 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:18:13,873 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:18:13,873 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Kız öğrenci için mi konaklama arıyordunu' conv=52
2026-07-05 18:18:14,485 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:18:15,619 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=17fc146e-1f89-41db-9964-a842bc6fcda6
2026-07-05 18:18:16,840 INFO app.main ← POST /webhooks/chatwoot 200 2968ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:21:52,900 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:21:52,902 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:21:52,903 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:21:52,904 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='Merhabalar 👋\nBenim için en iyi yurt hang' conv=955
2026-07-05 18:21:52,904 INFO app.webhooks.chatwoot WEBHOOK: TESTING_MODE — contact not on allowlist, ignoring (status=ignored)
2026-07-05 18:21:52,904 INFO app.main ← POST /webhooks/chatwoot 200 5ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:22:16,319 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:22:16,321 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:22:16,321 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:22:16,322 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='merhaba' conv=52
2026-07-05 18:22:18,064 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:22:19,263 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=b1c445aa-bc10-46cc-a39e-7eda99d4cafe
2026-07-05 18:22:20,363 INFO app.main ← POST /webhooks/chatwoot 200 4044ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:22:24,502 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:22:24,567 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126db20>
2026-07-05 18:22:24,567 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119e150> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:22:24,632 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126ffb0>
2026-07-05 18:22:24,633 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:22:24,634 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:22:24,634 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:22:24,635 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:22:24,635 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:22:25,062 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:22:25 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'437'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"9461841e7204b5c8020ae24dd933adb2"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'd762b0f2-7472-45be-a708-43e07dc75580'), (b'x-runtime', b'0.317752'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:22:25,063 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:22:25,063 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:22:25,064 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:22:25,064 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:22:25,064 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:22:25,064 DEBUG httpcore.connection close.started
2026-07-05 18:22:25,065 DEBUG httpcore.connection close.complete
2026-07-05 18:22:25,369 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:22:25,370 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:22:25,371 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:22:25,371 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Size daha iyi yardımcı olabilmek adına h' conv=52
2026-07-05 18:22:26,186 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:22:27,830 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=b1c445aa-bc10-46cc-a39e-7eda99d4cafe
2026-07-05 18:22:29,670 INFO app.main ← POST /webhooks/chatwoot 200 4301ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:22:39,300 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:22:39,303 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:22:39,305 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:22:39,305 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='TÖÜ' conv=52
2026-07-05 18:22:39,844 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:22:41,066 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=b1c445aa-bc10-46cc-a39e-7eda99d4cafe
2026-07-05 18:22:42,366 INFO app.main ← POST /webhooks/chatwoot 200 3066ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:22:49,919 DEBUG httpcore.connection connect_tcp.started host='marketinguni.app' port=443 local_address=None timeout=10.0 socket_options=None
2026-07-05 18:22:49,976 DEBUG httpcore.connection connect_tcp.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126f860>
2026-07-05 18:22:49,976 DEBUG httpcore.connection start_tls.started ssl_context=<ssl.SSLContext object at 0x11119e6d0> server_hostname='marketinguni.app' timeout=10.0
2026-07-05 18:22:50,036 DEBUG httpcore.connection start_tls.complete return_value=<httpcore._backends.anyio.AnyIOStream object at 0x11126fc80>
2026-07-05 18:22:50,037 DEBUG httpcore.http11 send_request_headers.started request=<Request [b'POST']>
2026-07-05 18:22:50,037 DEBUG httpcore.http11 send_request_headers.complete
2026-07-05 18:22:50,037 DEBUG httpcore.http11 send_request_body.started request=<Request [b'POST']>
2026-07-05 18:22:50,037 DEBUG httpcore.http11 send_request_body.complete
2026-07-05 18:22:50,037 DEBUG httpcore.http11 receive_response_headers.started request=<Request [b'POST']>
2026-07-05 18:22:50,455 DEBUG httpcore.http11 receive_response_headers.complete return_value=(b'HTTP/1.1', 200, b'OK', [(b'Server', b'nginx/1.18.0 (Ubuntu)'), (b'Date', b'Sun, 05 Jul 2026 15:22:50 GMT'), (b'Content-Type', b'application/json; charset=utf-8'), (b'Content-Length', b'415'), (b'Connection', b'keep-alive'), (b'x-frame-options', b'SAMEORIGIN'), (b'x-xss-protection', b'0'), (b'x-content-type-options', b'nosniff'), (b'x-download-options', b'noopen'), (b'x-permitted-cross-domain-policies', b'none'), (b'referrer-policy', b'strict-origin-when-cross-origin'), (b'etag', b'W/"5da526cd598261c9fc711c5f584d35fe"'), (b'cache-control', b'max-age=0, private, must-revalidate'), (b'x-request-id', b'efe5ee43-6c92-4081-a7d3-08ca0e00fe95'), (b'x-runtime', b'0.309843'), (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains')])
2026-07-05 18:22:50,456 INFO httpx HTTP Request: POST https://marketinguni.app/api/v1/accounts/1/conversations/52/messages "HTTP/1.1 200 OK"
2026-07-05 18:22:50,457 DEBUG httpcore.http11 receive_response_body.started request=<Request [b'POST']>
2026-07-05 18:22:50,457 DEBUG httpcore.http11 receive_response_body.complete
2026-07-05 18:22:50,457 DEBUG httpcore.http11 response_closed.started
2026-07-05 18:22:50,457 DEBUG httpcore.http11 response_closed.complete
2026-07-05 18:22:50,458 DEBUG httpcore.connection close.started
2026-07-05 18:22:50,458 DEBUG httpcore.connection close.complete
2026-07-05 18:22:50,721 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:22:50,722 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:22:50,723 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:22:50,723 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='outgoing' content='Kız öğrenci için mi konaklama arıyordunu' conv=52
2026-07-05 18:22:51,275 INFO app.webhooks.chatwoot WEBHOOK: upserting conversation cw_id=52 phone='905551839644'
2026-07-05 18:22:52,401 INFO app.webhooks.chatwoot WEBHOOK: conversation upserted id=b1c445aa-bc10-46cc-a39e-7eda99d4cafe
2026-07-05 18:22:53,556 INFO app.main ← POST /webhooks/chatwoot 200 2835ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
2026-07-05 18:23:27,335 INFO app.main → POST /webhooks/chatwoot
2026-07-05 18:23:27,338 INFO app.webhooks.chatwoot WEBHOOK: received request, verifying HMAC
2026-07-05 18:23:27,340 INFO app.webhooks.chatwoot WEBHOOK: HMAC OK
2026-07-05 18:23:27,340 INFO app.webhooks.chatwoot WEBHOOK: event='message_created' private=False message_type='incoming' content='Merhabalar Univotel!\n\nAcademic House Kad' conv=955
2026-07-05 18:23:27,340 INFO app.webhooks.chatwoot WEBHOOK: TESTING_MODE — contact not on allowlist, ignoring (status=ignored)
2026-07-05 18:23:27,341 INFO app.main ← POST /webhooks/chatwoot 200 6ms
INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
