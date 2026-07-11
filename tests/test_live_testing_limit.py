"""Unit tests for LIVE_TESTING_LIMIT ingestion cap (Spec 022 Part B)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks.chatwoot import _is_live_testing_new_conversation_rejected


@pytest.mark.asyncio
async def test_should_not_reject_when_live_testing_mode_off(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "live_testing_mode", False)
    with patch(
        "app.webhooks.chatwoot.queries.get_conversation_by_chatwoot_id",
        new_callable=AsyncMock,
    ) as mock_get:
        result = await _is_live_testing_new_conversation_rejected(99)
    assert result is False
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_should_not_reject_existing_conversation_past_limit(monkeypatch):
    from app import config
    from app.db.models import Conversation
    import uuid

    monkeypatch.setattr(config.settings, "live_testing_mode", True)
    monkeypatch.setattr(config.settings, "live_testing_limit", 2)
    existing = Conversation(id=uuid.uuid4(), chatwoot_conversation_id=99, flow_state="new")
    with patch(
        "app.webhooks.chatwoot.queries.get_conversation_by_chatwoot_id",
        new_callable=AsyncMock,
        return_value=existing,
    ), patch(
        "app.webhooks.chatwoot.queries.count_live_testing_conversations",
        new_callable=AsyncMock,
    ) as mock_count:
        result = await _is_live_testing_new_conversation_rejected(99)
    assert result is False
    mock_count.assert_not_called()


@pytest.mark.asyncio
async def test_should_reject_new_conversation_when_at_limit(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "live_testing_mode", True)
    monkeypatch.setattr(config.settings, "live_testing_limit", 10)
    with patch(
        "app.webhooks.chatwoot.queries.get_conversation_by_chatwoot_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.webhooks.chatwoot.queries.count_live_testing_conversations",
        new_callable=AsyncMock,
        return_value=10,
    ):
        result = await _is_live_testing_new_conversation_rejected(42)
    assert result is True


@pytest.mark.asyncio
async def test_should_admit_new_conversation_when_below_limit(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "live_testing_mode", True)
    monkeypatch.setattr(config.settings, "live_testing_limit", 10)
    with patch(
        "app.webhooks.chatwoot.queries.get_conversation_by_chatwoot_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.webhooks.chatwoot.queries.count_live_testing_conversations",
        new_callable=AsyncMock,
        return_value=9,
    ):
        result = await _is_live_testing_new_conversation_rejected(42)
    assert result is False


@pytest.mark.asyncio
async def test_count_live_testing_conversations_uses_total_rows():
    from app.db import queries

    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={"n": 7})
    with patch("app.db.queries.get_pool", return_value=mock_pool):
        count = await queries.count_live_testing_conversations()
    assert count == 7
    mock_pool.fetchrow.assert_awaited_once_with("SELECT count(*) AS n FROM conversations")
