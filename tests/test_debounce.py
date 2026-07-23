"""
Unit tests for inbound message debounce (Spec 020 Part E + Spec 020.2 cadence rework).

Covers the cadence-anchored timer, burst coalescing into a single fragment set,
human-takeover cancellation, and the per-conversation processing lock.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.webhooks import chatwoot


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_debounce_state():
    chatwoot._debounce_buffers.clear()
    chatwoot._processing_locks.clear()
    yield
    chatwoot._debounce_buffers.clear()
    chatwoot._processing_locks.clear()


@pytest.fixture(autouse=True)
def _passthrough_first_sight_backfill():
    """Most debounce tests use MagicMock conversations without history_backfilled_at."""
    async def _allow(conv, _cwid):
        return True, conv

    with patch.object(
        chatwoot, "_maybe_abstain_after_first_sight_backfill", side_effect=_allow
    ):
        yield


# ---------------------------------------------------------------------------
# _enqueue_debounced_inbound
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_process_immediately_when_debounce_disabled():
    with patch.object(chatwoot.settings, "debounce_window_seconds", 0), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(
            99, "merhaba", 1, _now(), contact_phone="905551839644",
        )

    process.assert_awaited_once()
    kwargs = process.await_args.kwargs
    assert kwargs["chatwoot_conversation_id"] == 99
    assert kwargs["contact_phone"] == "905551839644"
    assert [f.content for f in kwargs["fragments"]] == ["merhaba"]


@pytest.mark.asyncio
async def test_should_coalesce_burst_messages_into_one_turn():
    """Burst coalesce must complete via the production timer→flush path (not a foreign flush)."""
    base = _now()

    with patch.object(chatwoot.settings, "debounce_window_seconds", 3), \
         patch.object(chatwoot.asyncio, "sleep", new_callable=AsyncMock), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(100, "fiyat ne", 1, base, contact_phone="905551839644")
        await chatwoot._enqueue_debounced_inbound(100, "İTÜ", 2, base)
        await chatwoot._enqueue_debounced_inbound(100, "kız", 3, base)
        timer = chatwoot._debounce_buffers[100].task
        assert timer is not None
        await timer

    process.assert_awaited_once()
    kwargs = process.await_args.kwargs
    assert kwargs["chatwoot_conversation_id"] == 100
    assert kwargs["contact_phone"] == "905551839644"
    assert [f.content for f in kwargs["fragments"]] == ["fiyat ne", "İTÜ", "kız"]
    assert [f.chatwoot_message_id for f in kwargs["fragments"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_should_complete_process_inbound_when_flush_runs_on_timer_task():
    """
    Production path: _timer → _flush_debounce → _pop_debounce_state must not
    cancel the timer mid-flush (self-cancel regression).
    """
    with patch.object(chatwoot.settings, "debounce_window_seconds", 3), \
         patch.object(chatwoot.asyncio, "sleep", new_callable=AsyncMock), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(400, "merhaba", 1, _now())
        timer = chatwoot._debounce_buffers[400].task
        assert timer is not None
        await timer

    process.assert_awaited_once()
    kwargs = process.await_args.kwargs
    assert kwargs["chatwoot_conversation_id"] == 400
    assert [f.content for f in kwargs["fragments"]] == ["merhaba"]
    assert 400 not in chatwoot._debounce_buffers


@pytest.mark.asyncio
async def test_should_not_cancel_current_task_when_pop_during_flush():
    """_pop_debounce_state must not cancel the task that is currently flushing."""
    current = asyncio.current_task()
    assert current is not None
    state = chatwoot._DebounceState(chatwoot_conversation_id=401)
    state.task = current
    chatwoot._debounce_buffers[401] = state

    popped = chatwoot._pop_debounce_state(401)

    assert popped is state
    assert 401 not in chatwoot._debounce_buffers
    assert not current.cancelling()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_should_cancel_prior_timer_when_new_fragment_arrives():
    """A newer fragment must cancel the prior timer and coalesce both into one turn."""
    base = _now()

    with patch.object(chatwoot.settings, "debounce_window_seconds", 3), \
         patch.object(chatwoot.asyncio, "sleep", new_callable=AsyncMock), \
         patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
        await chatwoot._enqueue_debounced_inbound(402, "a", 1, base)
        task_a = chatwoot._debounce_buffers[402].task
        assert task_a is not None

        await chatwoot._enqueue_debounced_inbound(402, "b", 2, base)
        # Capture the new timer before awaiting (awaiting would let flush clear the buffer).
        task_b = chatwoot._debounce_buffers[402].task
        assert task_b is not None
        assert task_b is not task_a
        assert task_a.cancelling() or task_a.cancelled() or task_a.done()

        await task_b

    process.assert_awaited_once()
    assert [f.content for f in process.await_args.kwargs["fragments"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_should_persist_buffered_inbound_on_pending_debounce_flush_without_turn():
    fake_conv = MagicMock()
    fake_conv.id = uuid.uuid4()

    with patch.object(chatwoot.queries, "upsert_conversation", new_callable=AsyncMock, return_value=fake_conv), \
         patch.object(chatwoot.queries, "insert_message", new_callable=AsyncMock) as insert, \
         patch.object(chatwoot.settings, "debounce_window_seconds", 3):
        await chatwoot._enqueue_debounced_inbound(202, "merhaba", 9, _now())
        await chatwoot._persist_pending_debounce(202)

    insert.assert_awaited_once()
    assert 202 not in chatwoot._debounce_buffers


@pytest.mark.asyncio
async def test_should_discard_buffer_on_human_takeover_cancel():
    with patch.object(chatwoot.settings, "debounce_window_seconds", 3), \
         patch.object(chatwoot.asyncio, "sleep", new_callable=AsyncMock):
        await chatwoot._enqueue_debounced_inbound(101, "fiyat ne", 1, _now())
        assert 101 in chatwoot._debounce_buffers

        chatwoot._cancel_debounce(101)
        assert 101 not in chatwoot._debounce_buffers

        with patch.object(chatwoot, "_process_inbound", new_callable=AsyncMock) as process:
            await chatwoot._flush_debounce(101)

        process.assert_not_awaited()


# ---------------------------------------------------------------------------
# _compute_flush_wait — cadence anchoring
# ---------------------------------------------------------------------------

def test_should_wait_full_window_for_fresh_message():
    now = _now()
    wait = chatwoot._compute_flush_wait(now, 3.0, now=now)
    assert wait == pytest.approx(3.0)


def test_should_subtract_pipeline_latency_from_window():
    now = _now()
    sent_two_seconds_ago = now - timedelta(seconds=2)
    wait = chatwoot._compute_flush_wait(sent_two_seconds_ago, 3.0, now=now)
    assert wait == pytest.approx(1.0)


def test_should_floor_wait_when_message_older_than_window():
    now = _now()
    sent_five_seconds_ago = now - timedelta(seconds=5)
    wait = chatwoot._compute_flush_wait(sent_five_seconds_ago, 3.0, now=now)
    assert wait == pytest.approx(chatwoot._MIN_FLUSH_DELAY)


# ---------------------------------------------------------------------------
# _parse_sent_at — timestamp extraction
# ---------------------------------------------------------------------------

def test_should_parse_epoch_seconds_from_message_payload():
    result = chatwoot._parse_sent_at({"created_at": 1_752_000_000}, {})
    assert result == datetime.fromtimestamp(1_752_000_000, tz=timezone.utc)


def test_should_parse_epoch_milliseconds():
    result = chatwoot._parse_sent_at({"created_at": 1_752_000_000_000}, {})
    assert result == datetime.fromtimestamp(1_752_000_000, tz=timezone.utc)


def test_should_parse_iso_string_with_trailing_z():
    result = chatwoot._parse_sent_at({"created_at": "2026-07-10T12:23:45Z"}, {})
    assert result == datetime(2026, 7, 10, 12, 23, 45, tzinfo=timezone.utc)


def test_should_fall_back_to_top_level_created_at():
    result = chatwoot._parse_sent_at({}, {"created_at": 1_752_000_000})
    assert result == datetime.fromtimestamp(1_752_000_000, tz=timezone.utc)


def test_should_fall_back_to_now_when_timestamp_absent():
    before = _now()
    result = chatwoot._parse_sent_at({}, {})
    after = _now()
    assert before <= result <= after


def test_should_fall_back_to_now_when_timestamp_malformed():
    before = _now()
    result = chatwoot._parse_sent_at({"created_at": "not-a-date"}, {})
    after = _now()
    assert before <= result <= after


# ---------------------------------------------------------------------------
# _get_processing_lock + serialization
# ---------------------------------------------------------------------------

def test_should_return_same_lock_for_same_conversation():
    lock_a = chatwoot._get_processing_lock(555)
    lock_b = chatwoot._get_processing_lock(555)
    assert lock_a is lock_b


def test_should_return_distinct_locks_for_distinct_conversations():
    assert chatwoot._get_processing_lock(1) is not chatwoot._get_processing_lock(2)


@pytest.mark.asyncio
async def test_should_serialize_process_inbound_per_conversation():
    order: list[str] = []

    async def fake_process_message(conversation, cwid, content, chatwoot_message_id=None):
        order.append(f"start:{content}")
        await asyncio.sleep(0)  # force a yield so an unlocked path would interleave
        order.append(f"end:{content}")

    fake_conv = MagicMock()
    fake_conv.id = uuid.uuid4()

    def _fragments(text: str, mid: int):
        return [chatwoot._DebounceFragment(content=text, chatwoot_message_id=mid, sent_at=_now())]

    with patch.object(chatwoot.queries, "upsert_conversation", new_callable=AsyncMock, return_value=fake_conv), \
         patch.object(chatwoot.queries, "insert_message", new_callable=AsyncMock), \
         patch("app.layers.info_gatherer.process_message", new=fake_process_message):
        await asyncio.gather(
            chatwoot._process_inbound(chatwoot_conversation_id=300, contact_phone=None, fragments=_fragments("A", 1)),
            chatwoot._process_inbound(chatwoot_conversation_id=300, contact_phone=None, fragments=_fragments("B", 2)),
        )

    # With the per-conversation lock, one turn fully completes before the next starts.
    assert order in (
        ["start:A", "end:A", "start:B", "end:B"],
        ["start:B", "end:B", "start:A", "end:A"],
    )


@pytest.mark.asyncio
async def test_should_persist_each_fragment_and_process_combined_content():
    fake_conv = MagicMock()
    fake_conv.id = uuid.uuid4()

    fragments = [
        chatwoot._DebounceFragment(content="fiyat ne", chatwoot_message_id=5, sent_at=_now()),
        chatwoot._DebounceFragment(content="İTÜ", chatwoot_message_id=3, sent_at=_now()),
        chatwoot._DebounceFragment(content="kız", chatwoot_message_id=9, sent_at=_now()),
    ]

    async def fake_process_message(conversation, cwid, content, chatwoot_message_id=None):
        fake_process_message.seen = (content, chatwoot_message_id)

    with patch.object(chatwoot.queries, "upsert_conversation", new_callable=AsyncMock, return_value=fake_conv), \
         patch.object(chatwoot.queries, "insert_message", new_callable=AsyncMock) as insert, \
         patch("app.layers.info_gatherer.process_message", new=fake_process_message):
        await chatwoot._process_inbound(
            chatwoot_conversation_id=42, contact_phone="905551839644", fragments=fragments,
        )

    assert insert.await_count == 3
    # Combined content joins fragments in order; first_message_id is the burst minimum.
    assert fake_process_message.seen == ("fiyat ne\nİTÜ\nkız", 3)
