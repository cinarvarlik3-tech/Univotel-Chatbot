"""
TagAssigner LLM response types (spec 018, university_mention added spec 027).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TagResult:
    """Parsed LLM output: full snapshot labels + bot-writable attributes."""
    labels: list[str]
    attributes: dict[str, str] = field(default_factory=dict)
    # Optional raw university phrase the lead used, for deterministic Router
    # canonicalization (app.tagassigner.university_canonicalizer). Additive —
    # never required; absence just means the Router falls back to the LLM's
    # `attributes["university"]` list-value guess.
    university_mention: Optional[str] = None
