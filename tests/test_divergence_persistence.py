"""
Unit tests for same-intent persistence cap (spec §8.2).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, DivergenceAction, RoutingDecision, University
from app.layers.divergence_classifier import ClassificationResult, Intent
from app.layers import info_gatherer


def _uni(name: str) -> University:
    return University(id=uuid.uuid4(), name=name)


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
async def test_should_escalate_on_third_same_intent_repeat():
    conv = _conv(last_divergence_intent="price", divergence_repeat_count=2)
    decision = RoutingDecision(
        action=DivergenceAction.ANSWER_AND_REANCHOR,
        canned_response_id=uuid.uuid4(),
        canned_response_alt_id=uuid.uuid4(),
    )

    with patch.object(info_gatherer, "_try_extract_slots_and_advance", new_callable=AsyncMock, return_value=False), \
         patch("app.layers.divergence_classifier.classify", new_callable=AsyncMock, return_value=ClassificationResult(intent=Intent.PRICE)), \
         patch("app.layers.divergence_router.route", new_callable=AsyncMock, return_value=decision), \
         patch.object(info_gatherer.queries, "update_divergence_persistence", new_callable=AsyncMock) as persist, \
         patch.object(info_gatherer, "_log_divergence_turn", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_execute_divergence_decision", new_callable=AsyncMock) as execute:
        await info_gatherer._run_divergence_recovery(
            conv, 52, "fiyat",
            flow_state="awaiting_university", fallback="escalate_off_script",
        )

    persist.assert_awaited_once_with(conv.id, "price", 3)
    execute.assert_awaited_once()
    assert execute.await_args.args[2].action == DivergenceAction.ESCALATE


@pytest.mark.asyncio
async def test_should_reset_persistence_on_slot_progress():
    conv = _conv(last_divergence_intent="price", divergence_repeat_count=2)
    bogazici = _uni("Marmara Üniversitesi")

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[bogazici]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True), \
         patch.object(info_gatherer.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock) as reset:
        await info_gatherer._try_extract_slots_and_advance(conv, 52, "Marmara")

    reset.assert_awaited_once_with(conv.id)
