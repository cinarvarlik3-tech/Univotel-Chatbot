"""Unit tests for LLM task config resolution and client factory."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.llm.factory import (
    get_llm_client,
    resolve_task_config,
    reset_client_cache,
    validate_llm_config,
)
from app.llm.gemini_client import GeminiLLMClient
from app.llm.openai_client import OpenAILLMClient
from app.llm.anthropic_client import AnthropicLLMClient


@pytest.fixture(autouse=True)
def _clear_client_cache():
    reset_client_cache()
    yield
    reset_client_cache()


def _mock_settings(**overrides):
    base = {
        "tagassigner_provider": "gemini",
        "divergence_provider": "openai",
        "tagassigner_model_id": None,
        "divergence_model_id": None,
        "gemini_model_id": "gemini-2.5-flash-lite",
        "openai_model_id": "gpt-5.4-nano",
        "anthropic_model_id": "claude-haiku-4-5",
        "gemini_api_key": "gem-key",
        "openai_api_key": "oai-key",
        "anthropic_api_key": "ant-key",
        "llm_temperature": 0.0,
        "llm_reasoning_effort": None,
        "llm_max_output_tokens": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def test_should_resolve_tagassigner_provider_model_and_key():
    with patch("app.llm.factory.settings", _mock_settings()):
        config = resolve_task_config("tagassigner")
    assert config.provider == "gemini"
    assert config.model_id == "gemini-2.5-flash-lite"
    assert config.api_key == "gem-key"


def test_should_use_task_model_override_when_set():
    with patch(
        "app.llm.factory.settings",
        _mock_settings(tagassigner_model_id="custom-model"),
    ):
        config = resolve_task_config("tagassigner")
    assert config.model_id == "custom-model"


def test_should_resolve_divergence_openai_provider():
    with patch("app.llm.factory.settings", _mock_settings()):
        config = resolve_task_config("divergence")
    assert config.provider == "openai"
    assert config.model_id == "gpt-5.4-nano"
    assert config.api_key == "oai-key"


def test_should_raise_for_unknown_provider():
    with patch(
        "app.llm.factory.settings",
        _mock_settings(tagassigner_provider="cohere"),
    ):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            resolve_task_config("tagassigner")


def test_should_build_gemini_client_for_tagassigner():
    with patch("app.llm.factory.settings", _mock_settings()):
        client = get_llm_client("tagassigner")
    assert isinstance(client, GeminiLLMClient)


def test_should_build_openai_client_for_divergence():
    with patch("app.llm.factory.settings", _mock_settings()):
        client = get_llm_client("divergence")
    assert isinstance(client, OpenAILLMClient)


def test_should_build_anthropic_client_when_selected():
    with patch(
        "app.llm.factory.settings",
        _mock_settings(
            tagassigner_provider="anthropic",
            divergence_provider="anthropic",
        ),
    ):
        client = get_llm_client("tagassigner")
    assert isinstance(client, AnthropicLLMClient)


def test_should_reject_invalid_reasoning_effort():
    with patch(
        "app.llm.factory.settings",
        _mock_settings(llm_reasoning_effort="turbo"),
    ):
        with pytest.raises(RuntimeError, match="LLM_REASONING_EFFORT"):
            validate_llm_config()


def test_should_reject_missing_api_key_for_active_provider():
    with patch(
        "app.llm.factory.settings",
        _mock_settings(gemini_api_key=None),
    ):
        with pytest.raises(RuntimeError, match="API key"):
            validate_llm_config()
