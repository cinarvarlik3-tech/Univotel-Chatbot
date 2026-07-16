"""
Shared helpers for TagAssigner custom-attribute display and enum mapping (spec 018).
"""
from __future__ import annotations
from typing import Optional

EMPTY_SENTINELS = frozenset({"", "boş", "bilinmiyor", "Bilinmiyor"})

# LLM emits this when the institution is clear but campus cannot be resolved.
# Router maps it to info-check for agent clarification — never written to Chatwoot.
UNIVERSITY_CAMPUS_AMBIGUOUS = "bilinmiyor-kampus"

GENDER_DISPLAY_TO_ENUM: dict[str, Optional[str]] = {
    "Erkek": "male",
    "Kız": "female",
    "Bilinmiyor": None,
}

GENDER_ENUM_TO_DISPLAY: dict[Optional[str], str] = {
    "male": "Erkek",
    "female": "Kız",
    None: "Bilinmiyor",
}


def gender_enum_to_display(gender: Optional[str]) -> str:
    """Map conversations.gender enum to Chatwoot ogrenci_cinsiyet list value."""
    if gender == "male":
        return "Erkek"
    if gender == "female":
        return "Kız"
    return "Bilinmiyor"


def gender_display_to_enum(display: str) -> Optional[str]:
    """Map Chatwoot ogrenci_cinsiyet to conversations.gender enum."""
    normalized = normalize_attribute_value(display)
    if normalized is None:
        return None
    if normalized not in GENDER_DISPLAY_TO_ENUM:
        raise ValueError(f"Unknown ogrenci_cinsiyet value: {display!r}")
    return GENDER_DISPLAY_TO_ENUM[normalized]


def normalize_attribute_value(value: Optional[str]) -> Optional[str]:
    """Treat boş/bilinmiyor sentinels as unset."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped in EMPTY_SENTINELS:
        return None
    return stripped


def values_differ(current: Optional[str], proposed: Optional[str]) -> bool:
    """Compare normalized attribute display values."""
    return normalize_attribute_value(current) != normalize_attribute_value(proposed)
