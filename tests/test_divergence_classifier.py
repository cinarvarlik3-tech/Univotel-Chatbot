"""
Unit tests for divergence intent classifier (app/layers/divergence_classifier.py).
Mocks LLM — no live API.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.layers.divergence_classifier import ClassificationResult, Intent, _parse_intent, classify


def test_should_parse_valid_intent_json():
    assert _parse_intent('{"intent": "price"}') == Intent.PRICE


def test_should_return_none_for_unknown_label():
    assert _parse_intent('{"intent": "pricing"}') is None


def test_should_return_none_for_malformed_json():
    assert _parse_intent("not json") is None


@pytest.mark.asyncio
async def test_should_return_intent_when_llm_succeeds():
    with patch(
        "app.layers.divergence_classifier._call_llm_once",
        new_callable=AsyncMock,
        return_value=Intent.LOCATION,
    ):
        result = await classify("yeriniz nerede")
    assert result == ClassificationResult(intent=Intent.LOCATION, llm_failed=False)


@pytest.mark.asyncio
async def test_should_retry_once_then_mark_llm_failed():
    with patch(
        "app.layers.divergence_classifier._call_llm_once",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_call:
        result = await classify("fiyat ne kadar")
    assert mock_call.await_count == 2
    assert result.intent == Intent.COMPLEX
    assert result.llm_failed is True
