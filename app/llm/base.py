"""
Shared LLM client contract for provider adapters.
"""
from __future__ import annotations

from typing import Optional, Protocol


class LLMClient(Protocol):
    """
    Minimal async contract: system + user content in, raw JSON text out.

    Returns None when the provider yields no usable text.
    """

    async def complete(self, system_prompt: str, user_content: str) -> Optional[str]:
        """Execute one JSON-mode completion."""
        ...
