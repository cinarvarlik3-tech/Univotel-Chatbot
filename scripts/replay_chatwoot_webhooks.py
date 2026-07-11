"""
Replay recent Chatwoot incoming messages as signed message_created webhooks.

Fetches incoming messages from the Chatwoot API, selects the N most recent,
replays them oldest-first to the local webhook endpoint. LIVE_TESTING_LIMIT
gates new conversation creation automatically — excess new conversations are
dropped with 200 (no error retry loop).

Usage:
    python3 scripts/replay_chatwoot_webhooks.py [--limit 100] [--webhook-url http://127.0.0.1:8000/webhooks/chatwoot]
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app.config import settings

_BASE = settings.chatwoot_base_url.rstrip("/")
_ACCOUNT = settings.chatwoot_account_id
_HEADERS = {"api_access_token": settings.chatwoot_api_token}
_INCOMING_TYPES = {0, "incoming", "inbound", "0"}


@dataclass
class IncomingMessage:
    conversation_id: int
    message_id: int
    content: str
    created_at: float
    phone_number: Optional[str]
    sender_id: Optional[str]
    sender_name: Optional[str]
    private: bool


def _parse_created_at(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        ts = float(raw)
        return ts / 1000.0 if ts > 1e12 else ts
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            return _parse_created_at(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _is_incoming(message: dict) -> bool:
    if message.get("private"):
        return False
    mt = message.get("message_type")
    return mt in _INCOMING_TYPES or str(mt) == "0"


def _phone_from_conversation(conv: dict) -> Optional[str]:
    meta = conv.get("meta") or {}
    sender = meta.get("sender") or {}
    phone = sender.get("phone_number")
    if phone:
        return str(phone)
    contact = conv.get("contact") or {}
    phone = contact.get("phone_number")
    return str(phone) if phone else None


def _build_webhook_payload(msg: IncomingMessage) -> dict:
    return {
        "event": "message_created",
        "created_at": int(msg.created_at) if msg.created_at else int(time.time()),
        "message": {
            "id": msg.message_id,
            "content": msg.content,
            "message_type": "incoming",
            "private": msg.private,
            "created_at": int(msg.created_at) if msg.created_at else int(time.time()),
            "sender": {
                "id": msg.sender_id,
                "name": msg.sender_name,
            },
        },
        "conversation": {
            "id": msg.conversation_id,
            "meta": {
                "sender": {
                    "phone_number": msg.phone_number,
                },
            },
        },
        "contact": {
            "phone_number": msg.phone_number,
        },
    }


def _sign_body(body: bytes) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    signed_payload = timestamp.encode() + b"." + body
    digest = hmac.new(
        settings.chatwoot_webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return timestamp, f"sha256={digest}"


async def _fetch_conversations_page(client: httpx.AsyncClient, page: int) -> list[dict]:
    url = f"{_BASE}/api/v1/accounts/{_ACCOUNT}/conversations"
    resp = await client.get(url, headers=_HEADERS, params={"status": "all", "page": page})
    resp.raise_for_status()
    data = resp.json()
    payload = data.get("data", {}).get("payload")
    if payload is None:
        payload = data.get("payload", [])
    return payload if isinstance(payload, list) else []


async def _fetch_messages(client: httpx.AsyncClient, conversation_id: int) -> list[dict]:
    url = f"{_BASE}/api/v1/accounts/{_ACCOUNT}/conversations/{conversation_id}/messages"
    resp = await client.get(url, headers=_HEADERS)
    if resp.status_code != 200:
        return []
    payload = resp.json().get("payload", [])
    return payload if isinstance(payload, list) else []


def _messages_from_conv_dict(conv: dict) -> list[dict]:
    """Prefer embedded messages on the conversation list payload; fetch only if empty."""
    embedded = conv.get("messages")
    return embedded if isinstance(embedded, list) and embedded else []


def _append_incoming_from_messages(
    collected: list[IncomingMessage],
    conv: dict,
    messages: list[dict],
    seen_msg_ids: set[int],
) -> None:
    conv_id = int(conv["id"])
    phone = _phone_from_conversation(conv)
    for m in messages:
        if not _is_incoming(m):
            continue
        msg_id = m.get("id")
        if msg_id is None:
            continue
        msg_id = int(msg_id)
        if msg_id in seen_msg_ids:
            continue
        seen_msg_ids.add(msg_id)
        sender = m.get("sender") or {}
        collected.append(IncomingMessage(
            conversation_id=conv_id,
            message_id=msg_id,
            content=m.get("content") or "",
            created_at=_parse_created_at(m.get("created_at")),
            phone_number=phone,
            sender_id=str(sender.get("id")) if sender.get("id") is not None else None,
            sender_name=sender.get("name"),
            private=bool(m.get("private", False)),
        ))


async def _collect_incoming_messages(
    client: httpx.AsyncClient,
    *,
    target_count: int,
    max_pages: int = 15,
) -> list[IncomingMessage]:
    """
    Scan conversation pages for incoming traffic. Uses embedded messages first;
    fetches /messages only when the list payload has none. Stops early once
    target_count messages are collected.
    """
    collected: list[IncomingMessage] = []
    seen_msg_ids: set[int] = set()
    fetch_queue: list[tuple[dict, int]] = []

    for page in range(1, max_pages + 1):
        convs = await _fetch_conversations_page(client, page)
        if not convs:
            break
        print(f"  page {page}: {len(convs)} conversation(s)")
        for conv in convs:
            embedded = _messages_from_conv_dict(conv)
            incoming_embedded = [m for m in embedded if _is_incoming(m)]
            if incoming_embedded:
                _append_incoming_from_messages(collected, conv, embedded, seen_msg_ids)
            else:
                fetch_queue.append((conv, int(conv["id"])))
            if len(collected) >= target_count:
                break
        if len(collected) >= target_count:
            break

    if len(collected) < target_count and fetch_queue:
        print(f"  fetching full message history for {len(fetch_queue)} conversation(s)...")
        sem = asyncio.Semaphore(8)

        async def _fetch_one(conv: dict, conv_id: int) -> None:
            async with sem:
                messages = await _fetch_messages(client, conv_id)
            _append_incoming_from_messages(collected, conv, messages, seen_msg_ids)

        await asyncio.gather(*[_fetch_one(c, cid) for c, cid in fetch_queue])

    return collected


async def _replay(
    messages: list[IncomingMessage],
    webhook_url: str,
    pause_seconds: float,
) -> dict[str, int]:
    stats = {
        "posted": 0,
        "duplicate": 0,
        "live_testing_limit_reached": 0,
        "ignored": 0,
        "other": 0,
        "errors": 0,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, msg in enumerate(messages, start=1):
            body = json.dumps(_build_webhook_payload(msg), ensure_ascii=False).encode()
            timestamp, signature = _sign_body(body)
            headers = {
                "Content-Type": "application/json",
                "X-Chatwoot-Timestamp": timestamp,
                "X-Chatwoot-Signature": signature,
            }
            try:
                resp = await client.post(webhook_url, content=body, headers=headers)
                stats["posted"] += 1
                if resp.status_code != 200:
                    stats["errors"] += 1
                    print(f"  [{i}/{len(messages)}] conv={msg.conversation_id} HTTP {resp.status_code}")
                    continue
                status = resp.json().get("status", "unknown")
                if status in stats:
                    stats[status] += 1
                else:
                    stats["other"] += 1
                if i % 10 == 0 or i == len(messages):
                    print(f"  replayed {i}/{len(messages)} (last status={status})")
            except httpx.HTTPError as exc:
                stats["errors"] += 1
                print(f"  [{i}/{len(messages)}] conv={msg.conversation_id} error: {exc}")
            if pause_seconds > 0:
                await asyncio.sleep(pause_seconds)

    return stats


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Replay Chatwoot incoming webhooks")
    parser.add_argument("--limit", type=int, default=100, help="Max incoming messages to replay")
    parser.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8000/webhooks/chatwoot",
        help="Local webhook endpoint",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.15,
        help="Seconds between webhook posts (debounce-friendly)",
    )
    parser.add_argument(
        "--wait-after",
        type=float,
        default=8.0,
        help="Seconds to wait after replay for background/debounce processing",
    )
    args = parser.parse_args()

    print(f"Fetching incoming messages from Chatwoot ({_BASE})...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        all_incoming = await _collect_incoming_messages(
            client, target_count=max(args.limit * 2, args.limit)
        )

    if not all_incoming:
        print("No incoming messages found.")
        return

    all_incoming.sort(key=lambda m: m.created_at, reverse=True)
    selected = all_incoming[: args.limit]
    selected.sort(key=lambda m: m.created_at)

    unique_convs = len({m.conversation_id for m in selected})
    print(
        f"Found {len(all_incoming)} incoming message(s) total; "
        f"replaying {len(selected)} (oldest-first), "
        f"spanning {unique_convs} conversation(s)."
    )
    print(f"Target webhook: {args.webhook_url}")
    print(f"LIVE_TESTING_MODE={settings.live_testing_mode} LIVE_TESTING_LIMIT={settings.live_testing_limit}")

    stats = await _replay(selected, args.webhook_url, args.pause)
    print("Replay stats:", stats)

    if args.wait_after > 0:
        print(f"Waiting {args.wait_after}s for debounce/background processing...")
        await asyncio.sleep(args.wait_after)

    from app.db.client import create_pool, close_pool
    from app.db import queries

    await create_pool()
    try:
        total = await queries.count_live_testing_conversations()
        print(f"conversations in DB after replay: {total}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
