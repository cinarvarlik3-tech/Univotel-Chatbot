"""Unit tests for Chatwoot client message pagination (spec 024)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chatwoot_client import fetch_all_messages, _MAX_MESSAGE_PAGES


def _msg(mid: int) -> dict:
    return {
        "id": mid,
        "content": f"msg-{mid}",
        "message_type": 0,
        "private": False,
        "created_at": mid,
        "sender": {},
    }


@pytest.mark.asyncio
async def test_should_page_backward_until_no_new_messages():
    page1 = [_msg(30), _msg(20), _msg(10)]
    page2 = [_msg(5), _msg(3)]
    page3: list[dict] = []

    responses = []
    for payload in (page1, page2, page3):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"payload": payload}
        responses.append(resp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None

    with patch("app.chatwoot_client.httpx.AsyncClient", return_value=mock_cm):
        result = await fetch_all_messages(1142)

    assert result is not None
    assert [m["id"] for m in result] == [3, 5, 10, 20, 30]
    assert mock_client.get.await_count == 3
    second_call_params = mock_client.get.await_args_list[1].kwargs["params"]
    assert second_call_params["before"] == 10


@pytest.mark.asyncio
async def test_should_stop_at_page_cap():
    same_page = [_msg(100), _msg(90)]

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"payload": same_page}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None

    with patch("app.chatwoot_client.httpx.AsyncClient", return_value=mock_cm):
        result = await fetch_all_messages(1)

    assert result is not None
    assert mock_client.get.await_count <= _MAX_MESSAGE_PAGES
