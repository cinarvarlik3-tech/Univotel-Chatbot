"""
Unit tests for deterministic slot-skip before divergence classifier (spec §7).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, University, UniversityAlias
from app.layers import info_gatherer


def _conv(**kwargs) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "chatwoot_conversation_id": 52,
        "flow_state": "awaiting_university",
        "university_id": None,
        "gender": None,
    }
    defaults.update(kwargs)
    return Conversation(**defaults)


def _uni(name: str) -> University:
    return University(id=uuid.uuid4(), name=name)


@pytest.mark.asyncio
async def test_should_extract_both_slots_and_fire_recengine():
    conv = _conv(flow_state="awaiting_university")
    bogazici = _uni("Boğaziçi Üniversitesi")

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[bogazici]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True), \
         patch.object(info_gatherer.queries, "get_conversation_by_id", new_callable=AsyncMock) as get_conv, \
         patch.object(info_gatherer.queries, "set_conversation_gender", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_fire_rec_engine_if_ready", new_callable=AsyncMock) as rec, \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock):
        get_conv.return_value = _conv(
            flow_state="awaiting_gender",
            university_id=bogazici.id,
            gender="male",
        )
        result = await info_gatherer._try_extract_slots_and_advance(
            conv, 52, "Boğaziçi, erkek",
        )

    assert result is True
    rec.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_return_false_when_no_slots_extracted():
    conv = _conv(flow_state="awaiting_university")

    with patch.object(info_gatherer.queries, "get_all_hotels", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]):
        result = await info_gatherer._try_extract_slots_and_advance(conv, 52, "fiyat ne kadar")

    assert result is False


@pytest.mark.asyncio
async def test_should_fire_hotel_path_mid_flow_in_awaiting_university():
    conv = _conv(flow_state="awaiting_university")
    hotel_id = uuid.uuid4()
    hotel = type("Hotel", (), {"id": hotel_id, "name": "Keten Suites", "is_visible": True})()

    with patch.object(info_gatherer.queries, "get_all_hotels", new_callable=AsyncMock, return_value=[hotel]), \
         patch.object(info_gatherer, "_fire_hotel_path", new_callable=AsyncMock) as hotel_path:
        await info_gatherer._process_pre_recengine_turn(
            conv, 52, "Keten Suites hakkında bilgi",
            flow_state="awaiting_university",
            fallback="escalate_off_script",
        )

    hotel_path.assert_awaited_once_with(conv, 52, hotel_id)


@pytest.mark.asyncio
async def test_should_extract_gender_before_university_in_combined_reply():
    conv = _conv(flow_state="awaiting_university")
    parent_id = uuid.uuid4()
    itu_alias = UniversityAlias(id=uuid.uuid4(), parent_university_id=parent_id, alias="itu")

    with patch.object(info_gatherer.queries, "get_all_hotels", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[itu_alias]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "set_conversation_gender", new_callable=AsyncMock) as set_gender, \
         patch.object(info_gatherer.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(info_gatherer, "_handle_parent_match", new_callable=AsyncMock, return_value=True) as parent_match, \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock):
        result = await info_gatherer._run_deterministic_extraction(
            conv, 52, "itu kız", "awaiting_university",
        )

    assert result == "progress"
    set_gender.assert_awaited_once_with(conv.id, "female")
    parent_match.assert_awaited_once()
    assert parent_match.await_args.kwargs.get("content") == "itu kız"
