"""Unit tests for app/tagassigner/context_backfill.py (spec 024)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tagassigner.context_backfill import (
    _map_message_type,
    backfill_conversation_messages,
)


@pytest.mark.asyncio
async def test_should_insert_missing_messages_when_local_table_is_partial():
    conversation_id = uuid.uuid4()
    raw_messages = [
        {
            "id": 101,
            "content": "Merhaba",
            "message_type": 0,
            "private": False,
            "created_at": 1700000000,
            "sender": {"type": "contact", "id": 1, "name": "Lead"},
        },
        {
            "id": 102,
            "content": "Selam",
            "message_type": 1,
            "private": False,
            "created_at": 1700000100,
            "sender": {"type": "user", "id": 2, "name": "Bot"},
        },
    ]

    with patch(
        "app.tagassigner.context_backfill.fetch_all_messages",
        new_callable=AsyncMock,
        return_value=raw_messages,
    ), patch(
        "app.tagassigner.context_backfill.queries.message_exists",
        new_callable=AsyncMock,
        side_effect=[False, True],
    ), patch(
        "app.tagassigner.context_backfill.queries.insert_message",
        new_callable=AsyncMock,
    ) as insert_mock:
        inserted = await backfill_conversation_messages(conversation_id, 1142)

    assert inserted == 1
    insert_mock.assert_awaited_once()
    assert insert_mock.await_args.kwargs["advance_activity"] is False


@pytest.mark.asyncio
async def test_should_skip_private_and_activity_messages():
    conversation_id = uuid.uuid4()
    raw_messages = [
        {"id": 1, "content": "note", "message_type": 1, "private": True, "created_at": 1},
        {"id": 2, "content": "assigned", "message_type": 2, "private": False, "created_at": 2},
        {
            "id": 3,
            "content": "hi",
            "message_type": 0,
            "private": False,
            "created_at": 3,
            "sender": {},
        },
    ]

    with patch(
        "app.tagassigner.context_backfill.fetch_all_messages",
        new_callable=AsyncMock,
        return_value=raw_messages,
    ), patch(
        "app.tagassigner.context_backfill.queries.message_exists",
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        "app.tagassigner.context_backfill.queries.insert_message",
        new_callable=AsyncMock,
    ) as insert_mock:
        inserted = await backfill_conversation_messages(conversation_id, 1)

    assert inserted == 1
    assert insert_mock.await_args.args[3] == "inbound"


def test_should_map_message_type_incoming_to_inbound_and_outgoing_to_outbound():
    assert _map_message_type(0) == "inbound"
    assert _map_message_type(1) == "outbound"
    assert _map_message_type(3) == "outbound"
    assert _map_message_type(2) is None


def test_should_map_sender_type_to_db_allowed_values(monkeypatch):
    from app.tagassigner import context_backfill as cb

    monkeypatch.setattr(cb.settings, "chatwoot_bot_agent_id", 99)
    inbound_type, _, _ = cb._resolve_sender_type({"sender": {"type": "contact", "id": 1}}, "inbound")
    bot_type, _, _ = cb._resolve_sender_type({"sender": {"type": "agent_bot", "id": 99}}, "outbound")
    human_type, _, _ = cb._resolve_sender_type({"sender": {"type": "user", "id": 5}}, "outbound")
    assert inbound_type == "contact"
    assert bot_type == "infoGatherer"
    assert human_type == "user"


@pytest.mark.asyncio
async def test_should_return_zero_when_chatwoot_fetch_fails():
    with patch(
        "app.tagassigner.context_backfill.fetch_all_messages",
        new_callable=AsyncMock,
        return_value=None,
    ):
        inserted = await backfill_conversation_messages(uuid.uuid4(), 99)
    assert inserted == 0


@pytest.mark.asyncio
async def test_should_be_idempotent_when_all_messages_already_present():
    raw_messages = [
        {
            "id": 10,
            "content": "x",
            "message_type": 0,
            "private": False,
            "created_at": 1,
            "sender": {},
        },
    ]
    with patch(
        "app.tagassigner.context_backfill.fetch_all_messages",
        new_callable=AsyncMock,
        return_value=raw_messages,
    ), patch(
        "app.tagassigner.context_backfill.queries.message_exists",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "app.tagassigner.context_backfill.queries.insert_message",
        new_callable=AsyncMock,
    ) as insert_mock:
        inserted = await backfill_conversation_messages(uuid.uuid4(), 1)
    assert inserted == 0
    insert_mock.assert_not_awaited()
