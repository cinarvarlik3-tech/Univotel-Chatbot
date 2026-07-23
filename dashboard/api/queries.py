"""
Read-only database access for the dashboard.

Reuses the bot's asyncpg pool (app.db.client.get_pool) — no second pool, no second
process. Every statement here is a SELECT.

Filter values always travel as bound parameters. The only interpolated fragments
are sort column and direction, both resolved through whitelists before use.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.client import get_pool
from dashboard.api import derive, notes, sql

# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------


def _conversation_row(record: Any, stale_hours: int) -> dict[str, Any]:
    """Turn one `base`/`counted` row into the API shape, applying §4.4 and §4.5."""
    status = record["status"]

    reason, reason_source, signature = derive.resolve_failure_reason(
        status=status,
        flow_state=record["flow_state"],
        stale_hours=stale_hours,
        failure_log_explanation=record["failure_log_explanation"],
        failure_log_internal_class=record["failure_log_internal_class"],
        failure_log_status_code=record["failure_log_status_code"],
        rec_engine_status=record["rec_engine_status"],
        rec_engine_status_code=record["rec_engine_status_code"],
        rec_engine_network_status=record["rec_engine_network_status"],
    )

    origin = derive.origin_flow_state(
        status=status,
        flow_state=record["flow_state"],
        from_state=record["failure_log_from_state"],
        signature=signature,
    )

    return {
        "id": str(record["id"]),
        "chatwoot_conversation_id": record["chatwoot_conversation_id"],
        "lead_name": record["lead_name"],
        "lead_name_is_fallback": record["lead_name_is_fallback"],
        "flow_state": record["flow_state"],
        "status": status,
        "origin_flow_state": origin,
        "failure_reason": reason,
        "reason_source": reason_source,
        "failure_signature": signature,
        "message_count": record["message_count"],
        "log_count": record["log_count"],
        # Set by the caller from a single batched lookup (notes table); defaults
        # false so a conversation with no notes — or a DB without migration 033 —
        # simply carries no dot.
        "has_unresolved_note": False,
        "created_at": derive.to_iso(record["created_at"]),
        "last_activity_at": derive.to_iso(record["last_activity_at"]),
        "takeover_at": derive.to_iso(record["takeover_at"]),
        "escalated_at": derive.to_iso(record["escalated_at"]),
        "escalated_at_exact": record["escalated_at_exact"],
    }


def _conversation_ref(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "chatwoot_conversation_id": row["chatwoot_conversation_id"],
        "lead_name": row["lead_name"],
        "status": row["status"],
        "flow_state": row["flow_state"],
    }


def _log_row(record: Any, *, lead_name: Optional[str] = None) -> dict[str, Any]:
    signature, label = derive.failure_signature(
        internal_class=record["internal_class"],
        explanation=record["explanation"],
        status_code=record["status_code"],
    )
    return {
        "id": str(record["id"]),
        "derived": False,
        "created_at": derive.to_iso(record["created_at"]),
        "conversation_id": str(record["conversation_id"]) if record["conversation_id"] else None,
        "chatwoot_conversation_id": (
            record["chatwoot_conversation_id"]
            if "chatwoot_conversation_id" in record.keys()
            else None
        ),
        "lead_name": lead_name,
        "operation_layer": record["operation_layer"],
        "which_run": record["which_run"],
        "operation_label": derive.operation_label(
            operation_layer=record["operation_layer"],
            which_run=record["which_run"],
            internal_class=record["internal_class"],
        ),
        "log_level": record["log_level"],
        "is_success": record["is_success"],
        "log_status": derive.log_status(
            is_success=record["is_success"], log_level=record["log_level"]
        ),
        "status_code": record["status_code"],
        "internal_class": record["internal_class"],
        "signature": signature,
        "signature_label": label,
        "from_state": record["from_state"],
        "to_state": record["to_state"],
        "network_status": record["network_status"],
        "database_status": record["database_status"],
        "explanation": record["explanation"],
    }


def _message_row(record: Any) -> dict[str, Any]:
    return {
        "id": str(record["id"]),
        "chatwoot_message_id": record["chatwoot_message_id"],
        "direction": record["message_type"],
        "bubble": derive.bubble_kind(
            message_type=record["message_type"],
            sender_type=record["sender_type"],
            is_private=record["is_private"],
        ),
        "sender_type": record["sender_type"],
        "sender_id": record["sender_id"] if "sender_id" in record.keys() else None,
        "sender_name": record["sender_name"],
        "content": record["content"],
        "is_private": bool(record["is_private"]),
        "sent_at": derive.to_iso(record["sent_at"]),
        "created_at": derive.to_iso(record["created_at"]),
    }


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def _build_conversation_filters(
    *,
    statuses: Optional[list[str]],
    flow_states: Optional[list[str]],
    q: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    next_param: int,
) -> tuple[str, list[Any], int]:
    """Compose the WHERE clause. $1 is always stale_hours, so params start at $2."""
    clauses: list[str] = []
    params: list[Any] = []
    p = next_param

    if statuses:
        clauses.append(f"status = ANY(${p}::text[])")
        params.append(statuses)
        p += 1

    if flow_states:
        clauses.append(f"flow_state = ANY(${p}::text[])")
        params.append(flow_states)
        p += 1

    if q:
        term = q.strip()
        digits = "".join(ch for ch in term if ch.isdigit())
        # Match the derived name, the phone (digits-only, matching how it is
        # stored), and the Chatwoot id when the query is numeric.
        sub = [f"lead_name ILIKE ${p}", f"COALESCE(contact_phone,'') ILIKE ${p}"]
        params.append(f"%{term}%")
        p += 1
        if digits:
            sub.append(f"COALESCE(contact_phone,'') ILIKE ${p}")
            params.append(f"%{digits}%")
            p += 1
            sub.append(f"chatwoot_conversation_id::text ILIKE ${p}")
            params.append(f"%{digits}%")
            p += 1
        clauses.append("(" + " OR ".join(sub) + ")")

    if date_from:
        clauses.append(f"created_at >= ${p}")
        params.append(date_from)
        p += 1

    if date_to:
        clauses.append(f"created_at <= ${p}")
        params.append(date_to)
        p += 1

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params, p


async def list_conversations(
    *,
    stale_hours: int,
    statuses: Optional[list[str]] = None,
    flow_states: Optional[list[str]] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort: str = "last_activity",
    direction: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    pool = get_pool()

    where_sql, filter_params, next_param = _build_conversation_filters(
        statuses=statuses,
        flow_states=flow_states,
        q=q,
        date_from=date_from,
        date_to=date_to,
        next_param=2,
    )

    query = sql.conversations_query(
        where_sql=where_sql,
        sort=sort,
        direction=direction,
        limit_param=next_param,
        offset_param=next_param + 1,
    )

    records = await pool.fetch(query, stale_hours, *filter_params, limit, offset)
    total = records[0]["total_count"] if records else 0

    rows = [_conversation_row(r, stale_hours) for r in records]
    flagged = await notes.unresolved_conversation_ids([row["id"] for row in rows])
    for row in rows:
        row["has_unresolved_note"] = row["id"] in flagged

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": rows,
    }


async def get_conversation(
    *, stale_hours: int, cwid: int
) -> Optional[dict[str, Any]]:
    pool = get_pool()
    record = await pool.fetchrow(sql.CONVERSATION_DETAIL_QUERY, stale_hours, cwid)
    if not record:
        return None

    row = _conversation_row(record, stale_hours)
    flagged = await notes.unresolved_conversation_ids([row["id"]])
    row["has_unresolved_note"] = row["id"] in flagged
    row.update(
        {
            "university_id": str(record["university_id"]) if record["university_id"] else None,
            "university_name": record["university_name"],
            "gender": record["gender"],
            "ilgili_otel": record["ilgili_otel"],
            "labels": list(record["labels"] or []),
            "contact_phone": record["contact_phone"],
            "bot_enabled": record["bot_enabled"],
            "infogatherer_abstain_reason": record["infogatherer_abstain_reason"],
            "reprompt_count": record["reprompt_count"] or 0,
            "clarification_attempt": record["clarification_attempt"] or 0,
            "auto_run_count": record["auto_run_count"] or 0,
            "manual_run_count": record["manual_run_count"] or 0,
        }
    )
    return row


# ---------------------------------------------------------------------------
# Derived log events (spec §4.10)
# ---------------------------------------------------------------------------


def _derived_event(
    *,
    kind: str,
    conversation_id: str,
    at: Optional[str],
    log_status: str,
    label: str,
    explanation: str,
) -> dict[str, Any]:
    return {
        "id": f"derived:{kind}:{conversation_id}",
        "derived": True,
        "created_at": at,
        "conversation_id": conversation_id,
        "chatwoot_conversation_id": None,
        "lead_name": None,
        "operation_layer": "infoGatherer",
        "which_run": None,
        "operation_label": label,
        "log_level": None,
        "is_success": False,
        "log_status": log_status,
        "status_code": None,
        "internal_class": kind,
        "signature": kind,
        "signature_label": derive.signature_label(kind),
        "from_state": None,
        "to_state": None,
        "network_status": None,
        "database_status": None,
        "explanation": explanation,
    }


async def _build_derived_events(
    conversation: dict[str, Any], *, stale_hours: int
) -> list[dict[str, Any]]:
    """
    Synthesise the three conversation-level events that write no chatbot_logs row.

    Without these the per-conversation log list has silent gaps exactly where the
    interesting thing happened.
    """
    pool = get_pool()
    events: list[dict[str, Any]] = []
    cid = conversation["id"]
    status = conversation["status"]

    if status == derive.STATUS_HUMAN_INTERRUPTION and conversation["takeover_at"]:
        agent = await pool.fetchrow(sql.TAKEOVER_MESSAGE_QUERY, uuid.UUID(cid))
        who = (agent["sender_name"] if agent else None) or "A human agent"
        events.append(
            _derived_event(
                kind="human_takeover",
                conversation_id=cid,
                at=conversation["takeover_at"],
                log_status=derive.STATUS_HUMAN_INTERRUPTION,
                label="infoGatherer · human takeover",
                explanation=f"{who} sent an outbound message; InfoGatherer stopped.",
            )
        )

    if status == derive.STATUS_HUMAN_NEEDED and not conversation["escalated_at_exact"]:
        events.append(
            _derived_event(
                kind="recengine_escalation",
                conversation_id=cid,
                at=conversation["escalated_at"],
                log_status=derive.STATUS_HUMAN_NEEDED,
                label="recEngine · escalation",
                explanation=(
                    conversation["failure_reason"]
                    or "Escalated to human_needed with no log row written."
                ),
            )
        )

    if status == derive.STATUS_FAILED and conversation["failure_signature"] == "stalled":
        events.append(
            _derived_event(
                kind="stalled",
                conversation_id=cid,
                at=conversation["last_activity_at"],
                log_status=derive.STATUS_FAILED,
                label="infoGatherer · stalled",
                explanation=conversation["failure_reason"] or "Stalled — no reply.",
            )
        )

    return events


async def get_conversation_logs(
    *, stale_hours: int, cwid: int
) -> Optional[dict[str, Any]]:
    pool = get_pool()
    conversation = await get_conversation(stale_hours=stale_hours, cwid=cwid)
    if not conversation:
        return None

    records = await pool.fetch(
        sql.CONVERSATION_LOGS_QUERY, uuid.UUID(conversation["id"])
    )
    rows = [_log_row(r, lead_name=conversation["lead_name"]) for r in records]
    for row in rows:
        row["chatwoot_conversation_id"] = cwid

    derived = await _build_derived_events(conversation, stale_hours=stale_hours)
    for row in derived:
        row["chatwoot_conversation_id"] = cwid
        row["lead_name"] = conversation["lead_name"]

    merged = rows + derived
    # Undated rows sort last rather than crashing the comparison.
    merged.sort(key=lambda r: (r["created_at"] is None, r["created_at"] or ""))

    return {"conversation": _conversation_ref(conversation), "rows": merged}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


async def list_logs(
    *,
    cwid: Optional[int] = None,
    log_levels: Optional[list[str]] = None,
    is_success: Optional[bool] = None,
    operation_layer: Optional[str] = None,
    which_run: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    pool = get_pool()
    clauses: list[str] = []
    params: list[Any] = []
    p = 1

    if cwid is not None:
        clauses.append(f"c.chatwoot_conversation_id = ${p}")
        params.append(cwid)
        p += 1
    if log_levels:
        clauses.append(f"l.log_level = ANY(${p}::text[])")
        params.append(log_levels)
        p += 1
    if is_success is not None:
        clauses.append(f"l.is_success IS NOT DISTINCT FROM ${p}")
        params.append(is_success)
        p += 1
    if operation_layer:
        clauses.append(f"l.operation_layer = ${p}")
        params.append(operation_layer)
        p += 1
    if which_run:
        clauses.append(f"l.which_run = ${p}")
        params.append(which_run)
        p += 1
    if q:
        clauses.append(
            f"(COALESCE(l.explanation,'') ILIKE ${p} OR COALESCE(l.internal_class,'') ILIKE ${p})"
        )
        params.append(f"%{q.strip()}%")
        p += 1
    if date_from:
        clauses.append(f"l.created_at >= ${p}")
        params.append(date_from)
        p += 1
    if date_to:
        clauses.append(f"l.created_at <= ${p}")
        params.append(date_to)
        p += 1

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    query = sql.logs_query(where_sql=where_sql, limit_param=p, offset_param=p + 1)
    records = await pool.fetch(query, *params, limit, offset)
    total = records[0]["total_count"] if records else 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [_log_row(r) for r in records],
    }


_PAYLOAD_NOTE = (
    "Request/response payloads are not captured for this log. "
    "See DASHBOARD_SPEC.md §12 for the planned capture."
)


async def get_log_detail(*, stale_hours: int, log_id: str) -> Optional[dict[str, Any]]:
    pool = get_pool()

    if log_id.startswith("derived:"):
        return await _get_derived_log_detail(stale_hours=stale_hours, log_id=log_id)

    try:
        log_uuid = uuid.UUID(log_id)
    except ValueError:
        return None

    record = await pool.fetchrow(sql.LOG_DETAIL_QUERY, log_uuid)
    if not record:
        return None

    row = _log_row(record)
    conversation_ref = None
    context = {"preceding_messages": [], "following_messages": []}

    if record["conversation_id"]:
        conversation = await get_conversation(
            stale_hours=stale_hours, cwid=record["chatwoot_conversation_id"]
        )
        if conversation:
            conversation_ref = _conversation_ref(conversation)
            row["lead_name"] = conversation["lead_name"]

        # Bracketing uses created_at on both sides — chatbot_logs.created_at and
        # messages.created_at are the same persist clock, while messages.sent_at
        # is Chatwoot's send clock and runs seconds earlier.
        before = await pool.fetch(
            sql.LOG_CONTEXT_BEFORE_QUERY, record["conversation_id"], record["created_at"]
        )
        after = await pool.fetch(
            sql.LOG_CONTEXT_AFTER_QUERY, record["conversation_id"], record["created_at"]
        )
        context = {
            "preceding_messages": [_message_row(m) for m in reversed(before)],
            "following_messages": [_message_row(m) for m in after],
        }

    raw = {
        key: (str(value) if isinstance(value, (uuid.UUID, datetime)) else value)
        for key, value in dict(record).items()
    }

    return {
        "log": row,
        "conversation": conversation_ref,
        "context": context,
        "payload": {"available": False, "note": _PAYLOAD_NOTE},
        "raw": raw,
    }


async def _get_derived_log_detail(
    *, stale_hours: int, log_id: str
) -> Optional[dict[str, Any]]:
    """Detail for a synthesised event — shows the derivation inputs, not a fake row."""
    parts = log_id.split(":", 2)
    if len(parts) != 3:
        return None
    _, kind, conversation_uuid = parts

    pool = get_pool()
    record = await pool.fetchrow(
        "SELECT chatwoot_conversation_id FROM conversations WHERE id = $1",
        _safe_uuid(conversation_uuid),
    )
    if not record:
        return None

    conversation = await get_conversation(
        stale_hours=stale_hours, cwid=record["chatwoot_conversation_id"]
    )
    if not conversation:
        return None

    events = await _build_derived_events(conversation, stale_hours=stale_hours)
    match = next((e for e in events if e["id"] == log_id), None)
    if match is None:
        return None

    match["chatwoot_conversation_id"] = conversation["chatwoot_conversation_id"]
    match["lead_name"] = conversation["lead_name"]

    return {
        "log": match,
        "conversation": _conversation_ref(conversation),
        "context": {"preceding_messages": [], "following_messages": []},
        "payload": {
            "available": False,
            "note": (
                "Derived event — reconstructed by the dashboard from conversation "
                "state, not read from chatbot_logs."
            ),
        },
        "raw": {
            "kind": kind,
            "derived_from": {
                "status": conversation["status"],
                "flow_state": conversation["flow_state"],
                "takeover_at": conversation["takeover_at"],
                "escalated_at": conversation["escalated_at"],
                "escalated_at_exact": conversation["escalated_at_exact"],
                "last_activity_at": conversation["last_activity_at"],
                "reason_source": conversation["reason_source"],
                "stale_hours": stale_hours,
            },
        },
    }


def _safe_uuid(value: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


async def get_conversation_messages(
    *, stale_hours: int, cwid: int
) -> Optional[dict[str, Any]]:
    pool = get_pool()
    conversation = await get_conversation(stale_hours=stale_hours, cwid=cwid)
    if not conversation:
        return None

    cid = uuid.UUID(conversation["id"])
    records = await pool.fetch(sql.CONVERSATION_MESSAGES_QUERY, cid)
    messages = [_message_row(m) for m in records]

    markers = await _build_markers(conversation, records, cid)

    return {
        "conversation": _conversation_ref(conversation),
        "messages": messages,
        "markers": markers,
    }


def _anchor_message_id(
    records: Any, at: Optional[datetime], *, exclusive: bool = False
) -> Optional[str]:
    """
    Last message persisted before `at` — the marker renders directly beneath it.

    Anchoring on created_at (persist clock) keeps markers consistent with
    chatbot_logs.created_at; using sent_at would drift markers by seconds and can
    place a failure line before the message that caused it.

    `exclusive` is for markers whose timestamp *is* a message's timestamp — a
    human takeover is stamped from the agent's own message, and an inclusive
    match would anchor to that message and draw the "took over" line below it
    instead of above.
    """
    if at is None:
        return None
    anchor = None
    for record in records:
        created = record["created_at"]
        if created is None:
            continue
        if created < at or (created == at and not exclusive):
            anchor = record
        else:
            break
    return str(anchor["id"]) if anchor is not None else None


async def _build_markers(
    conversation: dict[str, Any], records: Any, cid: uuid.UUID
) -> list[dict[str, Any]]:
    pool = get_pool()
    markers: list[dict[str, Any]] = []
    status = conversation["status"]

    # Records come back in send order; anchoring wants persist order.
    by_created = sorted(
        (r for r in records if r["created_at"] is not None), key=lambda r: r["created_at"]
    )

    if status == derive.STATUS_HUMAN_INTERRUPTION and conversation["takeover_at"]:
        agent = await pool.fetchrow(sql.TAKEOVER_MESSAGE_QUERY, cid)
        who = (agent["sender_name"] if agent else None) or "A human agent"
        at = agent["created_at"] if agent else None
        markers.append(
            {
                "kind": "human_interruption",
                "at": conversation["takeover_at"],
                # exclusive: `at` is the agent's own message timestamp.
                "after_message_id": _anchor_message_id(by_created, at, exclusive=True),
                "label": "Human agent took over",
                "detail": f"{who} sent an outbound message; InfoGatherer stopped.",
                "log_id": None,
            }
        )

    if status in (derive.STATUS_FAILED, derive.STATUS_HUMAN_NEEDED):
        failure_at = await pool.fetchval(
            """
            SELECT MAX(created_at) FROM chatbot_logs
             WHERE conversation_id = $1 AND log_level IN ('error','fatal')
            """,
            cid,
        )
        log_id = None
        if failure_at is not None:
            log_id = await pool.fetchval(
                """
                SELECT id FROM chatbot_logs
                 WHERE conversation_id = $1 AND created_at = $2
                 ORDER BY created_at DESC LIMIT 1
                """,
                cid,
                failure_at,
            )
        anchor_at = failure_at
        if anchor_at is None and conversation["last_activity_at"]:
            anchor_at = _parse_iso(conversation["last_activity_at"])

        markers.append(
            {
                "kind": "failure" if status == derive.STATUS_FAILED else "human_needed",
                "at": derive.to_iso(failure_at) or conversation["escalated_at"],
                "after_message_id": _anchor_message_id(by_created, anchor_at),
                "label": (
                    "Failed" if status == derive.STATUS_FAILED else "Escalated to human"
                ),
                "detail": conversation["failure_reason"],
                "log_id": str(log_id) if log_id else None,
            }
        )

    return markers


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


async def get_stats_summary(*, stale_hours: int) -> dict[str, Any]:
    pool = get_pool()

    count_records = await pool.fetch(sql.STATUS_COUNTS_QUERY, stale_hours)
    counts = {status: 0 for status in derive.ALL_STATUSES}
    for record in count_records:
        counts[record["status"]] = record["n"]

    total = sum(counts.values())
    denominator = total - counts[derive.STATUS_NOT_RUN]

    clean_record = await pool.fetchrow(sql.CLEAN_INTERRUPTION_QUERY, stale_hours)
    clean = clean_record["clean_count"] if clean_record else 0
    interrupted = clean_record["total_interrupted"] if clean_record else 0

    return {
        "stale_hours": stale_hours,
        "total_conversations": total,
        "denominator": denominator,
        "counts": counts,
        "percentages": {
            "failed": derive.percentage(counts[derive.STATUS_FAILED], denominator),
            "human_needed": derive.percentage(
                counts[derive.STATUS_HUMAN_NEEDED], denominator
            ),
            "success": derive.percentage(counts[derive.STATUS_SUCCESS], denominator),
            "clean_interruption": derive.percentage(clean, denominator),
            "in_progress": derive.percentage(
                counts[derive.STATUS_IN_PROGRESS], denominator
            ),
        },
        "clean_interruption_count": clean,
        "dirty_interruption_count": interrupted - clean,
    }


async def get_breakdowns(*, stale_hours: int) -> dict[str, Any]:
    pool = get_pool()
    records = await pool.fetch(sql.BREAKDOWN_ROWS_QUERY, stale_hours)

    failures_by_state: Counter[str] = Counter()
    failures_by_signature: Counter[str] = Counter()
    human_needed_by_state: Counter[str] = Counter()
    labels: dict[str, str] = {}

    for record in records:
        status = record["status"]
        reason, _, signature = derive.resolve_failure_reason(
            status=status,
            flow_state=record["flow_state"],
            stale_hours=stale_hours,
            failure_log_explanation=record["failure_log_explanation"],
            failure_log_internal_class=record["failure_log_internal_class"],
            failure_log_status_code=record["failure_log_status_code"],
            rec_engine_status=record["rec_engine_status"],
            rec_engine_status_code=record["rec_engine_status_code"],
            rec_engine_network_status=record["rec_engine_network_status"],
        )
        origin = derive.origin_flow_state(
            status=status,
            flow_state=record["flow_state"],
            from_state=record["failure_log_from_state"],
            signature=signature,
        )

        if status == derive.STATUS_FAILED:
            failures_by_state[origin] += 1
            key = signature or "unclassified"
            failures_by_signature[key] += 1
            labels[key] = derive.signature_label(key)
        else:
            human_needed_by_state[origin] += 1

    state_labels = {derive.UNKNOWN_ORIGIN: "Unknown origin"}

    return {
        "failures_by_flow_state": derive.build_slices(
            dict(failures_by_state), labels=state_labels
        ),
        "failures_by_signature": derive.build_slices(
            dict(failures_by_signature), labels=labels
        ),
        "human_needed_by_flow_state": derive.build_slices(
            dict(human_needed_by_state), labels=state_labels
        ),
    }


async def get_human_needed_triggers(
    *, stale_hours: int, limit: int = 20
) -> dict[str, Any]:
    pool = get_pool()
    records = await pool.fetch(sql.HUMAN_NEEDED_TRIGGERS_QUERY, stale_hours)

    total = len(records)
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "conversations": [], "originals": Counter()}
    )

    for record in records:
        content = record["content"]
        if content is None or not content.strip():
            continue
        key = derive.normalize_message_text(content)
        if not key:
            continue
        group = groups[key]
        group["count"] += 1
        group["originals"][content.strip()] += 1
        group["conversations"].append(
            {
                "chatwoot_conversation_id": record["chatwoot_conversation_id"],
                "lead_name": record["lead_name"],
                "sent_at": derive.to_iso(record["sent_at"]),
            }
        )

    rows = []
    for key, group in groups.items():
        # Most frequent original casing; ties fall back to the most recent.
        display = group["originals"].most_common(1)[0][0]
        conversations = sorted(
            group["conversations"], key=lambda c: c["sent_at"] or "", reverse=True
        )
        rows.append(
            {
                "normalized": key,
                "display_text": display,
                "count": group["count"],
                "conversations": conversations,
                "_recent": conversations[0]["sent_at"] if conversations else "",
            }
        )

    rows.sort(key=lambda r: (-r["count"], r["_recent"] or ""), reverse=False)
    rows.sort(key=lambda r: r["count"], reverse=True)
    for row in rows:
        row.pop("_recent", None)

    return {
        "total_human_needed": total,
        "with_trigger": sum(group["count"] for group in groups.values()),
        "rows": rows[:limit],
    }


def utc_now_iso() -> str:
    return derive.to_iso(datetime.now(tz=timezone.utc)) or ""
