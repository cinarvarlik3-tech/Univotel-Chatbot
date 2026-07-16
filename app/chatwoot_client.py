"""
Thin async wrapper around the Chatwoot REST API.
All outbound HTTP to Chatwoot goes through here — callers never touch httpx directly.
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = settings.chatwoot_base_url.rstrip("/")
_ACCOUNT = settings.chatwoot_account_id
_HEADERS = {
    "api_access_token": settings.chatwoot_api_token,
    "Content-Type": "application/json",
}

TIMEOUT = httpx.Timeout(10.0)


@dataclass
class SendResult:
    ok: bool
    status_code: int
    message_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class FetchResult:
    ok: bool
    status_code: int
    data: Optional[dict] = None
    error: Optional[str] = None


async def send_message(chatwoot_conversation_id: int, content: str) -> SendResult:
    url = f"{_BASE}/api/v1/accounts/{_ACCOUNT}/conversations/{chatwoot_conversation_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json={"content": content, "message_type": "outgoing"}, headers=_HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            return SendResult(ok=True, status_code=200, message_id=data.get("id"))
        logger.error("send_message: HTTP %d for conversation %d", resp.status_code, chatwoot_conversation_id)
        return SendResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        logger.error("send_message: TIMEOUT for conversation %d", chatwoot_conversation_id)
        return SendResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        logger.error("send_message: network error for conversation %d: %s", chatwoot_conversation_id, exc)
        return SendResult(ok=False, status_code=0, error=str(exc))


async def send_private_note(chatwoot_conversation_id: int, content: str) -> SendResult:
    """Post a private note on a conversation (operator commands / confirmations)."""
    url = f"{_BASE}/api/v1/accounts/{_ACCOUNT}/conversations/{chatwoot_conversation_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                url,
                json={"content": content, "message_type": "outgoing", "private": True},
                headers=_HEADERS,
            )
        if resp.status_code == 200:
            data = resp.json()
            return SendResult(ok=True, status_code=200, message_id=data.get("id"))
        logger.error(
            "send_private_note: HTTP %d for conversation %d",
            resp.status_code, chatwoot_conversation_id,
        )
        return SendResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        logger.error("send_private_note: TIMEOUT for conversation %d", chatwoot_conversation_id)
        return SendResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        logger.error(
            "send_private_note: network error for conversation %d: %s",
            chatwoot_conversation_id, exc,
        )
        return SendResult(ok=False, status_code=0, error=str(exc))


async def set_custom_attribute(
    chatwoot_conversation_id: int, key: str, value: Any
) -> SendResult:
    url = (
        f"{_BASE}/api/v1/accounts/{_ACCOUNT}"
        f"/conversations/{chatwoot_conversation_id}/custom_attributes"
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                url,
                json={"custom_attributes": {key: value}},
                headers=_HEADERS,
            )
        if resp.status_code == 200:
            return SendResult(ok=True, status_code=200)
        logger.error(
            "set_custom_attribute: HTTP %d for conversation %d key=%s",
            resp.status_code, chatwoot_conversation_id, key,
        )
        return SendResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        logger.error("set_custom_attribute: TIMEOUT for conversation %d key=%s", chatwoot_conversation_id, key)
        return SendResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        logger.error("set_custom_attribute: network error for conversation %d: %s", chatwoot_conversation_id, exc)
        return SendResult(ok=False, status_code=0, error=str(exc))


async def set_custom_attributes(
    chatwoot_conversation_id: int, attributes: dict[str, Any]
) -> SendResult:
    """Write multiple custom attributes in a single call."""
    url = (
        f"{_BASE}/api/v1/accounts/{_ACCOUNT}"
        f"/conversations/{chatwoot_conversation_id}/custom_attributes"
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                url,
                json={"custom_attributes": attributes},
                headers=_HEADERS,
            )
        if resp.status_code == 200:
            return SendResult(ok=True, status_code=200)
        logger.error(
            "set_custom_attributes: HTTP %d for conversation %d",
            resp.status_code, chatwoot_conversation_id,
        )
        return SendResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        logger.error("set_custom_attributes: TIMEOUT for conversation %d", chatwoot_conversation_id)
        return SendResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        logger.error("set_custom_attributes: network error for conversation %d: %s", chatwoot_conversation_id, exc)
        return SendResult(ok=False, status_code=0, error=str(exc))


async def get_labels(chatwoot_conversation_id: int) -> Optional[list[str]]:
    """
    Returns the current label set live from Chatwoot.
    Returns None on failure (caller decides how to handle).
    The merge/guard logic in TagAssigner depends on an accurate snapshot — always read live.
    """
    url = (
        f"{_BASE}/api/v1/accounts/{_ACCOUNT}"
        f"/conversations/{chatwoot_conversation_id}/labels"
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=_HEADERS)
        if resp.status_code == 200:
            return resp.json().get("payload", [])
        logger.error(
            "get_labels: HTTP %d for conversation %d",
            resp.status_code, chatwoot_conversation_id,
        )
        return None
    except httpx.TimeoutException:
        logger.error("get_labels: TIMEOUT for conversation %d", chatwoot_conversation_id)
        return None
    except httpx.RequestError as exc:
        logger.error("get_labels: network error for conversation %d: %s", chatwoot_conversation_id, exc)
        return None


async def set_labels(
    chatwoot_conversation_id: int, labels: list[str]
) -> SendResult:
    """
    Replace the entire label set for a conversation.
    Chatwoot's POST /labels replaces the full set — callers must pass the complete
    desired set, not just the additions. Use get_labels() first if a merge is needed.
    """
    url = (
        f"{_BASE}/api/v1/accounts/{_ACCOUNT}"
        f"/conversations/{chatwoot_conversation_id}/labels"
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json={"labels": labels}, headers=_HEADERS)
        if resp.status_code == 200:
            return SendResult(ok=True, status_code=200)
        logger.error(
            "set_labels: HTTP %d for conversation %d",
            resp.status_code, chatwoot_conversation_id,
        )
        return SendResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        logger.error("set_labels: TIMEOUT for conversation %d", chatwoot_conversation_id)
        return SendResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        logger.error("set_labels: network error for conversation %d: %s", chatwoot_conversation_id, exc)
        return SendResult(ok=False, status_code=0, error=str(exc))


async def fetch_conversation(chatwoot_conversation_id: int) -> FetchResult:
    url = f"{_BASE}/api/v1/accounts/{_ACCOUNT}/conversations/{chatwoot_conversation_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=_HEADERS)
        if resp.status_code == 200:
            return FetchResult(ok=True, status_code=200, data=resp.json())
        return FetchResult(ok=False, status_code=resp.status_code, error=resp.text)
    except httpx.TimeoutException:
        return FetchResult(ok=False, status_code=0, error="TIMEOUT")
    except httpx.RequestError as exc:
        return FetchResult(ok=False, status_code=0, error=str(exc))


_MAX_MESSAGE_PAGES = 25


async def fetch_all_messages(chatwoot_conversation_id: int) -> Optional[list[dict]]:
    """
    Fetch the full message history for a conversation, paging backward.

    Chatwoot returns newest-first pages; walk backward with `before` until empty.
    Returns raw message dicts oldest-first, or None on hard failure.
    """
    url = (
        f"{_BASE}/api/v1/accounts/{_ACCOUNT}"
        f"/conversations/{chatwoot_conversation_id}/messages"
    )
    collected: list[dict] = []
    before_id: Optional[int] = None

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for page in range(_MAX_MESSAGE_PAGES):
                params = {}
                if before_id is not None:
                    params["before"] = before_id

                resp = await client.get(url, headers=_HEADERS, params=params or None)
                if resp.status_code != 200:
                    logger.error(
                        "fetch_all_messages: HTTP %d for conversation %d",
                        resp.status_code, chatwoot_conversation_id,
                    )
                    return None

                payload = resp.json().get("payload", [])
                if not isinstance(payload, list) or not payload:
                    break

                page_ids = [m.get("id") for m in payload if m.get("id") is not None]
                if not page_ids:
                    break

                min_id = min(int(mid) for mid in page_ids)
                if before_id is not None and min_id >= before_id:
                    break

                collected.extend(payload)
                before_id = min_id

            if page + 1 >= _MAX_MESSAGE_PAGES:
                logger.warning(
                    "fetch_all_messages: page cap hit for conversation %d",
                    chatwoot_conversation_id,
                )

        collected.sort(key=lambda m: int(m.get("id", 0)))
        return collected

    except httpx.TimeoutException:
        logger.error(
            "fetch_all_messages: TIMEOUT for conversation %d", chatwoot_conversation_id
        )
        return None
    except httpx.RequestError as exc:
        logger.error(
            "fetch_all_messages: network error for conversation %d: %s",
            chatwoot_conversation_id, exc,
        )
        return None
