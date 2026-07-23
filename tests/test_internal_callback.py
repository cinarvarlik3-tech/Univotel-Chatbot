"""
Unit tests for RecEngine → InfoGatherer callback (sentinel pass-through and labels).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation
from app.db import queries
from app.webhooks import internal


def _conversation(**kwargs) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "chatwoot_conversation_id": 52,
        "flow_state": "recengine_running",
    }
    defaults.update(kwargs)
    return Conversation(**defaults)


@pytest.mark.asyncio
async def test_should_write_deal_awaiting_label_on_label_state_sentinel():
    conv = _conversation()
    body = internal.RecEngineCallbackRequest(
        conversation_id=conv.id,
        hotel_rec=queries.DEAL_AWAITING_LABEL_STATE_ID,
        status="200_NOT_FOUND",
    )
    with patch.object(internal.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(internal.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True), \
         patch("app.layers.info_gatherer._send_hotel_responses", new_callable=AsyncMock) as send, \
         patch("app.layers.info_gatherer._write_deal_awaiting_label", new_callable=AsyncMock) as write_label, \
         patch("app.tagassigner.attribute_resolver.write_attributes_at_flow_completion", new_callable=AsyncMock), \
         patch.object(internal, "verify_internal_secret"):
        resp = await internal.rec_engine_callback(body, x_internal_secret="test")

    assert resp.status_code == 200
    send.assert_awaited_once_with(conv.id, 52, queries.DEAL_AWAITING_LABEL_STATE_ID)
    write_label.assert_awaited_once_with(52)


@pytest.mark.asyncio
async def test_should_send_all_hotels_on_found_with_hotel_recs():
    conv = _conversation()
    h1, h2 = uuid.uuid4(), uuid.uuid4()
    body = internal.RecEngineCallbackRequest(
        conversation_id=conv.id,
        hotel_rec=h1,
        hotel_recs=[h1, h2],
        status="200_FOUND",
    )
    with patch.object(internal.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(internal.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True), \
         patch("app.layers.info_gatherer._send_all_eligible_hotel_responses", new_callable=AsyncMock) as send_all, \
         patch("app.tagassigner.attribute_resolver.write_attributes_at_flow_completion", new_callable=AsyncMock), \
         patch.object(internal, "verify_internal_secret"):
        resp = await internal.rec_engine_callback(body, x_internal_secret="test")

    assert resp.status_code == 200
    send_all.assert_awaited_once_with(conv.id, 52, [h1, h2], escalate_if_none_sent=True)


@pytest.mark.asyncio
async def test_should_escalate_when_found_payload_contains_sentinel():
    conv = _conversation()
    body = internal.RecEngineCallbackRequest(
        conversation_id=conv.id,
        hotel_recs=[queries.DEAL_AWAITING_STATE_ID],
        status="200_FOUND",
    )
    with patch.object(internal.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(internal.queries, "set_conversation_human_needed", new_callable=AsyncMock) as escalate, \
         patch("app.layers.info_gatherer._write_human_needed_label", new_callable=AsyncMock), \
         patch.object(internal, "verify_internal_secret"):
        resp = await internal.rec_engine_callback(body, x_internal_secret="test")

    assert resp.status_code == 200
    escalate.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_not_write_deal_awaiting_label_on_plain_deal_awaiting_state():
    conv = _conversation()
    body = internal.RecEngineCallbackRequest(
        conversation_id=conv.id,
        hotel_rec=queries.DEAL_AWAITING_STATE_ID,
        status="200_NOT_FOUND",
    )
    with patch.object(internal.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(internal.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True), \
         patch("app.layers.info_gatherer._send_hotel_responses", new_callable=AsyncMock), \
         patch("app.layers.info_gatherer._write_deal_awaiting_label", new_callable=AsyncMock) as write_label, \
         patch("app.tagassigner.attribute_resolver.write_attributes_at_flow_completion", new_callable=AsyncMock), \
         patch.object(internal, "verify_internal_secret"):
        await internal.rec_engine_callback(body, x_internal_secret="test")

    write_label.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_fallback_to_global_null_when_hotel_rec_missing():
    conv = _conversation()
    body = internal.RecEngineCallbackRequest(
        conversation_id=conv.id,
        hotel_rec=None,
        status="200_NOT_FOUND",
    )
    with patch.object(internal.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(internal.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True), \
         patch("app.layers.info_gatherer._send_hotel_responses", new_callable=AsyncMock) as send, \
         patch("app.layers.info_gatherer._write_deal_awaiting_label", new_callable=AsyncMock), \
         patch("app.tagassigner.attribute_resolver.write_attributes_at_flow_completion", new_callable=AsyncMock), \
         patch.object(internal, "verify_internal_secret"):
        await internal.rec_engine_callback(body, x_internal_secret="test")

    send.assert_awaited_once_with(conv.id, 52, queries.GLOBAL_NULL_STATE_ID)
