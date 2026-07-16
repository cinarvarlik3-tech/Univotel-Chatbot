"""
Import conversation histories from CRM lead_messages into the chatbot DB.

Used for TagAssigner accuracy testing: seeds conversations + messages locally
so tag sweep can run against known transcripts without relying on live webhooks.

Usage:
    python3 scripts/import_crm_conversations.py --data /path/to/messages.json
    ./scripts/tag importConvo --10   # live CRM fetch (preferred)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import asyncpg

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import settings  # noqa: E402
from app.tagassigner.crm_import import (  # noqa: E402
    ConversationSeed,
    import_conversations,
)

# Legacy fallback when importing from a static JSON export (no live CRM connection).
CONVERSATIONS = [
    {"chatwoot_conversation_id": 1137, "lead_phone": "05421374898"},
    {"chatwoot_conversation_id": 459, "lead_phone": "05050166184"},
    {"chatwoot_conversation_id": 371, "lead_phone": "05513532396"},
    {"chatwoot_conversation_id": 559, "lead_phone": "+923332009521"},
    {"chatwoot_conversation_id": 621, "lead_phone": "05527545615"},
    {"chatwoot_conversation_id": 460, "lead_phone": "05079101535"},
    {"chatwoot_conversation_id": 796, "lead_phone": "+923391105012"},
    {"chatwoot_conversation_id": 294, "lead_phone": "05396948740"},
    {"chatwoot_conversation_id": 867, "lead_phone": "+994509894622"},
    {"chatwoot_conversation_id": 801, "lead_phone": "05324226096"},
    {"chatwoot_conversation_id": 528, "lead_phone": "05385997821"},
    {"chatwoot_conversation_id": 389, "lead_phone": "05464233565"},
    {"chatwoot_conversation_id": 766, "lead_phone": "05068861642"},
    {"chatwoot_conversation_id": 1091, "lead_phone": "05052540319"},
    {"chatwoot_conversation_id": 647, "lead_phone": "05300227017"},
    {"chatwoot_conversation_id": 70, "lead_phone": "05418647519"},
    {"chatwoot_conversation_id": 700, "lead_phone": "05078014168"},
    {"chatwoot_conversation_id": 1149, "lead_phone": "05411501575"},
    {"chatwoot_conversation_id": 98, "lead_phone": "05396093825"},
    {"chatwoot_conversation_id": 896, "lead_phone": "05325613064"},
]


def _load_payload(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and "result" in payload:
        inner = payload["result"]
        if isinstance(inner, str):
            return json.loads(inner)
        return inner
    return payload


async def _import_from_file(data: list[dict[str, Any]]) -> None:
    conversations = [
        ConversationSeed(
            chatwoot_conversation_id=int(c["chatwoot_conversation_id"]),
            lead_phone=str(c["lead_phone"]),
        )
        for c in CONVERSATIONS
    ]
    conn = await asyncpg.connect(settings.database_url)
    try:
        result = await import_conversations(conn, conversations, data)
        conv_count = await conn.fetchval("SELECT count(*) FROM conversations")
        msg_count = await conn.fetchval("SELECT count(*) FROM messages")
        print(
            f"\nDone: {conv_count} conversations, {msg_count} messages "
            f"({result.messages_inserted} inserted)"
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import CRM lead_messages into chatbot DB")
    parser.add_argument("--data", required=True, help="JSON file with lead_messages array")
    args = parser.parse_args()
    data = _load_payload(args.data)
    asyncio.run(_import_from_file(data))


if __name__ == "__main__":
    main()
