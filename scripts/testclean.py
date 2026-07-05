"""
testclean — deletes a conversation and everything FK-connected to it, for repeat
manual testing against the same Chatwoot conversation without manual cleanup.

Usage:
    testclean <conversation_uuid> [table_name]
    testclean --<chatwoot_conversation_id> [table_name]

The first argument may be either the conversation's internal uuid or its
Chatwoot conversation id (a plain integer, e.g. "testclean --52"). When an
integer is given, it is resolved to the conversation's uuid via
conversations.chatwoot_conversation_id before any deletion happens.

If table_name is omitted, every row across all dependent tables is deleted,
followed by the conversation row itself. If table_name is given, only that
table's rows for the conversation are deleted (the conversation row is kept).

Deletion order matters because of FK constraints:
    tag_assigner_queue  -> conversations, tag_assigner_runs
    tag_assigner_logs   -> conversations, tag_assigner_runs
    tag_assigner_runs   -> conversations
    rec_engine_logs     -> conversations
    messages            -> conversations, chatbot_logs
    chatbot_logs        -> conversations
    conversations.last_processed_log_id -> chatbot_logs.id  (circular FK)

The circular FK is broken by nulling conversations.last_processed_log_id
before chatbot_logs rows are deleted.
"""
from __future__ import annotations
import asyncio
import sys
import uuid as uuid_lib

import asyncpg

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import settings  # noqa: E402

VALID_TABLES = [
    "tag_assigner_queue",
    "tag_assigner_logs",
    "tag_assigner_runs",
    "rec_engine_logs",
    "messages",
    "chatbot_logs",
]

# Order respects FK dependencies — children before parents.
_DELETE_ORDER = [
    ("tag_assigner_queue", "DELETE FROM tag_assigner_queue WHERE conversation_id = $1"),
    ("tag_assigner_logs", "DELETE FROM tag_assigner_logs WHERE conversation_id = $1"),
    ("tag_assigner_runs", "DELETE FROM tag_assigner_runs WHERE conversation_id = $1"),
    ("rec_engine_logs", "DELETE FROM rec_engine_logs WHERE conversation_id = $1"),
    ("messages", "DELETE FROM messages WHERE conversation_id = $1"),
    ("chatbot_logs", "DELETE FROM chatbot_logs WHERE conversation_id = $1"),
]


async def _run(
    conversation_id: str | None, chatwoot_conversation_id: int | None, table: str | None
) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        if chatwoot_conversation_id is not None:
            conversation_id = await conn.fetchval(
                "SELECT id FROM conversations WHERE chatwoot_conversation_id = $1",
                chatwoot_conversation_id,
            )
            if conversation_id is None:
                print(f"No conversation found with chatwoot_conversation_id {chatwoot_conversation_id}")
                return
            conversation_id = str(conversation_id)
        else:
            exists = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1", conversation_id
            )
            if not exists:
                print(f"No conversation found with id {conversation_id}")
                return

        async with conn.transaction():
            if table:
                _, query = next(p for p in _DELETE_ORDER if p[0] == table)
                result = await conn.execute(query, conversation_id)
                print(f"{table}: {result}")
                return

            # Break the circular FK before chatbot_logs rows are removed.
            await conn.execute(
                "UPDATE conversations SET last_processed_log_id = NULL WHERE id = $1",
                conversation_id,
            )

            for name, query in _DELETE_ORDER:
                result = await conn.execute(query, conversation_id)
                print(f"{name}: {result}")

            result = await conn.execute(
                "DELETE FROM conversations WHERE id = $1", conversation_id
            )
            print(f"conversations: {result}")
    finally:
        await conn.close()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(
            'Please provide a uuid or chatwoot conversation id in the following '
            'format "testclean --uuid" or "testclean --<chatwoot_conversation_id>".'
        )
        sys.exit(1)

    raw_id = args[0].lstrip("-")
    table = args[1].lstrip("-") if len(args) > 1 else None

    conversation_id: str | None = None
    chatwoot_conversation_id: int | None = None

    if raw_id.isdigit():
        chatwoot_conversation_id = int(raw_id)
    else:
        try:
            uuid_lib.UUID(raw_id)
        except ValueError:
            print(
                'Please provide a uuid or chatwoot conversation id in the following '
                'format "testclean --uuid" or "testclean --<chatwoot_conversation_id>".'
            )
            sys.exit(1)
        conversation_id = raw_id

    if table and table not in VALID_TABLES:
        print(f"Unknown table {table!r}. Valid tables: {', '.join(VALID_TABLES)}")
        sys.exit(1)

    asyncio.run(_run(conversation_id, chatwoot_conversation_id, table))


if __name__ == "__main__":
    main()
