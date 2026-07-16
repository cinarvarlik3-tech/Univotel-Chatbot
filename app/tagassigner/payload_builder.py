"""
Assembles the structured JSON payload sent to Gemini (§4.3 of tagassigner-v1-spec.md).

Kept modular: the V2 CRM/sales-action context block slots in here without a rewrite.
Attribute list is config-driven (TAGASSIGNER_ATTRIBUTE_KEYS) — not hardcoded —
so a Chatwoot attribute cleanup requires no code changes.

Gemini receives conversation messages, custom attributes as context, current labels,
and returns a full snapshot of labels plus bot-writable attributes (spec 018).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.db.models import Conversation, Message
from app.config import TAGASSIGNER_ATTRIBUTE_KEYS, TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES
from app.tagassigner.llm_types import TagResult
from app.tagassigner.attribute_helpers import gender_enum_to_display

_PROMPT_PATH = Path(__file__).parent.parent.parent / "system_prompts" / "tagassigner_prompt.md"

def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()

_SYSTEM_PROMPT: str = _load_system_prompt()


def build_payload(
    conversation: Conversation,
    messages: list[Message],
    current_labels: list[str],
    university_display: Optional[str] = None,
    university_list_lines: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build the structured payload for a Gemini live call.

    Returns a dict with:
    - system_prompt: str
    - user_content: str  (the conversation transcript + context)

    university_display: resolved Chatwoot list string for university_id (from Router).
    university_list_lines: formatted list + abbreviation lines for Gemini selection.
    """
    transcript = _build_transcript(messages)
    context = _build_context(
        conversation,
        current_labels,
        university_display,
        university_list_lines=university_list_lines or [],
    )

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
    university_display: Optional[str] = None,
    university_list_lines: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build a single Gemini Batch API request object.
    custom_id is used to correlate results back to conversations.
    """
    payload = build_payload(
        conversation,
        messages,
        current_labels,
        university_display,
        university_list_lines=university_list_lines,
    )
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


def _build_context(
    conversation: Conversation,
    current_labels: list[str],
    university_display: Optional[str] = None,
    university_list_lines: Optional[list[str]] = None,
) -> str:
    """
    Assembles the context block for Gemini.
    Human-only attributes are read-only; bot-writable fields appear for snapshot output.
    """
    lines = ["## Mevcut Durum"]

    uni_str = university_display or "bilinmiyor"
    gender_str = gender_enum_to_display(conversation.gender) if conversation.gender else "bilinmiyor"

    lines.append("### Bot-writable (echo in attributes output — full snapshot)")
    lines.append(f"university: {uni_str}")
    lines.append(f"ogrenci_cinsiyet: {gender_str}")
    lines.append(f"oda_tiipi: {conversation.oda_tiipi if conversation.oda_tiipi else 'boş'}")

    if university_list_lines:
        lines.append("### Geçerli üniversite listesi (yalnızca bu değerlerden birini kullan)")
        lines.extend(university_list_lines)

    lines.append("### Human-only (context for labelling — never in attributes output)")
    for key in TAGASSIGNER_ATTRIBUTE_KEYS:
        value = getattr(conversation, key, None)
        lines.append(f"{key}: {value if value is not None else 'boş'}")

    lines.append(f"mevcut_etiketler: {', '.join(current_labels) if current_labels else 'yok'}")

    return "\n".join(lines)


def parse_tag_result(raw: str) -> TagResult | None:
    """
    Parse LLM JSON response into labels + bot-writable attributes (spec 018).
    Returns None if malformed. Attributes key is required.

    `university_mention` (spec 027) is read if present but never required —
    older/other-provider responses without it still parse successfully; the
    Router falls back to attributes["university"] when it's absent.
    """
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

    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        return None

    label_list = [str(label) for label in labels if isinstance(label, str)]

    attr_out: dict[str, str] = {}
    for key in TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES:
        if key not in attributes:
            return None
        val = attributes[key]
        if not isinstance(val, str):
            return None
        attr_out[key] = val

    university_mention_raw = data.get("university_mention")
    university_mention = (
        university_mention_raw if isinstance(university_mention_raw, str) else None
    )

    return TagResult(
        labels=label_list,
        attributes=attr_out,
        university_mention=university_mention,
    )


def parse_tag_labels(raw: str) -> list[str] | None:
    """Labels-only parse. Prefer parse_tag_result for full snapshot."""
    result = parse_tag_result(raw)
    return result.labels if result else None
