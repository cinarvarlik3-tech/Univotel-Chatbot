"""
RecEngine retry ladder (§6.2).
3 attempts, 5s apart, sharing one idempotency_key.
After 3 misses → human_needed.
"""
import asyncio
import logging
import uuid

import httpx

from app.config import settings
from app.db import queries

logger = logging.getLogger(__name__)

ATTEMPT_DELAYS = [5.0, 5.0, 5.0]


async def fire_rec_engine(
    conversation_id: uuid.UUID,
    chatwoot_conversation_id: int,
    idempotency_key: uuid.UUID,
    university_id_override: uuid.UUID | None = None,
    gender_override: str | None = None,
) -> None:
    """
    Fire RecEngine via the internal HTTP endpoint, then poll rec_engine_logs
    at each 5s checkpoint. If still not resolved after 3 attempts → human_needed.
    """
    import os
    port = os.environ.get("PORT", "8000")
    url = f"http://localhost:{port}/internal/recengine/start"
    headers = {"X-Internal-Secret": settings.internal_shared_secret}

    for attempt in range(1, 4):
        await _post_start(
            url, headers, conversation_id, idempotency_key,
            university_id_override, gender_override,
        )
        await asyncio.sleep(ATTEMPT_DELAYS[attempt - 1])

        log = await queries.get_rec_engine_log(idempotency_key)
        if log and log.status in ("success", "failed"):
            logger.info(
                "RecEngineLadder: idempotency_key=%s resolved as %s on attempt %d",
                idempotency_key, log.status, attempt,
            )
            return

        logger.warning(
            "RecEngineLadder: no resolution after attempt %d for conversation %s",
            attempt, conversation_id,
        )

    # All attempts exhausted
    logger.fatal(
        "RecEngineLadder: all 3 attempts exhausted for conversation %s — escalating",
        conversation_id,
    )
    await queries.set_conversation_human_needed(conversation_id)
    from app.layers.info_gatherer import _write_human_needed_label
    await _write_human_needed_label(chatwoot_conversation_id)


async def _post_start(
    url: str,
    headers: dict,
    conversation_id: uuid.UUID,
    idempotency_key: uuid.UUID,
    university_id_override: uuid.UUID | None = None,
    gender_override: str | None = None,
) -> None:
    payload = {
        "conversation_id": str(conversation_id),
        "idempotency_key": str(idempotency_key),
    }
    if university_id_override is not None:
        payload["university_id_override"] = str(university_id_override)
    if gender_override is not None:
        payload["gender_override"] = gender_override
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                url,
                json=payload,
                headers=headers,
            )
        if resp.status_code != 200:
            logger.warning("RecEngineLadder: start returned HTTP %d", resp.status_code)
    except Exception as exc:
        logger.error("RecEngineLadder: failed to POST start: %s", exc)
