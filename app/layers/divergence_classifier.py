"""
Divergence intent classifier — state-blind LLM fallback for InfoGatherer (spec 019).

Reads a single inbound message and returns one intent from a fixed enum. Policy,
routing, and customer-facing text live elsewhere.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from app.llm.factory import get_llm_client

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "system_prompts" / "divergence_classifier_prompt.md"
_PROMPT_MARKER = "## SYSTEM PROMPT (everything below the line is the prompt content)"


class Intent(str, Enum):
    HOUSING = "housing"
    PRICE = "price"
    LOCATION = "location"
    VACANCY = "vacancy"
    PARENT_SHOPPING = "parent_shopping"
    LOGISTICS_COVERAGE = "logistics_coverage"
    LOGISTICS_PAYMENT = "logistics_payment"
    LOGISTICS_ELIGIBILITY = "logistics_eligibility"
    NO_INTENT = "no_intent"
    COMPLEX = "complex"
    NON_TURKISH = "non_turkish"


_INTENT_VALUES = frozenset(i.value for i in Intent)


@dataclass(frozen=True)
class ClassificationResult:
    """Classifier output; llm_failed=True means fall back to pre-divergence behavior."""
    intent: Intent
    llm_failed: bool = False


def _load_system_prompt() -> str:
    """Extract the system prompt body from the markdown file."""
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    idx = text.find(_PROMPT_MARKER)
    if idx == -1:
        raise RuntimeError(f"Prompt marker not found in {_PROMPT_PATH}")
    body = text[idx + len(_PROMPT_MARKER):]
    end = body.find("---\n\n## Integration notes")
    if end != -1:
        body = body[:end]
    return body.strip()


def _build_user_content(message: str) -> str:
    """Replace the {{MESSAGE}} placeholder with raw inbound text."""
    return _load_system_prompt().replace("{{MESSAGE}}", message)


def _parse_intent(raw: str) -> Optional[Intent]:
    """Parse JSON response and validate intent membership."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    label = data.get("intent")
    if not isinstance(label, str) or label not in _INTENT_VALUES:
        return None
    return Intent(label)


async def _call_llm_once(message: str) -> Optional[Intent]:
    """Single LLM attempt; returns None on transport/parse failure."""
    user_content = _build_user_content(message)
    system_prompt = (
        "You are an intent classifier. Return only the JSON object specified in the prompt."
    )
    try:
        client = get_llm_client("divergence")
        raw = await client.complete(system_prompt, user_content)
    except Exception as exc:
        logger.warning("divergence_classifier: LLM error: %s", exc)
        return None
    if not raw:
        return None
    return _parse_intent(raw)


async def classify(message: str) -> ClassificationResult:
    """
    Classify one inbound message into an Intent enum value.

    One retry on failure; second failure sets llm_failed=True with intent=COMPLEX
    so the orchestrator can apply state-specific fallback behavior.
    """
    for attempt in (1, 2):
        intent = await _call_llm_once(message)
        if intent is not None:
            return ClassificationResult(intent=intent, llm_failed=False)
        logger.warning("divergence_classifier: attempt %d failed for message %r", attempt, message[:80])

    return ClassificationResult(intent=Intent.COMPLEX, llm_failed=True)
