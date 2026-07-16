"""
Live LLM API calls for daytime TagAssigner runs (§4.3 of tagassigner-v1-spec.md).

Provider and model are resolved per task from settings (TAGASSIGNER_PROVIDER, etc.).
Returns labels + bot-writable attributes; Router merges and persists (spec 018).
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from app.llm.errors import is_client_error
from app.llm.factory import get_llm_client
from app.tagassigner.payload_builder import parse_tag_result
from app.tagassigner.llm_types import TagResult

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1.0, 2.0, 4.0]


async def call_llm(
    system_prompt: str,
    user_content: str,
) -> Optional[TagResult]:
    """
    Send a single live LLM request for TagAssigner and return the parsed result.
    Returns None on unrecoverable failure.
    Retries on 5xx/timeout (1s/2s/4s); aborts on 4xx.
    """
    client = get_llm_client("tagassigner")

    last_error: Optional[str] = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            response = await client.complete(system_prompt, user_content)
            if response is None:
                return None
            result = parse_tag_result(response)
            if result is None:
                logger.error(
                    "llm_client: malformed response on attempt %d: %r",
                    attempt, response[:200],
                )
                return None
            return result

        except Exception as exc:
            last_error = str(exc)
            exc_name = type(exc).__name__
            if is_client_error(exc):
                logger.error(
                    "llm_client: non-retryable error on attempt %d (%s): %s",
                    attempt, exc_name, exc,
                )
                return None
            logger.warning(
                "llm_client: retryable error on attempt %d (%s): %s",
                attempt, exc_name, exc,
            )
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)

    logger.error("llm_client: all retries exhausted — last error: %s", last_error)
    return None
