"""Unit tests for sweep operations and tag private-note parsing (spec 021)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation
from app.tagassigner.sweep import VALID_OPERATIONS, run_sweep
from app.webhooks.chatwoot import _parse_tag_private_note


def _conv() -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        chatwoot_conversation_id=1,
        flow_state="new",
    )


# ---------------------------------------------------------------------------
# _parse_tag_private_note
# ---------------------------------------------------------------------------

def test_should_parse_single_token_tag_as_manual():
    assert _parse_tag_private_note("tag") == {"kind": "manual"}


def test_should_parse_tag_case_insensitive():
    assert _parse_tag_private_note("TAG") == {"kind": "manual"}


def test_should_reject_sweep_from_chat():
    assert _parse_tag_private_note("tag sweep") == {"kind": "reject"}
    assert _parse_tag_private_note("tag sweep 5") == {"kind": "reject"}


def test_should_reject_unrecognized_operation():
    assert _parse_tag_private_note("tag foo") == {"kind": "reject"}


def test_should_default_limit_to_20_for_sweep_safe():
    result = _parse_tag_private_note("tag sweepSafe")
    assert result == {"kind": "sweep", "operation": "sweepSafe", "limit": 20}


def test_should_accept_sweep_empty_with_limit():
    result = _parse_tag_private_note("tag sweepEmpty 10")
    assert result == {"kind": "sweep", "operation": "sweepEmpty", "limit": 10}


def test_should_reject_limit_above_20():
    assert _parse_tag_private_note("tag sweepSafe 21") == {"kind": "reject"}


def test_should_reject_non_numeric_limit():
    assert _parse_tag_private_note("tag sweepSafe abc") == {"kind": "reject"}


def test_should_reject_zero_limit():
    assert _parse_tag_private_note("tag sweepSafe 0") == {"kind": "reject"}


def test_should_return_none_for_non_tag_command():
    assert _parse_tag_private_note("hello") is None


# ---------------------------------------------------------------------------
# run_sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_enqueue_matched_conversations_for_sweep_safe():
    convos = [_conv(), _conv()]
    with patch(
        "app.tagassigner.sweep.queries.get_conversations_for_sweep_safe",
        new_callable=AsyncMock,
        return_value=convos,
    ), patch(
        "app.tagassigner.sweep.queries.enqueue_tagassigner_run",
        new_callable=AsyncMock,
        side_effect=[True, False],
    ) as mock_enqueue:
        count = await run_sweep("sweepSafe", 10)

    assert count == 1
    assert mock_enqueue.await_count == 2
    for call in mock_enqueue.await_args_list:
        assert call.kwargs.get("trigger_type") == "sweep"


@pytest.mark.asyncio
async def test_should_raise_for_unknown_operation():
    with pytest.raises(ValueError, match="unknown sweep operation"):
        await run_sweep("invalid", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,query_name", [
    ("sweep", "get_conversations_for_sweep"),
    ("sweepEmpty", "get_conversations_for_sweep_empty"),
    ("sweepSafe", "get_conversations_for_sweep_safe"),
])
async def test_should_dispatch_to_correct_query(operation, query_name):
    convo = _conv()
    with patch(
        f"app.tagassigner.sweep.queries.{query_name}",
        new_callable=AsyncMock,
        return_value=[convo],
    ), patch(
        "app.tagassigner.sweep.queries.enqueue_tagassigner_run",
        new_callable=AsyncMock,
        return_value=True,
    ):
        count = await run_sweep(operation, 5)
    assert count == 1


def test_valid_operations_tuple():
    assert set(VALID_OPERATIONS) == {"sweep", "sweepEmpty", "sweepSafe"}


# ---------------------------------------------------------------------------
# label_resolver deal_awaiting guards
# ---------------------------------------------------------------------------

def test_should_strip_gemini_proposed_deal_awaiting():
    from app.tagassigner.label_resolver import resolve_labels, strip_gemini_deal_awaiting

    assert strip_gemini_deal_awaiting(["ogrenci", "deal_awaiting"]) == ["ogrenci"]
    result = resolve_labels([], ["ogrenci", "deal_awaiting"])
    assert "deal_awaiting" not in result


def test_should_preserve_existing_deal_awaiting_in_resolve_labels():
    from app.tagassigner.label_resolver import resolve_labels

    before = ["deal_awaiting", "ogrenci"]
    proposed = ["ogrenci"]
    result = resolve_labels(before, proposed)
    assert "deal_awaiting" in result
