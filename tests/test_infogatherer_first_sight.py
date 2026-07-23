"""First-sight Chatwoot backfill abstention gate (Spec 031 C3)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation
from app.tagassigner.context_backfill import BackfillResult
from app.webhooks import chatwoot


def _conversation(**overrides) -> Conversation:
    base = dict(
        id=uuid.uuid4(),
        chatwoot_conversation_id=500,
        flow_state="new",
        history_backfilled_at=None,
    )
    base.update(overrides)
    return Conversation(**base)


@pytest.mark.asyncio
async def test_should_skip_backfill_when_history_already_marked():
    conv = _conversation(history_backfilled_at=datetime.now(tz=timezone.utc))
    with patch(
        "app.tagassigner.context_backfill.backfill_conversation_messages",
        new_callable=AsyncMock,
    ) as backfill_mock:
        should_run, out = await chatwoot._maybe_abstain_after_first_sight_backfill(conv, 500)
    backfill_mock.assert_not_awaited()
    assert should_run is True
    assert out is conv


@pytest.mark.asyncio
async def test_should_process_when_backfill_inserts_nothing():
    conv = _conversation()
    refreshed = _conversation(id=conv.id, history_backfilled_at=datetime.now(tz=timezone.utc))
    with patch(
        "app.tagassigner.context_backfill.backfill_conversation_messages",
        new_callable=AsyncMock,
        return_value=BackfillResult(ok=True, inserted=0),
    ), patch.object(
        chatwoot.queries, "mark_conversation_history_backfilled", new_callable=AsyncMock
    ), patch.object(
        chatwoot.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=refreshed
    ):
        should_run, out = await chatwoot._maybe_abstain_after_first_sight_backfill(conv, 500)
    assert should_run is True
    assert out.history_backfilled_at is not None


@pytest.mark.asyncio
async def test_should_abstain_prior_history_when_backfill_inserts_rows():
    conv = _conversation()
    with patch(
        "app.tagassigner.context_backfill.backfill_conversation_messages",
        new_callable=AsyncMock,
        return_value=BackfillResult(ok=True, inserted=3),
    ), patch.object(
        chatwoot.queries, "mark_conversation_history_backfilled", new_callable=AsyncMock
    ), patch.object(
        chatwoot.queries, "set_infogatherer_abstain", new_callable=AsyncMock
    ) as set_abstain, patch.object(
        chatwoot.queries, "write_log", new_callable=AsyncMock
    ) as write_log:
        should_run, _ = await chatwoot._maybe_abstain_after_first_sight_backfill(conv, 500)
    assert should_run is False
    set_abstain.assert_awaited_once()
    assert set_abstain.await_args.args[1] == "prior_history"
    write_log.assert_awaited_once()
    assert write_log.await_args.args[0].operation_layer == "infoGatherer"
    assert write_log.await_args.args[0].internal_class == "abstain_prior_history"


@pytest.mark.asyncio
async def test_should_abstain_when_backfill_fetch_fails():
    conv = _conversation()
    with patch(
        "app.tagassigner.context_backfill.backfill_conversation_messages",
        new_callable=AsyncMock,
        return_value=BackfillResult(ok=False, inserted=0),
    ), patch.object(
        chatwoot.queries, "mark_conversation_history_backfilled", new_callable=AsyncMock
    ), patch.object(
        chatwoot.queries, "set_infogatherer_abstain", new_callable=AsyncMock
    ), patch.object(
        chatwoot.queries, "write_log", new_callable=AsyncMock
    ) as write_log:
        should_run, _ = await chatwoot._maybe_abstain_after_first_sight_backfill(conv, 500)
    assert should_run is False
    write_log.assert_awaited_once()
    assert write_log.await_args.args[0].operation_layer == "infoGatherer"
    assert write_log.await_args.args[0].internal_class == "abstain_backfill_failed"
