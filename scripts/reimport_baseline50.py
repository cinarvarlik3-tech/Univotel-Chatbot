"""
Re-import the baseline 50 conversations used in the 19-07-2026 accuracy report.

Fetches the exact same Chatwoot conversation IDs from the CRM DB and seeds them
into the chatbot DB, so a fresh sweep produces an apples-to-apples comparison
against the baseline accuracy numbers.

Usage (after sweepclean):
    source venv/bin/activate
    python3 scripts/reimport_baseline50.py
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

import asyncpg

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import settings  # noqa: E402
from app.tagassigner.crm_import import (  # noqa: E402
    ConversationSeed,
    import_conversations,
    map_crm_message,
    normalize_phone,
    parse_ts,
)

# ── The exact 50 Chatwoot conversation IDs from the baseline report ──────────
# Source: accuracy_optimization/tagassigner/results/19-07-2026_19.28_50_tagassigner-accuracy.md
BASELINE_CW_IDS: list[int] = [
    140, 183, 230, 242, 270, 417, 447, 511, 513, 529,
    559, 588, 644, 650, 652, 656, 684, 707, 716, 729,
    811, 869, 884, 886, 900, 920, 923, 924, 937, 970,
    977, 988, 1020, 1050, 1055, 1067, 1113, 1126, 1134, 1138,
    1154, 1156, 1168, 1261, 1279, 1300, 1312, 1328, 1359, 1362,
]

# ── SQL: fetch messages for specific Chatwoot conversation IDs ───────────────
_SELECT_BY_CW_IDS_SQL = """
WITH target AS (
    SELECT
        l.chatwoot_conversation_id,
        l.lead_phone
    FROM leads l
    WHERE l.chatwoot_conversation_id = ANY($1::int[])
      AND l.is_deleted = false
    GROUP BY l.chatwoot_conversation_id, l.lead_phone
)
SELECT
    lm.chatwoot_message_id,
    lm.chatwoot_conversation_id,
    lm.message_type,
    lm.content,
    lm.sender_type,
    lm.sender_id,
    lm.sender_name,
    lm.is_private,
    lm.created_at,
    lm.direction,
    l.lead_phone
FROM lead_messages lm
INNER JOIN leads l ON l.uuid = lm.lead_uuid
INNER JOIN target t ON t.chatwoot_conversation_id = l.chatwoot_conversation_id
WHERE l.is_deleted = false
ORDER BY lm.chatwoot_conversation_id, lm.created_at
"""


async def fetch_specific_crm_messages(
    crm_conn: asyncpg.Connection,
    cw_ids: list[int],
) -> tuple[list[ConversationSeed], list[dict[str, Any]]]:
    """Fetch CRM messages for specific Chatwoot conversation IDs."""
    rows = await crm_conn.fetch(_SELECT_BY_CW_IDS_SQL, cw_ids)
    if not rows:
        return [], []

    seeds: list[ConversationSeed] = []
    seen_cw: set[int] = set()
    data: list[dict[str, Any]] = []

    for row in rows:
        record = dict(row)
        cwid = int(record["chatwoot_conversation_id"])
        if cwid not in seen_cw:
            seen_cw.add(cwid)
            seeds.append(
                ConversationSeed(
                    chatwoot_conversation_id=cwid,
                    lead_phone=str(record.get("lead_phone") or ""),
                )
            )
        data.append(record)

    return seeds, data


async def main() -> None:
    crm_url = settings.crm_database_url
    if not crm_url or not crm_url.strip():
        print("ERROR: CRM_DATABASE_URL is not set in .env")
        sys.exit(1)

    crm_conn = await asyncpg.connect(crm_url.strip())
    chatbot_conn = await asyncpg.connect(settings.database_url)

    try:
        print(f"Fetching {len(BASELINE_CW_IDS)} specific conversations from CRM...")
        seeds, message_rows = await fetch_specific_crm_messages(crm_conn, BASELINE_CW_IDS)

        if not seeds:
            print("ERROR: No matching conversations found in CRM DB.")
            sys.exit(1)

        found_ids = {s.chatwoot_conversation_id for s in seeds}
        missing = sorted(set(BASELINE_CW_IDS) - found_ids)
        if missing:
            print(f"WARNING: {len(missing)} conversations not found in CRM: {missing}")

        print(
            f"Found {len(seeds)}/{len(BASELINE_CW_IDS)} conversations, "
            f"{len(message_rows)} total message rows"
        )
        print(f"CW IDs: {', '.join(str(s.chatwoot_conversation_id) for s in seeds)}")

        result = await import_conversations(
            chatbot_conn, seeds, message_rows, wipe_existing=True
        )

        conv_count = await chatbot_conn.fetchval("SELECT count(*) FROM conversations")
        msg_count = await chatbot_conn.fetchval("SELECT count(*) FROM messages")
        print(
            f"\nDone: {conv_count} conversations, {msg_count} messages "
            f"({result.messages_inserted} inserted)"
        )
    finally:
        await crm_conn.close()
        await chatbot_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
