"""
Unit tests for divergence escalation label writes (Spec 020 Part B).
Every silent-escalate path must set human_needed state AND Chatwoot label.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, DivergenceAction, RoutingDecision
from app.layers.divergence_classifier import ClassificationResult, Intent
from app.layers import info_gatherer


def _conv(**kwargs) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "chatwoot_conversation_id": 52,
        "flow_state": "awaiting_university",
        "last_divergence_intent": None,
        "divergence_repeat_count": 0,
    }
    defaults.update(kwargs)
    return Conversation(**defaults)


@pytest.mark.asyncio
async def test_should_write_human_needed_label_on_divergence_escalate_action():
    conv = _conv()
    decision = RoutingDecision(action=DivergenceAction.ESCALATE)

    with patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock) as set_state, \
         patch.object(info_gatherer, "_write_human_needed_label", new_callable=AsyncMock) as write_label:
        await info_gatherer._execute_divergence_decision(
            conv, 52, decision, "awaiting_university", repeat_count=1,
        )

    set_state.assert_awaited_once_with(conv.id)
    write_label.assert_awaited_once_with(52)


@pytest.mark.asyncio
async def test_should_write_human_needed_label_on_missing_routing_row():
    """complex / non_turkish have no routing rows → default escalate."""
    conv = _conv()
    decision = RoutingDecision(action=DivergenceAction.ESCALATE)

    with patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock) as set_state, \
         patch.object(info_gatherer, "_write_human_needed_label", new_callable=AsyncMock) as write_label:
        await info_gatherer._execute_divergence_decision(
            conv, 52, decision, "new", repeat_count=1,
        )

    set_state.assert_awaited_once()
    write_label.assert_awaited_once_with(52)


@pytest.mark.asyncio
async def test_should_write_human_needed_label_on_third_strike_persistence():
    conv = _conv(last_divergence_intent="price", divergence_repeat_count=2)
    decision = RoutingDecision(
        action=DivergenceAction.ANSWER_AND_REANCHOR,
        canned_response_id=uuid.uuid4(),
        canned_response_alt_id=uuid.uuid4(),
    )

    with patch("app.layers.divergence_classifier.classify", new_callable=AsyncMock, return_value=ClassificationResult(intent=Intent.PRICE)), \
         patch("app.layers.divergence_router.route", new_callable=AsyncMock, return_value=decision), \
         patch.object(info_gatherer.queries, "update_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_log_divergence_turn", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock) as set_state, \
         patch.object(info_gatherer, "_write_human_needed_label", new_callable=AsyncMock) as write_label:
        await info_gatherer._run_divergence_recovery(
            conv, 52, "fiyat",
            flow_state="awaiting_university", fallback="escalate_off_script",
        )

    set_state.assert_awaited_once_with(conv.id)
    write_label.assert_awaited_once_with(52)


@pytest.mark.asyncio
async def test_should_write_human_needed_label_on_non_turkish_classification():
    conv = _conv(flow_state="new")
    decision = RoutingDecision(action=DivergenceAction.ESCALATE)

    with patch("app.layers.divergence_classifier.classify", new_callable=AsyncMock, return_value=ClassificationResult(intent=Intent.NON_TURKISH)), \
         patch("app.layers.divergence_router.route", new_callable=AsyncMock, return_value=decision), \
         patch.object(info_gatherer.queries, "update_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_log_divergence_turn", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock) as set_state, \
         patch.object(info_gatherer, "_write_human_needed_label", new_callable=AsyncMock) as write_label:
        await info_gatherer._run_divergence_recovery(
            conv, 52, "Привет!",
            flow_state="new", fallback="ignore",
        )

    set_state.assert_awaited_once_with(conv.id)
    write_label.assert_awaited_once_with(52)
