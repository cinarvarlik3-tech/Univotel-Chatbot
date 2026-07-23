"""
TagAssigner full-context backfill (spec 024).

Pulls the complete Chatwoot transcript and upserts it into the local messages
table before a full-history run, so the Router never tags on partial context.
Idempotent: insert_message uses ON CONFLICT (chatwoot_message_id) DO NOTHING.

Backfill is invoked only on full-history runs (manual / scheduled / sweep).
Message-triggered incremental runs rely on live webhooks and must not backfill,
because backfilled rows get a new created_at and would skew the since filter.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.chatwoot_client import fetch_all_messages
from app.config import settings
from app.db import queries
from app.layers.automation_gate import is_automation_message

logger = logging.getLogger(__name__)

_SKIP_MESSAGE_TYPES = frozenset({2})


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of a Chatwoot transcript backfill (Spec 031 C4)."""

    ok: bool
    inserted: int


def _parse_chatwoot_timestamp(raw: Any) -> Optional[datetime]:
    """Normalize Chatwoot created_at (epoch seconds, ms, or ISO string) to UTC."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            return _parse_chatwoot_timestamp(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _map_message_type(chatwoot_type: Any) -> Optional[str]:
    """Map Chatwoot message_type int to local inbound/outbound; None = skip."""
    if chatwoot_type in (0, "incoming", "inbound"):
        return "inbound"
    if chatwoot_type in (1, "outgoing", "outbound", 3, "template"):
        return "outbound"
    if chatwoot_type in (2, "activity"):
        return None
    return "inbound"


def _resolve_sender_type(
    raw: dict,
    local_message_type: str,
) -> tuple[str, Optional[str], Optional[str]]:
    """Map Chatwoot sender to DB-allowed sender_type values."""
    sender = raw.get("sender") or {}
    sender_id = str(sender["id"]) if sender.get("id") is not None else None
    sender_name = sender.get("name")

    if local_message_type == "inbound":
        return "contact", sender_id, sender_name

    content = raw.get("content")
    if is_automation_message(content if isinstance(content, str) else None):
        return "automation", sender_id, sender_name

    if sender_id and str(sender_id) == str(settings.chatwoot_bot_agent_id):
        return "infoGatherer", sender_id, sender_name
    return "user", sender_id, sender_name


async def backfill_conversation_messages(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
) -> BackfillResult:
    """
    Fetch all Chatwoot messages and upsert missing ones into `messages`.
    Returns ok=False when Chatwoot fetch fails (Spec 031 fail-closed for InfoGatherer).
    """
    raw_messages = await fetch_all_messages(chatwoot_conversation_id)
    if raw_messages is None:
        logger.warning(
            "context_backfill: Chatwoot fetch failed for conversation %s (cwid=%d)",
            conversation_id, chatwoot_conversation_id,
        )
        return BackfillResult(ok=False, inserted=0)

    inserted = 0
    for raw in raw_messages:
        if raw.get("private"):
            continue

        chatwoot_message_id = raw.get("id")
        if chatwoot_message_id is None:
            continue

        cw_type = raw.get("message_type")
        if cw_type in _SKIP_MESSAGE_TYPES:
            continue

        local_type = _map_message_type(cw_type)
        if local_type is None:
            continue

        msg_id = int(chatwoot_message_id)
        if await queries.message_exists(msg_id):
            continue

        sender_type, sender_id, sender_name = _resolve_sender_type(raw, local_type)
        await queries.insert_message(
            conversation_id,
            msg_id,
            raw.get("content"),
            local_type,
            sender_type,
            sender_id,
            sender_name,
            is_private=False,
            sent_at=_parse_chatwoot_timestamp(raw.get("created_at")),
            advance_activity=False,
        )
        inserted += 1

    return BackfillResult(ok=True, inserted=inserted)
