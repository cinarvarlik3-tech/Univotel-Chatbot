"""
Dashboard JSON API (spec §5).

Read-only. Every route sits behind HTTP Basic (spec §3.5) via the router-level
dependency, so a new endpoint cannot accidentally ship unauthenticated.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from dashboard.api import derive, notes, queries, schemas
from dashboard.api.auth import require_dashboard_auth
from dashboard.api.config import get_dashboard_settings
from dashboard.api.sql import SORT_COLUMNS

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_dashboard_auth)],
)


def _stale_hours() -> int:
    return get_dashboard_settings().stale_hours


def _parse_date(value: Optional[str], *, end_of_day: bool) -> Optional[datetime]:
    """
    Accept a bare date or a full ISO timestamp.

    A bare `to=2026-07-22` means "through the end of that day" — treating it as
    midnight would silently exclude everything the user can see on that date.
    """
    if not value:
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed = datetime.fromisoformat(raw)
            parsed = datetime.combine(
                parsed.date(), time.max if end_of_day else time.min
            )
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _validate_enum(
    values: Optional[list[str]], allowed: list[str], field: str
) -> Optional[list[str]]:
    if not values:
        return None
    invalid = [v for v in values if v not in allowed]
    if invalid:
        raise HTTPException(
            status_code=400, detail=f"Invalid {field}: {', '.join(invalid)}"
        )
    return values


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@router.get("/meta", response_model=schemas.Meta)
async def get_meta() -> schemas.Meta:
    return schemas.Meta(
        stale_hours=_stale_hours(),
        flow_states=derive.ALL_FLOW_STATES,
        statuses=derive.ALL_STATUSES,
        log_levels=derive.ALL_LOG_LEVELS,
        operation_layers=derive.ALL_OPERATION_LAYERS,
        which_runs=derive.ALL_WHICH_RUNS,
        server_time=queries.utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@router.get("/infogatherer/conversations", response_model=schemas.ConversationList)
async def list_conversations(
    status: Optional[list[str]] = Query(default=None),
    flow_state: Optional[list[str]] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=200),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
    sort: str = Query(default="last_activity"),
    dir: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> schemas.ConversationList:
    if sort not in SORT_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort: {sort}. Allowed: {', '.join(SORT_COLUMNS)}",
        )
    if dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid dir: use asc or desc")

    result = await queries.list_conversations(
        stale_hours=_stale_hours(),
        statuses=_validate_enum(status, derive.ALL_STATUSES, "status"),
        flow_states=_validate_enum(flow_state, derive.ALL_FLOW_STATES, "flow_state"),
        q=q,
        date_from=_parse_date(date_from, end_of_day=False),
        date_to=_parse_date(date_to, end_of_day=True),
        sort=sort,
        direction=dir,
        limit=limit,
        offset=offset,
    )
    return schemas.ConversationList(**result)


@router.get(
    "/infogatherer/conversations/{cwid}", response_model=schemas.ConversationDetail
)
async def get_conversation(cwid: int) -> schemas.ConversationDetail:
    result = await queries.get_conversation(stale_hours=_stale_hours(), cwid=cwid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No conversation #{cwid}")
    return schemas.ConversationDetail(**result)


@router.get(
    "/infogatherer/conversations/{cwid}/logs", response_model=schemas.ConversationLogs
)
async def get_conversation_logs(cwid: int) -> schemas.ConversationLogs:
    result = await queries.get_conversation_logs(stale_hours=_stale_hours(), cwid=cwid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No conversation #{cwid}")
    return schemas.ConversationLogs(**result)


@router.get(
    "/infogatherer/conversations/{cwid}/messages",
    response_model=schemas.ConversationMessages,
)
async def get_conversation_messages(cwid: int) -> schemas.ConversationMessages:
    result = await queries.get_conversation_messages(
        stale_hours=_stale_hours(), cwid=cwid
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"No conversation #{cwid}")
    return schemas.ConversationMessages(**result)


# ---------------------------------------------------------------------------
# Notes (per-lead annotations — the dashboard's only write path)
# ---------------------------------------------------------------------------


def _conversation_ref_from_row(row: dict) -> schemas.ConversationRef:
    return schemas.ConversationRef(
        id=row["id"],
        chatwoot_conversation_id=row["chatwoot_conversation_id"],
        lead_name=row["lead_name"],
        status=row["status"],
        flow_state=row["flow_state"],
    )


@router.get(
    "/infogatherer/conversations/{cwid}/notes", response_model=schemas.NoteList
)
async def get_conversation_notes(
    cwid: int,
    note_type: Optional[str] = Query(default=None, alias="type"),
) -> schemas.NoteList:
    if note_type is not None and note_type not in notes.NOTE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid note type: {note_type}. Allowed: {', '.join(notes.NOTE_TYPES)}",
        )
    conversation = await queries.get_conversation(stale_hours=_stale_hours(), cwid=cwid)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"No conversation #{cwid}")
    rows = await notes.list_notes(
        conversation_uuid=conversation["id"], note_type=note_type
    )
    return schemas.NoteList(
        conversation=_conversation_ref_from_row(conversation),
        rows=[schemas.Note(**row) for row in rows],
    )


@router.post(
    "/infogatherer/conversations/{cwid}/notes",
    response_model=schemas.Note,
    status_code=201,
)
async def create_conversation_note(
    cwid: int,
    payload: schemas.NoteCreate = Body(...),
    author: str = Depends(require_dashboard_auth),
) -> schemas.Note:
    conversation_uuid = await notes.resolve_conversation_uuid(cwid)
    if conversation_uuid is None:
        raise HTTPException(status_code=404, detail=f"No conversation #{cwid}")
    row = await notes.create_note(
        conversation_uuid=conversation_uuid,
        note_type=payload.note_type,
        body=payload.body,
        author=author,
    )
    return schemas.Note(**row)


@router.patch("/infogatherer/notes/{note_id}", response_model=schemas.Note)
async def update_note(
    note_id: str,
    payload: schemas.NoteUpdate = Body(...),
) -> schemas.Note:
    row = await notes.set_note_resolved(note_id=note_id, resolved=payload.resolved)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No note {note_id}")
    return schemas.Note(**row)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/infogatherer/logs", response_model=schemas.LogList)
async def list_logs(
    conversation: Optional[int] = Query(default=None),
    log_level: Optional[list[str]] = Query(default=None),
    is_success: Optional[bool] = Query(default=None),
    operation_layer: Optional[str] = Query(default=None),
    which_run: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=200),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> schemas.LogList:
    result = await queries.list_logs(
        cwid=conversation,
        log_levels=_validate_enum(log_level, derive.ALL_LOG_LEVELS, "log_level"),
        is_success=is_success,
        operation_layer=(
            _validate_enum(
                [operation_layer], derive.ALL_OPERATION_LAYERS, "operation_layer"
            )[0]
            if operation_layer
            else None
        ),
        which_run=(
            _validate_enum([which_run], derive.ALL_WHICH_RUNS, "which_run")[0]
            if which_run
            else None
        ),
        q=q,
        date_from=_parse_date(date_from, end_of_day=False),
        date_to=_parse_date(date_to, end_of_day=True),
        limit=limit,
        offset=offset,
    )
    return schemas.LogList(**result)


@router.get("/infogatherer/logs/{log_id}", response_model=schemas.LogDetail)
async def get_log_detail(log_id: str) -> schemas.LogDetail:
    result = await queries.get_log_detail(stale_hours=_stale_hours(), log_id=log_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No log {log_id}")
    return schemas.LogDetail(**result)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@router.get("/infogatherer/stats/summary", response_model=schemas.StatsSummary)
async def get_stats_summary() -> schemas.StatsSummary:
    return schemas.StatsSummary(**await queries.get_stats_summary(stale_hours=_stale_hours()))


@router.get("/infogatherer/stats/breakdowns", response_model=schemas.Breakdowns)
async def get_breakdowns() -> schemas.Breakdowns:
    return schemas.Breakdowns(**await queries.get_breakdowns(stale_hours=_stale_hours()))


@router.get(
    "/infogatherer/stats/human-needed-triggers", response_model=schemas.TriggerList
)
async def get_human_needed_triggers(
    limit: int = Query(default=20, ge=1, le=100),
) -> schemas.TriggerList:
    return schemas.TriggerList(
        **await queries.get_human_needed_triggers(stale_hours=_stale_hours(), limit=limit)
    )
