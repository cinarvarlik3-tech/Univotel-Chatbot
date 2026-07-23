"""
Send retry with exponential backoff (§6.3).
3 attempts: ~1s → ~2s → ~4s.
4xx errors skip straight to fatal (retrying an identical bad request is pointless).
Timeouts are logged as TIMEOUT.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.chatwoot_client import send_message
from app.config import settings

from app.diagnostics.trace import trace_event_async

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1.0, 2.0, 4.0]


@dataclass
class SendRetryResult:
    ok: bool
    final_status_code: int
    error: Optional[str] = None


async def send_with_retry(chatwoot_conversation_id: int, content: str) -> SendRetryResult:
    if settings.outbound_block:
        logger.info(
            "OUTBOUND_BLOCK: suppressed message to conversation %s",
            chatwoot_conversation_id,
        )
        await trace_event_async(
            "chatwoot",
            "outbound_blocked",
            level="warn",
            chatwoot_conversation_id=chatwoot_conversation_id,
            content_preview=content[:120],
        )
        return SendRetryResult(ok=True, final_status_code=0)

    await trace_event_async(
        "chatwoot",
        "send_attempt",
        chatwoot_conversation_id=chatwoot_conversation_id,
        content_preview=content[:200],
        content_len=len(content),
    )

    last_error: Optional[str] = None
    last_status = 0

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        result = await send_message(chatwoot_conversation_id, content)

        if result.ok:
            await trace_event_async(
                "chatwoot",
                "send_ok",
                chatwoot_conversation_id=chatwoot_conversation_id,
                message_id=result.message_id,
                attempt=attempt,
            )
            return SendRetryResult(ok=True, final_status_code=result.status_code)

        last_status = result.status_code
        last_error = result.error

        if result.status_code == 0 and result.error == "TIMEOUT":
            logger.error(
                "send_with_retry: TIMEOUT on attempt %d for conversation %d",
                attempt, chatwoot_conversation_id,
            )
        elif 400 <= result.status_code < 500:
            # Non-retryable: a 4xx will never succeed with the same payload.
            logger.error(
                "send_with_retry: non-retryable %d on conversation %d — aborting",
                result.status_code, chatwoot_conversation_id,
            )
            return SendRetryResult(ok=False, final_status_code=result.status_code, error=last_error)
        else:
            logger.warning(
                "send_with_retry: HTTP %d on attempt %d for conversation %d",
                result.status_code, attempt, chatwoot_conversation_id,
            )

        if attempt < len(RETRY_DELAYS):
            await asyncio.sleep(delay)

    logger.error(
        "send_with_retry: all attempts exhausted for conversation %d — fatal",
        chatwoot_conversation_id,
    )
    return SendRetryResult(ok=False, final_status_code=last_status, error=last_error)
