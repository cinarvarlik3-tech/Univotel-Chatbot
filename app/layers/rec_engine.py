"""
RecEngine (§5.2, §8.4).

Entry point: run_rec_engine(conversation_id, idempotency_key)
Writes a 'processing' row before doing any query work (idempotency guarantee).
Returns via HTTP callback to /internal/infogatherer/callback on completion.
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from app.config import settings
from app.db import queries
from app.db.models import ChatbotLog

logger = logging.getLogger(__name__)

GLOBAL_NULL_STATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LAYER = "recEngine"

_CALLBACK_URL = "http://localhost:{port}/internal/infogatherer/callback"


class RecStatus(str, Enum):
    FOUND = "200_FOUND"
    NOT_FOUND = "200_NOT_FOUND"
    FAILED = "502"


@dataclass
class RecResult:
    status: RecStatus
    hotel_id: Optional[uuid.UUID] = None


async def run_rec_engine(
    conversation_id: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> None:
    """
    Full RecEngine run. The idempotency_key prevents duplicate processing:
    write 'processing' first, then work. A retry that arrives mid-run
    finds the existing row and no-ops.
    """
    # Idempotency: write processing row before any query work
    await queries.insert_rec_engine_processing(conversation_id, idempotency_key)

    # Check if already processed (race: two retries both got here before either wrote)
    existing = await queries.get_rec_engine_log(idempotency_key)
    if existing and existing.status in ("success", "failed"):
        logger.info("RecEngine: idempotency key %s already resolved — skipping", idempotency_key)
        return

    try:
        result = await _select_hotel(conversation_id)
    except Exception as exc:
        logger.error("RecEngine: unexpected error for conversation %s: %s", conversation_id, exc)
        await queries.update_rec_engine_log(idempotency_key, "failed", None, status_code="502")
        await _fire_callback(conversation_id, None, RecStatus.FAILED)
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

    hotel_rec = result.hotel_id if result.status == RecStatus.FOUND else None
    db_status = "success" if result.status != RecStatus.FAILED else "failed"
    await queries.update_rec_engine_log(idempotency_key, db_status, hotel_rec)
    await _fire_callback(conversation_id, hotel_rec, result.status)


async def _select_hotel(conversation_id: uuid.UUID) -> RecResult:
    conv = await queries.get_conversation_by_chatwoot_id_by_id(conversation_id)
    if not conv or not conv.university_id or not conv.gender:
        raise ValueError(f"Missing university_id or gender for conversation {conversation_id}")

    candidates = await queries.find_hotels_by_gender_and_university(
        conv.gender, conv.university_id
    )

    if not candidates:
        logger.info(
            "RecEngine: conv=%s uni=%s gender=%s candidates=[] → NOT_FOUND",
            conversation_id, conv.university_id, conv.gender,
        )
        return RecResult(status=RecStatus.NOT_FOUND, hotel_id=GLOBAL_NULL_STATE_ID)

    if len(candidates) == 1:
        hotel = candidates[0]
    else:
        hotel = max(candidates, key=lambda h: h.priority_score or 0)

    logger.info(
        "RecEngine: conv=%s uni=%s gender=%s candidates=%s → selected=%s",
        conversation_id,
        conv.university_id,
        conv.gender,
        [(h.name, h.priority_score) for h in candidates],
        hotel.name,
    )

    # Stale hotel reference check (§8.4)
    live = await queries.get_hotel_by_id(hotel.id)
    if not live:
        logger.warning("RecEngine: hotel %s no longer exists — rerunning selection", hotel.id)
        fresh_candidates = await queries.find_hotels_by_gender_and_university(
            conv.gender, conv.university_id
        )
        fresh_candidates = [c for c in fresh_candidates if c.id != hotel.id]
        if not fresh_candidates:
            return RecResult(status=RecStatus.NOT_FOUND, hotel_id=GLOBAL_NULL_STATE_ID)
        live = await queries.get_hotel_by_id(fresh_candidates[0].id)
        if not live:
            raise ValueError("Stale hotel rerun also produced a missing hotel — aborting")
        hotel = fresh_candidates[0]

    return RecResult(status=RecStatus.FOUND, hotel_id=hotel.id)


async def _fire_callback(
    conversation_id: uuid.UUID,
    hotel_rec: Optional[uuid.UUID],
    status: RecStatus,
) -> None:
    import os
    port = os.environ.get("PORT", "8000")
    url = f"http://localhost:{port}/internal/infogatherer/callback"
    payload = {
        "conversation_id": str(conversation_id),
        "hotel_rec": str(hotel_rec) if hotel_rec else None,
        "status": status.value,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(
                url,
                json=payload,
                headers={"X-Internal-Secret": settings.internal_shared_secret},
            )
    except Exception as exc:
        logger.error("RecEngine: callback delivery failed for conversation %s: %s", conversation_id, exc)
