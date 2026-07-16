"""
Resolve per-task LLM provider/model from settings and construct adapters.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from app.config import settings
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMClient
from app.llm.gemini_client import GeminiLLMClient
from app.llm.openai_client import OpenAILLMClient

logger = logging.getLogger(__name__)

LLMTask = Literal["tagassigner", "divergence"]
LLMProvider = Literal["gemini", "openai", "anthropic"]

_VALID_PROVIDERS = frozenset({"gemini", "openai", "anthropic"})
_VALID_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh"})

_client_cache: dict[LLMTask, LLMClient] = {}


@dataclass(frozen=True)
class LLMTaskConfig:
    """Resolved provider credentials and tuning for one LLM task."""

    task: LLMTask
    provider: LLMProvider
    model_id: str
    api_key: Optional[str]
    temperature: float
    reasoning_effort: Optional[str]
    max_output_tokens: Optional[int]


def _normalize_optional(value: Optional[str]) -> Optional[str]:
    """Treat blank env strings as unset."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_task_config(task: LLMTask) -> LLMTaskConfig:
    """
    Resolve provider, API key, and model for a task.

    Model precedence: <TASK>_MODEL_ID override, else <PROVIDER>_MODEL_ID.
    """
    if task == "tagassigner":
        provider_raw = settings.tagassigner_provider
        task_model_override = _normalize_optional(settings.tagassigner_model_id)
    else:
        provider_raw = settings.divergence_provider
        task_model_override = _normalize_optional(settings.divergence_model_id)

    provider = provider_raw.strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise ValueError(f"Unknown LLM provider {provider!r} for task {task!r}")

    provider_models = {
        "gemini": settings.gemini_model_id,
        "openai": settings.openai_model_id,
        "anthropic": settings.anthropic_model_id,
    }
    api_keys = {
        "gemini": settings.gemini_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }

    model_id = task_model_override or provider_models[provider]
    reasoning_effort = _normalize_optional(settings.llm_reasoning_effort)
    if reasoning_effort == "none":
        reasoning_effort = None

    return LLMTaskConfig(
        task=task,
        provider=provider,  # type: ignore[arg-type]
        model_id=model_id,
        api_key=api_keys[provider],
        temperature=settings.llm_temperature,
        reasoning_effort=reasoning_effort,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def _build_client(config: LLMTaskConfig) -> LLMClient:
    """Instantiate the adapter for a resolved task config."""
    if config.provider == "gemini":
        return GeminiLLMClient(
            model_id=config.model_id,
            api_key=config.api_key or "",
            temperature=config.temperature,
        )
    if config.provider == "openai":
        return OpenAILLMClient(
            model_id=config.model_id,
            api_key=config.api_key or "",
            temperature=config.temperature,
            reasoning_effort=config.reasoning_effort,
            max_output_tokens=config.max_output_tokens,
        )
    return AnthropicLLMClient(
        model_id=config.model_id,
        api_key=config.api_key or "",
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
    )


def get_llm_client(task: LLMTask) -> LLMClient:
    """Return a cached LLM adapter for the given task."""
    if task not in _client_cache:
        config = resolve_task_config(task)
        _client_cache[task] = _build_client(config)
        logger.info(
            "llm factory: task=%s provider=%s model=%s",
            task,
            config.provider,
            config.model_id,
        )
    return _client_cache[task]


def reset_client_cache() -> None:
    """Clear cached clients (for tests and config reload)."""
    _client_cache.clear()


def validate_llm_config() -> None:
    """
    Boot-time LLM rules. Raises RuntimeError on misconfiguration.

    Each configured task must have a valid provider and that provider's API key.
    """
    log = logging.getLogger(__name__)

    reasoning = _normalize_optional(settings.llm_reasoning_effort)
    if reasoning and reasoning not in _VALID_REASONING_EFFORTS:
        log.fatal("LLM_REASONING_EFFORT must be one of %s", sorted(_VALID_REASONING_EFFORTS))
        raise RuntimeError(
            f"LLM_REASONING_EFFORT must be one of {sorted(_VALID_REASONING_EFFORTS)}"
        )

    for task in ("tagassigner", "divergence"):
        try:
            config = resolve_task_config(task)  # type: ignore[arg-type]
        except ValueError as exc:
            log.fatal("LLM config invalid for task %s: %s", task, exc)
            raise RuntimeError(str(exc)) from exc

        if not config.api_key:
            log.fatal(
                "LLM API key missing for task=%s provider=%s",
                task,
                config.provider,
            )
            raise RuntimeError(
                f"API key for provider '{config.provider}' is required "
                f"(task={task})"
            )
