"""Unit tests for Gemini LLM adapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.llm.gemini_client import GeminiLLMClient


@pytest.mark.asyncio
async def test_should_return_text_from_gemini_response():
    client = GeminiLLMClient(
        model_id="gemini-2.5-flash-lite",
        api_key="test-key",
    )

    with patch.object(
        client,
        "_sync_complete",
        return_value='{"intent": "price"}',
    ):
        result = await client.complete("system", "user")

    assert result == '{"intent": "price"}'


@pytest.mark.asyncio
async def test_should_return_none_when_api_key_missing():
    client = GeminiLLMClient(model_id="gemini-2.5-flash-lite", api_key="")
    result = await client.complete("system", "user")
    assert result is None
