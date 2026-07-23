"""Multi-hotel schema delivery (RecEngine FOUND path)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.background.send_retry import SendRetryResult
from app.layers import info_gatherer


@pytest.mark.asyncio
async def test_should_send_all_hotels_and_retry_failed_messages():
    conv_id = uuid.uuid4()
    cwid = 99
    h1, h2 = uuid.uuid4(), uuid.uuid4()
    calls: list[str] = []

    async def fake_send(_cwid, content):
        calls.append(content)
        return SendRetryResult(ok=content != "fail-once", final_status_code=200)

    with patch.object(
        info_gatherer.queries, "get_canned_responses_for_hotel", new_callable=AsyncMock
    ) as get_schemas, patch.object(info_gatherer, "send_with_retry", side_effect=fake_send), patch.object(
        info_gatherer.asyncio, "sleep", new_callable=AsyncMock
    ):
        get_schemas.side_effect = [
            ["a1"],
            ["fail-once", "b2"],
        ]
        sent = await info_gatherer._send_all_eligible_hotel_responses(
            conv_id, cwid, [h1, h2], escalate_if_none_sent=True,
        )

    assert sent == 2
    assert calls == ["a1", "fail-once", "b2", "fail-once"]


@pytest.mark.asyncio
async def test_should_escalate_when_no_messages_sent_for_real_hotels():
    conv_id = uuid.uuid4()
    hotel_id = uuid.uuid4()

    with patch.object(
        info_gatherer.queries, "get_canned_responses_for_hotel", new_callable=AsyncMock, return_value=[]
    ), patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), patch.object(
        info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock
    ) as escalate, patch.object(
        info_gatherer, "_write_human_needed_label", new_callable=AsyncMock
    ):
        sent = await info_gatherer._send_all_eligible_hotel_responses(
            conv_id, 1, [hotel_id], escalate_if_none_sent=True,
        )

    assert sent == 0
    escalate.assert_awaited_once()
