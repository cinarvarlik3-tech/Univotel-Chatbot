"""
Assembles the structured JSON payload sent to Gemini (§4.3 of tagassigner-v1-spec.md).

Kept modular: the V2 CRM/sales-action context block slots in here without a rewrite.
Attribute list is config-driven (TAGASSIGNER_ATTRIBUTE_KEYS) — not hardcoded —
so a Chatwoot attribute cleanup requires no code changes.

Gemini receives:
- Conversation messages (full history or since-last-run depending on trigger type)
- All custom attributes as read-only context
- Current label set
- university_id and gender (InfoGatherer's authoritative values, read-only for Gemini)

Gemini returns ONLY the proposed label set. It never decides attribute values.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from app.db.models import Conversation, Message
from app.config import TAGASSIGNER_ATTRIBUTE_KEYS

_PROMPT_PATH = Path(__file__).parent.parent.parent / "system_prompts" / "tagassigner_prompt.md"

def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()

_SYSTEM_PROMPT: str = _load_system_prompt()


def build_payload(
    conversation: Conversation,
    messages: list[Message],
    current_labels: list[str],
) -> dict[str, Any]:
    """
    Build the structured payload for a Gemini live call.

    Returns a dict with:
    - system_prompt: str
    - user_content: str  (the conversation transcript + context)
    """
    transcript = _build_transcript(messages)
    context = _build_context(conversation, current_labels)

    user_content = f"{context}\n\n## Konuşma\n{transcript}"

    return {
        "system_prompt": _SYSTEM_PROMPT,
        "user_content": user_content,
    }


def build_batch_request(
    conversation: Conversation,
    messages: list[Message],
    current_labels: list[str],
    custom_id: str,
) -> dict[str, Any]:
    """
    Build a single Gemini Batch API request object.
    custom_id is used to correlate results back to conversations.
    """
    payload = build_payload(conversation, messages, current_labels)
    return {
        "custom_id": custom_id,
        "system_prompt": payload["system_prompt"],
        "user_content": payload["user_content"],
    }


def _build_transcript(messages: list[Message]) -> str:
    lines = []
    for msg in messages:
        role = "Müşteri" if msg.message_type == "inbound" else "Bot"
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(Konuşma mesajı bulunamadı)"


def _build_context(conversation: Conversation, current_labels: list[str]) -> str:
    """
    Assembles the read-only context block for Gemini.
    Attribute list is driven by TAGASSIGNER_ATTRIBUTE_KEYS (config-driven, not hardcoded).
    """
    lines = ["## Mevcut Durum (salt-okunur — bu değerleri değiştirme)"]

    # InfoGatherer columns (authoritative)
    lines.append(f"university_id: {conversation.university_id or 'bilinmiyor'}")
    lines.append(f"gender: {conversation.gender or 'bilinmiyor'}")

    # Config-driven attribute columns
    for key in TAGASSIGNER_ATTRIBUTE_KEYS:
        value = getattr(conversation, key, None)
        lines.append(f"{key}: {value if value is not None else 'boş'}")

    lines.append(f"mevcut_etiketler: {', '.join(current_labels) if current_labels else 'yok'}")

    return "\n".join(lines)


def parse_gemini_response(raw: str) -> list[str] | None:
    """
    Parse Gemini's JSON response into a label list.
    Returns None if the response is malformed.
    """
    import json
    import re

    # Strip markdown code fences if present
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    labels = data.get("labels")
    if not isinstance(labels, list):
        return None

    return [str(label) for label in labels if isinstance(label, str)]
