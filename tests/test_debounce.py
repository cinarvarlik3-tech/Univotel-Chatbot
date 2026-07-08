"""
Unit tests for inbound message debounce (Spec 020 Part E).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks import chatwoot


@pytest.fixture(autouse=True)
def _clear_debounce_state():
    chatwoot._debounce_buffers.clear()
    yield
    chatwoot._debounce_buffers.clear()


@pytest.mark.asyncio
async def test_should_process_immediately_when_debounce_disabled():
    conv_id = uuid.uuid4()

    with patch.object(chatwoot.settings, "debounce_window_seconds", 0), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(conv_id, 99, "merhaba", 1)

    process.assert_awaited_once_with(conv_id, 99, "merhaba", 1)


@pytest.mark.asyncio
async def test_should_coalesce_burst_messages_into_one_turn():
    conv_id = uuid.uuid4()

    with patch.object(chatwoot.settings, "debounce_window_seconds", 3), \
         patch.object(chatwoot.asyncio, "sleep", new_callable=AsyncMock), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(conv_id, 100, "fiyat ne", 1)
        await chatwoot._enqueue_debounced_inbound(conv_id, 100, "İTÜ", 2)
        await chatwoot._enqueue_debounced_inbound(conv_id, 100, "kız", 3)
        await chatwoot._flush_debounce(100)

    process.assert_awaited_once()
    assert process.await_args.kwargs == {
        "conversation_id": conv_id,
        "chatwoot_conversation_id": 100,
        "content": "fiyat ne\nİTÜ\nkız",
        "chatwoot_message_id": 3,
    }


@pytest.mark.asyncio
async def test_should_discard_buffer_on_human_takeover_cancel():
    conv_id = uuid.uuid4()

    with patch.object(chatwoot.settings, "debounce_window_seconds", 3):
        await chatwoot._enqueue_debounced_inbound(conv_id, 101, "fiyat ne", 1)
        assert 101 in chatwoot._debounce_buffers
        chatwoot._cancel_debounce(101)
        assert 101 not in chatwoot._debounce_buffers

        with patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
            await chatwoot._flush_debounce(101)

        process.assert_not_awaited()
