"""Router integration tests for context backfill wiring (spec 024)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, Message


def _conv() -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        chatwoot_conversation_id=1142,
        flow_state="new",
    )


@pytest.mark.asyncio
async def test_should_backfill_before_transcript_read_on_full_history_trigger():
    conv = _conv()
    messages = [
        Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            chatwoot_message_id=1,
            message_type="inbound",
            content="hi",
        )
    ]

    with patch("app.tagassigner.router.queries.get_tagassigner_run", new_callable=AsyncMock, return_value=None), \
         patch("app.tagassigner.router.queries.get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch("app.tagassigner.router.get_labels", new_callable=AsyncMock, return_value=[]), \
         patch("app.tagassigner.router.backfill_conversation_messages", new_callable=AsyncMock, return_value=5) as backfill_mock, \
         patch("app.tagassigner.router.queries.get_messages_for_conversation", new_callable=AsyncMock, return_value=messages) as get_msgs_mock, \
         patch("app.tagassigner.router.load_formatted_university_list_lines", new_callable=AsyncMock, return_value=[]), \
         patch("app.tagassigner.router.build_payload", return_value={"system_prompt": "p", "user_content": "u"}), \
         patch("app.tagassigner.router.call_llm", new_callable=AsyncMock, return_value=None), \
         patch("app.tagassigner.router.queries.update_tagassigner_run_failed", new_callable=AsyncMock), \
         patch("app.tagassigner.router._log", new_callable=AsyncMock):
        from app.tagassigner.router import run_tagging
        await run_tagging(conv.id, uuid.uuid4(), "sweep", read_full_history=True)

    backfill_mock.assert_awaited_once_with(conv.id, conv.chatwoot_conversation_id)
    get_msgs_mock.assert_awaited_once_with(conv.id)


@pytest.mark.asyncio
async def test_should_not_backfill_on_message_trigger():
    conv = _conv()

    with patch("app.tagassigner.router.queries.get_tagassigner_run", new_callable=AsyncMock, return_value=None), \
         patch("app.tagassigner.router.queries.get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch("app.tagassigner.router.get_labels", new_callable=AsyncMock, return_value=[]), \
         patch("app.tagassigner.router.backfill_conversation_messages", new_callable=AsyncMock) as backfill_mock, \
         patch("app.tagassigner.router._get_last_successful_run", new_callable=AsyncMock, return_value=None), \
         patch("app.tagassigner.router.queries.get_messages_for_conversation", new_callable=AsyncMock, return_value=[]), \
         patch("app.tagassigner.router.load_formatted_university_list_lines", new_callable=AsyncMock, return_value=[]), \
         patch("app.tagassigner.router.build_payload", return_value={"system_prompt": "p", "user_content": "u"}), \
         patch("app.tagassigner.router.call_llm", new_callable=AsyncMock, return_value=None), \
         patch("app.tagassigner.router.queries.update_tagassigner_run_failed", new_callable=AsyncMock), \
         patch("app.tagassigner.router._log", new_callable=AsyncMock):
        from app.tagassigner.router import run_tagging
        await run_tagging(conv.id, uuid.uuid4(), "message", read_full_history=False)

    backfill_mock.assert_not_awaited()
