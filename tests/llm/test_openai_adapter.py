"""Unit tests for OpenAI LLM adapter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.openai_client import OpenAILLMClient


@pytest.mark.asyncio
async def test_should_return_text_from_openai_response():
    client = OpenAILLMClient(
        model_id="gpt-5.4-nano",
        api_key="test-key",
        temperature=0.0,
    )
    mock_message = MagicMock(content='{"labels": []}')
    mock_choice = MagicMock(message=mock_message)
    mock_response = MagicMock(choices=[mock_choice])
    mock_api = MagicMock()
    mock_api.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch.object(client, "_get_client", return_value=mock_api):
        result = await client.complete("system", "user")

    assert result == '{"labels": []}'
    call_kwargs = mock_api.chat.completions.create.await_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["temperature"] == 0.0


@pytest.mark.asyncio
async def test_should_pass_reasoning_effort_when_configured():
    client = OpenAILLMClient(
        model_id="gpt-5.4-nano",
        api_key="test-key",
        reasoning_effort="low",
    )
    mock_message = MagicMock(content='{"intent": "price"}')
    mock_choice = MagicMock(message=mock_message)
    mock_response = MagicMock(choices=[mock_choice])
    mock_api = MagicMock()
    mock_api.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch.object(client, "_get_client", return_value=mock_api):
        await client.complete("system", "user")

    call_kwargs = mock_api.chat.completions.create.await_args.kwargs
    assert call_kwargs["reasoning_effort"] == "low"
    assert "temperature" not in call_kwargs
