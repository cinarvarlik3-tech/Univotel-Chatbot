"""
Chatwoot university/campus automation recognition (Spec 031).

The live account fires exactly one outbound automation on new inbound. We match by
normalized content only (no sender id). If Chatwoot automation copy changes without
updating _AUTOMATION_CORE here, the message is treated as human takeover again.
"""
from __future__ import annotations

from app.layers.matching import normalize

# Distinctive fragment before the univotel.com apostrophe variants in the full template.
_AUTOMATION_CORE = normalize("hangi üniversite ve hangi kampüsteydeniz")


def is_automation_message(content: str | None) -> bool:
    """True when an outbound message is the Chatwoot university/campus automation."""
    if not content or not content.strip():
        return False
    normalized = normalize(content)
    if not normalized:
        return False
    return _AUTOMATION_CORE in normalized
