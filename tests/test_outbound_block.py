"""Unit tests for OUTBOUND_BLOCK guard (Spec 022 Part C)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.background.send_retry import SendRetryResult, send_with_retry


@pytest.mark.asyncio
async def test_should_return_synthetic_success_when_outbound_block_on(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "outbound_block", True)
    with patch(
        "app.background.send_retry.send_message",
        new_callable=AsyncMock,
    ) as mock_send:
        result = await send_with_retry(123, "hello")
    assert result == SendRetryResult(ok=True, final_status_code=0)
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_should_call_send_message_when_outbound_block_off(monkeypatch):
    from app import config
    from app.chatwoot_client import SendResult

    monkeypatch.setattr(config.settings, "outbound_block", False)
    with patch(
        "app.background.send_retry.send_message",
        new_callable=AsyncMock,
        return_value=SendResult(ok=True, status_code=200, message_id=1),
    ) as mock_send:
        result = await send_with_retry(123, "hello")
    assert result.ok is True
    mock_send.assert_awaited_once_with(123, "hello")


def _mock_httpx_post(status_code: int = 200, json_data: dict | None = None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


@pytest.mark.asyncio
async def test_set_labels_not_guarded_by_outbound_block(monkeypatch):
    from app import config
    from app.chatwoot_client import set_labels

    monkeypatch.setattr(config.settings, "outbound_block", True)
    with patch(
        "app.chatwoot_client.httpx.AsyncClient",
        return_value=_mock_httpx_post(),
    ):
        result = await set_labels(123, ["ogrenci"])
    assert result.ok is True


@pytest.mark.asyncio
async def test_send_private_note_not_guarded_by_outbound_block(monkeypatch):
    from app import config
    from app.chatwoot_client import send_private_note

    monkeypatch.setattr(config.settings, "outbound_block", True)
    with patch(
        "app.chatwoot_client.httpx.AsyncClient",
        return_value=_mock_httpx_post(json_data={"id": 1}),
    ) as mock_client_cls:
        result = await send_private_note(123, "note")
    assert result.ok is True
    mock_client = mock_client_cls.return_value
    call_json = mock_client.post.await_args.kwargs["json"]
    assert call_json.get("private") is True
