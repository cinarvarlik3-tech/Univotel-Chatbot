"""
TagAssigner university list enrichment for Gemini context.

Builds annotated list lines ([tek kampüs], [tıp fakültesi]) and a short-name
abbreviation appendix from DB rows. Keeps payload_builder rendering thin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.layers.matching import normalize

_TIP_FAKULTESI = "tip fakultesi"


@dataclass(frozen=True)
class UniversityListEntry:
    """One canonical Chatwoot list value with TagAssigner matching hints."""

    list_value: str
    is_single_campus: bool = False
    is_faculty_entry: bool = False
    short_names: tuple[str, ...] = field(default_factory=tuple)


def _is_faculty_name(name: str, list_value: str) -> bool:
    """True when university or list string denotes a medical faculty entry."""
    combined = normalize(f"{name} {list_value}")
    return _TIP_FAKULTESI in combined or "tip fak" in combined


def build_university_list_entries(
    rows: list[dict],
) -> list[UniversityListEntry]:
    """
    Merge DB rows (one per university_id) into deduplicated list entries.

    rows: dicts with chatwoot_list_value, university_name, university_short_name,
          parent_campus_count.
    """
    by_value: dict[str, dict] = {}

    for row in rows:
        list_value = row["chatwoot_list_value"]
        short_raw = (row.get("university_short_name") or "").strip()
        short_names: set[str] = set(by_value.get(list_value, {}).get("short_names", set()))
        if short_raw and normalize(short_raw) != normalize(list_value):
            short_names.add(short_raw)

        campus_count = int(row["parent_campus_count"])
        is_single = campus_count == 1
        is_faculty = _is_faculty_name(row["university_name"], list_value)

        if list_value not in by_value:
            by_value[list_value] = {
                "is_single_campus": is_single,
                "is_faculty_entry": is_faculty,
                "short_names": short_names,
            }
        else:
            existing = by_value[list_value]
            existing["is_single_campus"] = existing["is_single_campus"] or is_single
            existing["is_faculty_entry"] = existing["is_faculty_entry"] or is_faculty
            existing["short_names"].update(short_names)

    entries = [
        UniversityListEntry(
            list_value=lv,
            is_single_campus=data["is_single_campus"],
            is_faculty_entry=data["is_faculty_entry"],
            short_names=tuple(sorted(data["short_names"])),
        )
        for lv, data in sorted(by_value.items())
    ]
    return entries


def format_university_list_section(entries: list[UniversityListEntry]) -> list[str]:
    """
    Render list lines and optional abbreviation appendix for Gemini context.

    Returns flat lines: list entries first, then abbrev subsection if any.
    """
    lines: list[str] = []
    abbrev_lines: list[str] = []

    for entry in entries:
        suffix_parts: list[str] = []
        if entry.is_single_campus:
            suffix_parts.append("[tek kampüs]")
        if entry.is_faculty_entry:
            suffix_parts.append("[tıp fakültesi]")
        tag = f"  {' '.join(suffix_parts)}" if suffix_parts else ""
        lines.append(f"{entry.list_value}{tag}")

        for short in entry.short_names:
            if _should_include_abbrev(short, entry):
                abbrev_lines.append(f"{short} → {entry.list_value}")

    if abbrev_lines:
        lines.append("### Üniversite kısaltmaları (lead ifadesi → list değeri)")
        lines.extend(sorted(set(abbrev_lines)))

    return lines


def _should_include_abbrev(short_name: str, entry: UniversityListEntry) -> bool:
    """
    Include abbreviation hints when campus-specific or faculty-specific.

    Excludes bare parent abbreviations for multi-campus parents (e.g. DOU alone).
    """
    if entry.is_faculty_entry or entry.is_single_campus:
        return True
    norm_short = normalize(short_name)
    norm_list = normalize(entry.list_value)
    # Campus token present in short name but not as the whole string matching parent only
    if norm_short != norm_list and len(norm_short.split()) >= 2:
        return True
    return False


async def load_formatted_university_list_lines() -> list[str]:
    """Fetch DB rows and render annotated list + abbreviation lines for Gemini."""
    from app.db import queries

    rows = await queries.get_university_list_rows_for_tagassigner()
    entries = build_university_list_entries(rows)
    return format_university_list_section(entries)
