"""
Live Gemini API calls for daytime TagAssigner runs (§4.3 of tagassigner-v1-spec.md).

Model ID is always read from settings.model_id (never hardcoded).
Gemini's only output is the proposed label set — attributes are Router-computed.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from app.config import settings
from app.tagassigner.payload_builder import parse_gemini_response

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1.0, 2.0, 4.0]


async def call_gemini(
    system_prompt: str,
    user_content: str,
) -> Optional[list[str]]:
    """
    Send a single live request to Gemini and return the parsed label list.
    Returns None on unrecoverable failure.
    Retries on 5xx/timeout (1s/2s/4s); aborts on 4xx.
    """
    if not settings.gemini_api_key:
        logger.fatal("gemini_client: GEMINI_API_KEY not configured")
        return None

    import google.genai as genai
    client = genai.Client(api_key=settings.gemini_api_key)

    last_error: Optional[str] = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            response = await asyncio.to_thread(
                _sync_call,
                client,
                system_prompt,
                user_content,
            )
            if response is None:
                return None
            labels = parse_gemini_response(response)
            if labels is None:
                logger.error(
                    "gemini_client: malformed response on attempt %d: %r",
                    attempt, response[:200],
                )
                return None
            return labels

        except Exception as exc:
            last_error = str(exc)
            exc_name = type(exc).__name__
            # 4xx-equivalent errors are not retryable
            if _is_client_error(exc):
                logger.error(
                    "gemini_client: non-retryable error on attempt %d (%s): %s",
                    attempt, exc_name, exc,
                )
                return None
            logger.warning(
                "gemini_client: retryable error on attempt %d (%s): %s",
                attempt, exc_name, exc,
            )
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)

    logger.error("gemini_client: all retries exhausted — last error: %s", last_error)
    return None


def _sync_call(client, system_prompt: str, user_content: str) -> Optional[str]:
    """Synchronous Gemini call, run via asyncio.to_thread."""
    from google.genai import types

    response = client.models.generate_content(
        model=settings.model_id,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return response.text if response.text else None


def _is_client_error(exc: Exception) -> bool:
    """Heuristic: treat 400-range API errors as non-retryable."""
    msg = str(exc).lower()
    return any(code in msg for code in ["400", "401", "403", "404", "422"])
