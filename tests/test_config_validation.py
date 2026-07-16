"""Unit tests for boot-time config validation (Spec 022 Part A)."""
import pytest
from unittest.mock import patch

from app.config import validate_config
from app.llm.factory import validate_llm_config


def _llm_settings(**overrides):
    base = {
        "tagassigner_provider": "gemini",
        "divergence_provider": "gemini",
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
    from unittest.mock import MagicMock
    return MagicMock(**base)


def test_should_refuse_start_when_both_testing_modes_enabled():
    with pytest.raises(RuntimeError, match="cannot both be enabled"):
        validate_config(
            live_testing_mode=True,
            testing_limitations_mode=True,
            live_testing_limit=10,
        )


def test_should_refuse_start_when_live_testing_mode_on_without_limit():
    with pytest.raises(RuntimeError, match="LIVE_TESTING_LIMIT is not set"):
        validate_config(
            live_testing_mode=True,
            testing_limitations_mode=False,
            live_testing_limit=None,
        )


def test_should_allow_start_when_limit_set_but_live_testing_mode_off():
    validate_config(
        live_testing_mode=False,
        testing_limitations_mode=False,
        live_testing_limit=10,
    )


def test_should_allow_start_when_live_testing_mode_on_with_limit():
    validate_config(
        live_testing_mode=True,
        testing_limitations_mode=False,
        live_testing_limit=10,
    )


def test_should_allow_outbound_block_in_any_combination():
    validate_config(
        live_testing_mode=False,
        testing_limitations_mode=False,
        live_testing_limit=None,
    )


def test_should_validate_llm_config_when_keys_present():
    with patch("app.llm.factory.settings", _llm_settings()):
        validate_llm_config()


def test_should_reject_llm_config_when_tagassigner_key_missing():
    with patch(
        "app.llm.factory.settings",
        _llm_settings(gemini_api_key=None),
    ):
        with pytest.raises(RuntimeError, match="API key"):
            validate_llm_config()


def test_should_treat_blank_llm_max_output_tokens_as_none():
    from pydantic import ValidationError
    from app.config import Settings

    settings = Settings(
        database_url="postgresql://user:pass@host:5432/db",
        chatwoot_base_url="https://example.com",
        chatwoot_api_token="token",
        chatwoot_account_id=1,
        chatwoot_webhook_secret="secret",
        chatwoot_bot_agent_id=1,
        internal_shared_secret="secret",
        llm_max_output_tokens="",
    )
    assert settings.llm_max_output_tokens is None
