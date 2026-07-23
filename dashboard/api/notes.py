"""
Dashboard notes — the one place the dashboard writes to the database.

Kept deliberately separate from queries.py / sql.py, which document themselves as
strictly read-only. Notes are dashboard-owned annotations on a conversation (a
"lead"); they never touch conversations / messages / Chatwoot. Two types:

  'log'          — rendered in the conversation's Logs panel as a log entry.
  'conversation' — rendered in the transcript like a Chatwoot private note.

Every value travels as a bound parameter. Reads that support the yellow-dot flag
degrade gracefully if migration 033 has not been applied yet (see
`unresolved_conversation_ids`) so a forgotten migration slows nothing and, in
particular, never breaks the read-only conversations list.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import asyncpg

from app.db.client import get_pool
from dashboard.api import derive

NOTE_TYPES = ("log", "conversation")
MAX_BODY_LENGTH = 5000

# chatwoot_conversation_id rides along on every row so the client never needs a
# second round-trip to map a note back to its conversation.
_NOTE_COLUMNS = """
  n.id, n.conversation_id, n.note_type, n.body, n.resolved, n.author,
  n.created_at, n.updated_at, n.resolved_at, c.chatwoot_conversation_id
"""


def _note_row(record: Any) -> dict[str, Any]:
    return {
        "id": str(record["id"]),
        "conversation_id": str(record["conversation_id"]),
        "chatwoot_conversation_id": record["chatwoot_conversation_id"],
        "note_type": record["note_type"],
        "body": record["body"],
        "resolved": bool(record["resolved"]),
        "author": record["author"],
        "created_at": derive.to_iso(record["created_at"]),
        "updated_at": derive.to_iso(record["updated_at"]),
        "resolved_at": derive.to_iso(record["resolved_at"]),
    }


async def resolve_conversation_uuid(cwid: int) -> Optional[str]:
    """Map a Chatwoot conversation id to the internal UUID, or None if unknown."""
    pool = get_pool()
    record = await pool.fetchrow(
        "SELECT id FROM conversations WHERE chatwoot_conversation_id = $1", cwid
    )
    return str(record["id"]) if record else None


async def list_notes(
    *, conversation_uuid: str, note_type: Optional[str] = None
) -> list[dict[str, Any]]:
    pool = get_pool()
    params: list[Any] = [uuid.UUID(conversation_uuid)]
    clause = "n.conversation_id = $1"
    if note_type:
        params.append(note_type)
        clause += " AND n.note_type = $2"
    records = await pool.fetch(
        f"""
        SELECT {_NOTE_COLUMNS}
          FROM dashboard_notes n
          JOIN conversations c ON c.id = n.conversation_id
         WHERE {clause}
         ORDER BY n.created_at ASC, n.id ASC
        """,
        *params,
    )
    return [_note_row(r) for r in records]


async def create_note(
    *, conversation_uuid: str, note_type: str, body: str, author: Optional[str]
) -> dict[str, Any]:
    pool = get_pool()
    record = await pool.fetchrow(
        f"""
        WITH inserted AS (
          INSERT INTO dashboard_notes (conversation_id, note_type, body, author)
          VALUES ($1, $2, $3, $4)
          RETURNING *
        )
        SELECT {_NOTE_COLUMNS}
          FROM inserted n
          JOIN conversations c ON c.id = n.conversation_id
        """,
        uuid.UUID(conversation_uuid),
        note_type,
        body,
        author,
    )
    return _note_row(record)


async def set_note_resolved(
    *, note_id: str, resolved: bool
) -> Optional[dict[str, Any]]:
    """Toggle a note's resolved flag. Returns None if the note id does not exist."""
    pool = get_pool()
    try:
        note_uuid = uuid.UUID(note_id)
    except ValueError:
        return None
    record = await pool.fetchrow(
        f"""
        WITH updated AS (
          UPDATE dashboard_notes
             SET resolved = $2,
                 resolved_at = CASE WHEN $2 THEN now() ELSE NULL END,
                 updated_at = now()
           WHERE id = $1
          RETURNING *
        )
        SELECT {_NOTE_COLUMNS}
          FROM updated n
          JOIN conversations c ON c.id = n.conversation_id
        """,
        note_uuid,
        resolved,
    )
    return _note_row(record) if record else None


async def unresolved_conversation_ids(conversation_ids: list[str]) -> set[str]:
    """
    Subset of the given conversation UUIDs that have at least one unresolved note.

    Drives the yellow dot on the conversations table. Returns an empty set — never
    raises — when dashboard_notes does not exist yet, so the conversations list
    keeps working before migration 033 is applied.
    """
    if not conversation_ids:
        return set()
    pool = get_pool()
    try:
        records = await pool.fetch(
            """
            SELECT DISTINCT conversation_id
              FROM dashboard_notes
             WHERE resolved = false
               AND conversation_id = ANY($1::uuid[])
            """,
            [uuid.UUID(cid) for cid in conversation_ids],
        )
    except asyncpg.UndefinedTableError:
        return set()
    return {str(r["conversation_id"]) for r in records}
