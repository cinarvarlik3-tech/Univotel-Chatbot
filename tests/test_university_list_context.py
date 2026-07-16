"""Unit tests for app/tagassigner/university_list_context.py."""
from app.tagassigner.university_list_context import (
    UniversityListEntry,
    build_university_list_entries,
    format_university_list_section,
    _should_include_abbrev,
)


def _row(list_value, name, short_name, campus_count):
    return {
        "chatwoot_list_value": list_value,
        "university_name": name,
        "university_short_name": short_name,
        "parent_campus_count": campus_count,
    }


def test_should_mark_single_campus_when_parent_has_one_row():
    rows = [_row("Yeni Yüzyıl Üniversitesi", "Yeni Yüzyıl Üniversitesi - Dr. Azmi Ofluoğlu Yerleşkesi", "YYÜ", 1)]
    entries = build_university_list_entries(rows)
    assert len(entries) == 1
    assert entries[0].is_single_campus is True


def test_should_not_mark_multi_campus_parent_entries():
    rows = [_row("Doğuş Üniversitesi Dudullu", "Doğuş Üniversitesi - Dudullu Yerleşkesi", "DOU Dudullu", 3)]
    entries = build_university_list_entries(rows)
    assert entries[0].is_single_campus is False


def test_should_mark_faculty_entries():
    rows = [
        _row("Çapa Tıp Fakültesi", "İstanbul Üniversitesi İÜ - Çapa Tıp Fakültesi", "İÜ ÇAPA", 4),
        _row("Bahçeşehir Üniversitesi - Tıp Fakültesi", "Bahçeşehir Üniversitesi Tıp Fakültesi", "BAU Tıp", 4),
    ]
    entries = build_university_list_entries(rows)
    assert all(e.is_faculty_entry for e in entries)


def test_should_include_abbrev_when_short_name_differs():
    rows = [_row("Doğuş Üniversitesi Dudullu", "Doğuş Üniversitesi - Dudullu Yerleşkesi", "DOU Dudullu", 3)]
    entries = build_university_list_entries(rows)
    lines = format_university_list_section(entries)
    assert any("DOU Dudullu → Doğuş Üniversitesi Dudullu" in line for line in lines)


def test_should_exclude_bare_dou_abbrev_for_multi_campus():
    entry = UniversityListEntry(
        list_value="Doğuş Üniversitesi Kadıköy",
        is_single_campus=False,
        is_faculty_entry=False,
        short_names=("DOU",),
    )
    assert _should_include_abbrev("DOU", entry) is False


def test_should_dedupe_duplicate_list_values():
    uid_a = "8cabe046-0cff-4663-a787-62869d465ca1"
    uid_b = "eaeeceed-65e1-4f67-8a80-a3fe566af0f2"
    rows = [
        _row("İstanbul Üniversitesi Cerrahpaşa", f"Campus A {uid_a}", "IUC-A", 2),
        _row("İstanbul Üniversitesi Cerrahpaşa", f"Campus B {uid_b}", "IUC-B", 2),
    ]
    entries = build_university_list_entries(rows)
    assert len(entries) == 1
    assert entries[0].list_value == "İstanbul Üniversitesi Cerrahpaşa"


def test_should_render_tek_kampus_tag_in_formatted_lines():
    entries = [UniversityListEntry("Yeni Yüzyıl Üniversitesi", is_single_campus=True)]
    lines = format_university_list_section(entries)
    assert any("[tek kampüs]" in line for line in lines)


def test_should_render_abbrev_subsection_header():
    rows = [_row("Çapa Tıp Fakültesi", "İstanbul Üniversitesi İÜ - Çapa Tıp Fakültesi", "İÜ ÇAPA", 4)]
    entries = build_university_list_entries(rows)
    lines = format_university_list_section(entries)
    assert any("Üniversite kısaltmaları" in line for line in lines)
