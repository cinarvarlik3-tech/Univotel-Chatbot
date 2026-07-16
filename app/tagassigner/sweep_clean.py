"""
Bulk reset for TagAssigner re-testing: clear Chatwoot labels/attributes, then wipe
all conversation-linked rows from the database.

Used by `tag sweepclean --confirm`. Per-conversation cleanup remains in testclean.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.chatwoot_client import set_custom_attributes, set_labels
from app.config import (
    TAGASSIGNER_ATTRIBUTE_KEYS,
    TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES,
)
from app.db.client import get_pool

logger = logging.getLogger(__name__)

_CHATWOOT_CLEAR_DELAY_SECONDS = 0.25

# Sentinel values TagAssigner treats as empty/unknown (matches payload_builder context).
_CHATWOOT_CLEAR_ATTRIBUTES: dict[str, str] = {
    "university": "bilinmiyor",
    "ogrenci_cinsiyet": "Bilinmiyor",
    "oda_tiipi": "boş",
    "ilgili_otel": "boş",
    "tasinma_tarihi": "boş",
    "kayip_nedeni": "boş",
    "butce": "boş",
}

# FK-safe bulk delete order (children before parents).
_DB_WIPE_STEPS: list[tuple[str, str]] = [
    ("tag_assigner_queue", "DELETE FROM tag_assigner_queue"),
    ("tag_assigner_logs", "DELETE FROM tag_assigner_logs"),
    ("tag_assigner_runs", "DELETE FROM tag_assigner_runs"),
    ("rec_engine_logs", "DELETE FROM rec_engine_logs"),
    ("messages", "DELETE FROM messages"),
    ("chatbot_logs", "DELETE FROM chatbot_logs"),
    ("conversations", "DELETE FROM conversations"),
]


@dataclass
class SweepCleanResult:
    """Summary of a sweepclean run."""

    conversations_found: int = 0
    chatwoot_cleared: int = 0
    chatwoot_failed: int = 0
    db_deleted: dict[str, int] = field(default_factory=dict)


def _chatwoot_clear_payload() -> dict[str, str]:
    """Build the attribute dict written to every Chatwoot conversation."""
    keys = set(TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES) | set(TAGASSIGNER_ATTRIBUTE_KEYS)
    return {key: _CHATWOOT_CLEAR_ATTRIBUTES.get(key, "boş") for key in keys}


async def run_sweep_clean(*, skip_chatwoot: bool = False) -> SweepCleanResult:
    """
    Clear labels/attributes on every known Chatwoot conversation, then delete all
    conversation-linked database rows (messages, logs, queue, runs, conversations).

    Conversations are recreated on the next inbound webhook. Re-run `tag sweep`
    after new traffic (or webhook replay) to repopulate local state.
    """
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, chatwoot_conversation_id FROM conversations ORDER BY created_at"
    )
    result = SweepCleanResult(conversations_found=len(rows))

    if not skip_chatwoot:
        clear_attrs = _chatwoot_clear_payload()
        for row in rows:
            cw_id = row["chatwoot_conversation_id"]
            labels_ok = (await set_labels(cw_id, [])).ok
            attrs_ok = (await set_custom_attributes(cw_id, clear_attrs)).ok
            if labels_ok and attrs_ok:
                result.chatwoot_cleared += 1
            else:
                result.chatwoot_failed += 1
                logger.warning(
                    "sweepclean: Chatwoot clear failed for conversation %s (chatwoot=%s)",
                    row["id"],
                    cw_id,
                )
            await asyncio.sleep(_CHATWOOT_CLEAR_DELAY_SECONDS)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE conversations SET last_processed_log_id = NULL"
            )
            for table, query in _DB_WIPE_STEPS:
                delete_result = await conn.execute(query)
                # asyncpg returns e.g. "DELETE 42"
                count = int(delete_result.split()[-1]) if delete_result else 0
                result.db_deleted[table] = count

    logger.info(
        "sweepclean: conversations=%d chatwoot_cleared=%d chatwoot_failed=%d db=%s",
        result.conversations_found,
        result.chatwoot_cleared,
        result.chatwoot_failed,
        result.db_deleted,
    )
    return result
