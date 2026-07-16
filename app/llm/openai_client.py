"""
OpenAI adapter for JSON-mode completions (Chat Completions API).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OpenAILLMClient:
    """OpenAI chat.completions wrapper with JSON response format."""

    def __init__(
        self,
        *,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
        reasoning_effort: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> None:
        self._model_id = model_id
        self._api_key = api_key
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        """Run one OpenAI completion."""
        if not self._api_key:
            logger.error("OpenAILLMClient: API key not configured")
            return None

        create_kwargs: dict = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }

        if self._reasoning_effort:
            create_kwargs["reasoning_effort"] = self._reasoning_effort
        else:
            create_kwargs["temperature"] = self._temperature

        if self._max_output_tokens is not None:
            create_kwargs["max_completion_tokens"] = self._max_output_tokens

        client = self._get_client()
        response = await client.chat.completions.create(**create_kwargs)
        message = response.choices[0].message
        return message.content if message.content else None
