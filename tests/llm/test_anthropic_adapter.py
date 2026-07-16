"""Unit tests for Anthropic LLM adapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.llm.anthropic_client import AnthropicLLMClient


@pytest.mark.asyncio
async def test_should_return_text_from_anthropic_response():
    client = AnthropicLLMClient(
        model_id="claude-haiku-4-5",
        api_key="test-key",
    )

    with patch.object(
        client,
        "_sync_complete",
        return_value='{"intent": "housing"}',
    ):
        result = await client.complete("system", "user")

    assert result == '{"intent": "housing"}'


@pytest.mark.asyncio
async def test_should_return_none_when_api_key_missing():
    client = AnthropicLLMClient(model_id="claude-haiku-4-5", api_key="")
    result = await client.complete("system", "user")
    assert result is None
