"""
Gemini TagAssigner response types (spec 018).
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class GeminiTagResult:
    """Parsed Gemini output: full snapshot labels + bot-writable attributes."""
    labels: list[str]
    attributes: dict[str, str] = field(default_factory=dict)
