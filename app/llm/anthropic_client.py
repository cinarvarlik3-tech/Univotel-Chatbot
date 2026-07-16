"""
Anthropic adapter for JSON completions (Messages API).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MAX_OUTPUT_TOKENS = 1024


class AnthropicLLMClient:
    """Anthropic messages.create wrapper; JSON enforced via prompt contract."""

    def __init__(
        self,
        *,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> None:
        self._model_id = model_id
        self._api_key = api_key
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens or _DEFAULT_MAX_OUTPUT_TOKENS

    async def complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        """Run one Anthropic completion via asyncio.to_thread."""
        if not self._api_key:
            logger.error("AnthropicLLMClient: API key not configured")
            return None

        return await asyncio.to_thread(
            self._sync_complete,
            system_prompt,
            user_content,
        )

    def _sync_complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model_id,
            max_tokens=self._max_output_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            temperature=self._temperature,
        )

        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        text = "".join(parts).strip()
        return text if text else None
