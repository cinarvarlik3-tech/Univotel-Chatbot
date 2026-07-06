"""
Internal API endpoints for InfoGatherer ↔ RecEngine communication (§4.2, §4.3).
All routes require X-Internal-Secret header verified via constant-time compare.
"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.security import verify_internal_secret
from app.db import queries

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /internal/recengine/start — InfoGatherer → RecEngine
# ---------------------------------------------------------------------------

class RecEngineStartRequest(BaseModel):
    conversation_id: uuid.UUID
    idempotency_key: uuid.UUID
    university_id_override: Optional[uuid.UUID] = None
    gender_override: Optional[str] = None


@router.post("/internal/recengine/start")
async def start_rec_engine(
    body: RecEngineStartRequest,
    x_internal_secret: Optional[str] = Header(default=None),
):
    verify_internal_secret(x_internal_secret)

    # Check idempotency: if already processing/done, skip.
    existing = await queries.get_rec_engine_log(body.idempotency_key)
    if existing:
        logger.info(
            "INTERNAL: idempotency key %s already exists (status=%s) — no-op",
            body.idempotency_key, existing.status,
        )
        return JSONResponse(status_code=200, content={"status": "already_processing"})

    from app.layers.rec_engine import run_rec_engine
    asyncio.create_task(run_rec_engine(
        body.conversation_id,
        body.idempotency_key,
        university_id_override=body.university_id_override,
        gender_override=body.gender_override,
    ))

    return JSONResponse(status_code=200, content={"status": "started"})


# ---------------------------------------------------------------------------
# POST /internal/infogatherer/callback — RecEngine → InfoGatherer
# ---------------------------------------------------------------------------

class RecEngineCallbackRequest(BaseModel):
    conversation_id: uuid.UUID
    hotel_rec: Optional[uuid.UUID] = None
    status: str  # "200_FOUND" | "200_NOT_FOUND" | "502"


@router.post("/internal/infogatherer/callback")
async def rec_engine_callback(
    body: RecEngineCallbackRequest,
    x_internal_secret: Optional[str] = Header(default=None),
):
    verify_internal_secret(x_internal_secret)

    conversation = await queries.get_conversation_by_id(body.conversation_id)
    if not conversation:
        logger.error("CALLBACK: conversation %s not found", body.conversation_id)
        return JSONResponse(status_code=200, content={"status": "not_found"})

    if body.status == "502":
        logger.error("CALLBACK: RecEngine returned 502 for conversation %s", body.conversation_id)
        await queries.set_conversation_human_needed(body.conversation_id)
        from app.layers.info_gatherer import _write_human_needed_label
        await _write_human_needed_label(conversation.chatwoot_conversation_id)
        return JSONResponse(status_code=200, content={"status": "escalated"})

    from app.db.queries import DEAL_AWAITING_LABEL_STATE_ID, GLOBAL_NULL_STATE_ID
    from app.layers.info_gatherer import (
        _send_hotel_responses,
        _write_deal_awaiting_label,
    )

    hotel_id = body.hotel_rec or GLOBAL_NULL_STATE_ID

    # Advance state
    advanced = await queries.update_conversation_state(
        body.conversation_id, "completed", "recengine_running"
    )
    if not advanced:
        logger.info("CALLBACK: lost optimistic lock on conversation %s — skipping", body.conversation_id)
        return JSONResponse(status_code=200, content={"status": "lock_lost"})

    chatwoot_id = conversation.chatwoot_conversation_id
    await _send_hotel_responses(body.conversation_id, chatwoot_id, hotel_id)

    if hotel_id == DEAL_AWAITING_LABEL_STATE_ID:
        await _write_deal_awaiting_label(chatwoot_id)

    # Write university / gender / ilgili_otel immediately so they are visible
    # in Chatwoot without waiting for the next TagAssigner run.
    from app.tagassigner.attribute_resolver import write_attributes_at_flow_completion
    await write_attributes_at_flow_completion(body.conversation_id, chatwoot_id)

    return JSONResponse(status_code=200, content={"status": "ok"})
