"""
Unit tests for RecEngine sentinel selection on NOT_FOUND.
Mocks DB queries — no live Supabase required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, Hotel
from app.db import queries
from app.layers import rec_engine
from app.layers.rec_engine import RecStatus, _resolve_not_found_sentinel, _select_hotel


def _conv(university_id: uuid.UUID, gender: str = "female") -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        chatwoot_conversation_id=52,
        flow_state="recengine_running",
        university_id=university_id,
        gender=gender,
    )


@pytest.mark.asyncio
async def test_should_return_deal_awaiting_state_when_not_on_list():
    uni_id = uuid.uuid4()
    with patch.object(queries, "is_deal_awaiting_university", new_callable=AsyncMock, return_value=False):
        sentinel = await _resolve_not_found_sentinel(uni_id)
    assert sentinel == queries.DEAL_AWAITING_STATE_ID


@pytest.mark.asyncio
async def test_should_return_label_state_when_on_deal_awaiting_list():
    uni_id = uuid.uuid4()
    with patch.object(queries, "is_deal_awaiting_university", new_callable=AsyncMock, return_value=True):
        sentinel = await _resolve_not_found_sentinel(uni_id)
    assert sentinel == queries.DEAL_AWAITING_LABEL_STATE_ID


@pytest.mark.asyncio
async def test_should_return_deal_awaiting_state_when_candidates_empty_and_not_on_list():
    uni_id = uuid.uuid4()
    conv = _conv(uni_id)
    with patch.object(
        queries, "get_conversation_by_chatwoot_id_by_id", new_callable=AsyncMock, return_value=conv
    ), patch.object(
        queries, "find_hotels_by_gender_and_university", new_callable=AsyncMock, return_value=[]
    ), patch.object(
        queries, "is_deal_awaiting_university", new_callable=AsyncMock, return_value=False
    ):
        result = await _select_hotel(conv.id)
    assert result.status == RecStatus.NOT_FOUND
    assert result.hotel_ids == [queries.DEAL_AWAITING_STATE_ID]


@pytest.mark.asyncio
async def test_should_return_label_state_when_candidates_empty_and_on_list():
    uni_id = uuid.uuid4()
    conv = _conv(uni_id, gender="male")
    with patch.object(
        queries, "get_conversation_by_chatwoot_id_by_id", new_callable=AsyncMock, return_value=conv
    ), patch.object(
        queries, "find_hotels_by_gender_and_university", new_callable=AsyncMock, return_value=[]
    ), patch.object(
        queries, "is_deal_awaiting_university", new_callable=AsyncMock, return_value=True
    ):
        result = await _select_hotel(conv.id)
    assert result.status == RecStatus.NOT_FOUND
    assert result.hotel_ids == [queries.DEAL_AWAITING_LABEL_STATE_ID]


@pytest.mark.asyncio
async def test_should_return_found_when_on_list_but_hotel_exists():
    uni_id = uuid.uuid4()
    hotel_id = uuid.uuid4()
    conv = _conv(uni_id)
    hotel = Hotel(id=hotel_id, name="Test Dorm", gender_scope="female", priority_score=100)
    with patch.object(
        queries, "get_conversation_by_chatwoot_id_by_id", new_callable=AsyncMock, return_value=conv
    ), patch.object(
        queries, "find_hotels_by_gender_and_university", new_callable=AsyncMock, return_value=[hotel]
    ), patch.object(
        queries, "get_hotel_by_id", new_callable=AsyncMock, return_value=hotel
    ):
        result = await _select_hotel(conv.id)
    assert result.status == RecStatus.FOUND
    assert result.hotel_ids == [hotel_id]


@pytest.mark.asyncio
async def test_should_return_all_eligible_hotels_ordered_by_query():
    uni_id = uuid.uuid4()
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    conv = _conv(uni_id)
    hotels = [
        Hotel(id=id_a, name="High", gender_scope="mixed", priority_score=100),
        Hotel(id=id_b, name="Low", gender_scope="mixed", priority_score=50),
    ]
    with patch.object(
        queries, "get_conversation_by_chatwoot_id_by_id", new_callable=AsyncMock, return_value=conv
    ), patch.object(
        queries, "find_hotels_by_gender_and_university", new_callable=AsyncMock, return_value=hotels
    ), patch.object(
        queries, "get_hotel_by_id", new_callable=AsyncMock, side_effect=lambda hid: next(h for h in hotels if h.id == hid)
    ):
        result = await _select_hotel(conv.id)
    assert result.status == RecStatus.FOUND
    assert result.hotel_ids == [id_a, id_b]


@pytest.mark.asyncio
async def test_should_pass_sentinel_hotel_id_to_callback_on_not_found():
    conv_id = uuid.uuid4()
    key = uuid.uuid4()
    sentinel = queries.DEAL_AWAITING_LABEL_STATE_ID
    not_found = rec_engine.RecResult(status=RecStatus.NOT_FOUND, hotel_ids=[sentinel])

    with patch.object(queries, "insert_rec_engine_processing", new_callable=AsyncMock), \
         patch.object(queries, "get_rec_engine_log", new_callable=AsyncMock, return_value=None), \
         patch.object(rec_engine, "_select_hotels", new_callable=AsyncMock, return_value=not_found), \
         patch.object(queries, "update_rec_engine_log", new_callable=AsyncMock), \
         patch.object(rec_engine, "_fire_callback", new_callable=AsyncMock) as callback:
        await rec_engine.run_rec_engine(conv_id, key)

    callback.assert_awaited_once_with(conv_id, sentinel, RecStatus.NOT_FOUND, hotel_recs=None)
