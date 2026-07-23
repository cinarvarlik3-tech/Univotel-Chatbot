"""
RecEngine (§5.2, §8.4).

Entry point: run_rec_engine(conversation_id, idempotency_key)
Writes a 'processing' row before doing any query work (idempotency guarantee).
Returns via HTTP callback to /internal/infogatherer/callback on completion.

FOUND returns all eligible properties (gender + university), ordered by priority_score.
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

from app.config import settings
from app.db import queries
from app.db.models import ChatbotLog
from app.diagnostics.trace import trace_event_async

logger = logging.getLogger(__name__)

LAYER = "recEngine"

_CALLBACK_URL = "http://localhost:{port}/internal/infogatherer/callback"


class RecStatus(str, Enum):
    FOUND = "200_FOUND"
    NOT_FOUND = "200_NOT_FOUND"
    FAILED = "502"


@dataclass
class RecResult:
    status: RecStatus
    hotel_ids: list[uuid.UUID] = field(default_factory=list)


async def _resolve_not_found_sentinel(university_id: uuid.UUID) -> uuid.UUID:
    """
    Pick the NOT_FOUND sentinel for an Istanbul university with no hotel match.
    Membership in deal_awaiting_universities → label path (…0003); else …0002.
    """
    if await queries.is_deal_awaiting_university(university_id):
        return queries.DEAL_AWAITING_LABEL_STATE_ID
    return queries.DEAL_AWAITING_STATE_ID


async def run_rec_engine(
    conversation_id: uuid.UUID,
    idempotency_key: uuid.UUID,
    university_id_override: uuid.UUID | None = None,
    gender_override: str | None = None,
) -> None:
    """
    Full RecEngine run. The idempotency_key prevents duplicate processing:
    write 'processing' first, then work. A retry that arrives mid-run
    finds the existing row and no-ops.

    Optional overrides are runtime-only — DB is not written before the run.
    """
    await queries.insert_rec_engine_processing(conversation_id, idempotency_key)

    existing = await queries.get_rec_engine_log(idempotency_key)
    if existing and existing.status in ("success", "failed"):
        logger.info("RecEngine: idempotency key %s already resolved — skipping", idempotency_key)
        return

    try:
        result = await _select_hotels(
            conversation_id,
            university_id_override=university_id_override,
            gender_override=gender_override,
        )
    except Exception as exc:
        logger.error("RecEngine: unexpected error for conversation %s: %s", conversation_id, exc)
        await queries.update_rec_engine_log(idempotency_key, "failed", None, status_code="502")
        await _fire_callback(conversation_id, None, RecStatus.FAILED, hotel_recs=None)
        await queries.write_log(ChatbotLog(
            conversation_id=conversation_id,
            operation_layer=LAYER,
            which_run="contextRun",
            log_level="fatal",
            is_success=False,
            status_code="502",
            explanation=f"Unexpected RecEngine error: {exc}",
        ))
        return

    hotel_rec: Optional[uuid.UUID] = None
    hotel_recs: Optional[list[uuid.UUID]] = None
    status_code = result.status.value

    if result.status == RecStatus.FOUND:
        hotel_recs = list(result.hotel_ids)
        hotel_rec = hotel_recs[0] if hotel_recs else None
    elif result.status == RecStatus.NOT_FOUND:
        hotel_rec = result.hotel_ids[0] if result.hotel_ids else None

    db_status = "success" if result.status != RecStatus.FAILED else "failed"
    await queries.update_rec_engine_log(
        idempotency_key,
        db_status,
        hotel_rec,
        status_code=status_code,
        hotel_recs=hotel_recs,
    )
    await _fire_callback(conversation_id, hotel_rec, result.status, hotel_recs=hotel_recs)


async def _select_hotels(
    conversation_id: uuid.UUID,
    university_id_override: uuid.UUID | None = None,
    gender_override: str | None = None,
) -> RecResult:
    conv = await queries.get_conversation_by_chatwoot_id_by_id(conversation_id)
    university_id = university_id_override or (conv.university_id if conv else None)
    gender = gender_override or (conv.gender if conv else None)
    if not university_id or not gender:
        raise ValueError(f"Missing university_id or gender for conversation {conversation_id}")

    candidates = await queries.find_hotels_by_gender_and_university(gender, university_id)

    if not candidates:
        sentinel = await _resolve_not_found_sentinel(university_id)
        logger.info(
            "RecEngine: conv=%s uni=%s gender=%s candidates=[] → NOT_FOUND sentinel=%s",
            conversation_id, university_id, gender, sentinel,
        )
        return RecResult(status=RecStatus.NOT_FOUND, hotel_ids=[sentinel])

    live_ids: list[uuid.UUID] = []
    for hotel in candidates:
        if queries.is_recengine_sentinel_hotel_id(hotel.id):
            continue
        live = await queries.get_hotel_by_id(hotel.id)
        if live:
            live_ids.append(live.id)

    if not live_ids:
        sentinel = await _resolve_not_found_sentinel(university_id)
        logger.warning(
            "RecEngine: conv=%s all candidates stale or invalid → NOT_FOUND sentinel=%s",
            conversation_id, sentinel,
        )
        return RecResult(status=RecStatus.NOT_FOUND, hotel_ids=[sentinel])

    logger.info(
        "RecEngine: conv=%s uni=%s gender=%s candidates=%s → FOUND all=%s",
        conversation_id,
        university_id,
        gender,
        [(h.name, h.priority_score) for h in candidates],
        live_ids,
    )
    await trace_event_async(
        "recEngine",
        "found",
        conversation_id=conversation_id,
        university_id=str(university_id),
        gender=gender,
        hotel_ids=[str(h) for h in live_ids],
        candidate_count=len(candidates),
    )
    return RecResult(status=RecStatus.FOUND, hotel_ids=live_ids)


# Backward-compatible alias for tests and callers.
_select_hotel = _select_hotels


async def _fire_callback(
    conversation_id: uuid.UUID,
    hotel_rec: Optional[uuid.UUID],
    status: RecStatus,
    *,
    hotel_recs: Optional[list[uuid.UUID]] = None,
) -> None:
    import os
    port = os.environ.get("PORT", "8000")
    url = f"http://localhost:{port}/internal/infogatherer/callback"
    payload: dict = {
        "conversation_id": str(conversation_id),
        "hotel_rec": str(hotel_rec) if hotel_rec else None,
        "status": status.value,
    }
    if hotel_recs is not None:
        payload["hotel_recs"] = [str(hid) for hid in hotel_recs]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(
                url,
                json=payload,
                headers={"X-Internal-Secret": settings.internal_shared_secret},
            )
    except Exception as exc:
        logger.error("RecEngine: callback delivery failed for conversation %s: %s", conversation_id, exc)
