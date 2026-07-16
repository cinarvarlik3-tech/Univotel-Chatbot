"""
Google Gemini adapter for JSON-mode completions.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GeminiLLMClient:
    """Gemini generate_content wrapper with JSON response mode."""

    def __init__(
        self,
        *,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
    ) -> None:
        self._model_id = model_id
        self._api_key = api_key
        self._temperature = temperature

    async def complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        """Run one Gemini completion via asyncio.to_thread."""
        if not self._api_key:
            logger.error("GeminiLLMClient: API key not configured")
            return None

        return await asyncio.to_thread(
            self._sync_complete,
            system_prompt,
            user_content,
        )

    def _sync_complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        import google.genai as genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self._model_id,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=self._temperature,
            ),
        )
        return response.text if response.text else None
