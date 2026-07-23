"""InfoGatherer hangi suppression when Chatwoot automation already fired (Spec 031 C5)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation
from app.layers import info_gatherer


@pytest.mark.asyncio
async def test_should_not_send_hangi_when_automation_outbound_exists():
    conv = Conversation(id=uuid.uuid4(), chatwoot_conversation_id=1, flow_state="new")
    with patch.object(
        info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True
    ), patch.object(
        info_gatherer.queries, "has_automation_outbound", new_callable=AsyncMock, return_value=True
    ), patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send_mock:
        await info_gatherer._activate_flow(conv, 1, "new")
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_send_hangi_when_no_automation_outbound():
    conv = Conversation(id=uuid.uuid4(), chatwoot_conversation_id=1, flow_state="new")
    with patch.object(
        info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True
    ), patch.object(
        info_gatherer.queries, "has_automation_outbound", new_callable=AsyncMock, return_value=False
    ), patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send_mock:
        await info_gatherer._activate_flow(conv, 1, "new")
    send_mock.assert_awaited_once()
