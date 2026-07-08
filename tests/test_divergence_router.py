"""
Unit tests for divergence routing table (app/layers/divergence_router.py).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import DivergenceAction, DivergenceRoutingRow, RoutingDecision
from app.layers.divergence_classifier import Intent
from app.layers import divergence_router


def _row(intent: str, state: str, action: str, primary=None, alt=None) -> DivergenceRoutingRow:
    return DivergenceRoutingRow(
        intent=intent,
        flow_state=state,
        action=action,
        canned_response_id=primary,
        canned_response_alt_id=alt,
    )


@pytest.mark.asyncio
async def test_should_return_seeded_action_for_intent_and_state():
    pid, aid = uuid.uuid4(), uuid.uuid4()
    table = {
        ("price", "awaiting_university"): RoutingDecision(
            action=DivergenceAction.ANSWER_AND_REANCHOR,
            canned_response_id=pid,
            canned_response_alt_id=aid,
        ),
    }
    with patch.object(divergence_router, "ensure_routing_cache", new_callable=AsyncMock, return_value=table):
        decision = await divergence_router.route(Intent.PRICE, "awaiting_university")
    assert decision.action == DivergenceAction.ANSWER_AND_REANCHOR
    assert decision.canned_response_id == pid


@pytest.mark.asyncio
async def test_should_escalate_when_row_missing():
    with patch.object(divergence_router, "ensure_routing_cache", new_callable=AsyncMock, return_value={}):
        decision = await divergence_router.route(Intent.COMPLEX, "new")
    assert decision.action == DivergenceAction.ESCALATE


@pytest.mark.asyncio
async def test_should_ignore_no_intent_in_clarification_state():
    table = {
        ("no_intent", "awaiting_campus_clarification"): RoutingDecision(
            action=DivergenceAction.IGNORE,
        ),
    }
    with patch.object(divergence_router, "ensure_routing_cache", new_callable=AsyncMock, return_value=table):
        decision = await divergence_router.route(Intent.NO_INTENT, "awaiting_campus_clarification")
    assert decision.action == DivergenceAction.IGNORE
