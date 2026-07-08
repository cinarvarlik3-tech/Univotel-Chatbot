"""
Label resolution pipeline (§8.1, §9 of tagassigner-v1-spec.md).

Pure functions — no I/O, fully unit-testable.
The Router enforces this taxonomy regardless of what the system prompt says.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# The four lists (architecture, not just prompt content)
# ---------------------------------------------------------------------------

LIST_1_USABLE: frozenset[str] = frozenset([
    "pre-sinav", "hazırlık", "1-sinif", "2-sinif", "3-sinif", "4-sinif",
    "universitede", "yerlesti", "yeni-giris", "erasmus",
    "ogrenci", "veli", "ogrenci-degil",
    "kyk-sonuc-bekliyor", "ibb-yurdu-sonuc-bekliyor",
    "universite-yurdu-sonuc-bekliyor", "yatay_geçiş_bekliyor",
    "univotelli", "fiyat-soruyor", "ilgilenmiyor", "info-check",
    "ziyaret", "ziyaret-etti", "ziyaret-etmedi",
])

LIST_2_TERMINAL: frozenset[str] = frozenset([
    "kapora-alindi", "sozlesme-imzalandi", "kayıp", "ziyaret-ama-almayacak",
])

LIST_3_NEVER_TOUCH: frozenset[str] = frozenset([
    # Source/channel (CRM-owned)
    "google-ads", "google-maps", "meta-ads", "instagram",
    "whatsapp", "netgsm", "sahibinden", "manual",
    # Sales-action (not chat-observable — V2 unlock)
    "aranacak", "arandi", "arandi-acmadi", "bizi-aradi-konustuk",
])

# List 4: mutually-exclusive groups.
# Each group is a tuple of (label_set, is_forward_progression).
# Forward-progression groups keep the most-advanced label; one-only groups keep exactly one.

# Academic year — forward progression, higher index = more advanced
_ACADEMIC_YEAR_ORDER: list[str] = [
    "pre-sinav", "hazırlık", "1-sinif", "2-sinif", "3-sinif", "4-sinif", "universitede",
]

# Enrollment progression
_ENROLLMENT_ORDER: list[str] = ["yerlesti", "yeni-giris"]

# Visit progression — two parallel branches at level 1
_VISIT_LEVELS: dict[str, int] = {
    "ziyaret": 0,
    "ziyaret-etti": 1,
    "ziyaret-etmedi": 1,
    "ziyaret-ama-almayacak": 2,
}

# Contact identity — one only, no forward direction
_CONTACT_IDENTITY: frozenset[str] = frozenset(["ogrenci", "veli", "ogrenci-degil"])

# Deal terminal — one only, no forward direction
_DEAL_TERMINAL: frozenset[str] = frozenset(["sozlesme-imzalandi", "kayıp"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_labels(
    before: list[str],
    proposed: list[str],
) -> list[str]:
    """
    Full label resolution pipeline (§8.1):
    1. Drop List-3 (never-touch) from proposed.
    2. List-2 terminal hard-guard: re-add any terminal label present in 'before'
       but missing from proposed output (additions allowed, removals blocked).
    3. List-4 mutex enforcement.
    4. Merge: keep all labels from 'before' that are not being changed,
       then apply the resolved additions/removals.

    'before' is the live label set read from Chatwoot at run start.
    'proposed' is Gemini's raw output (the full label set it wants).
    Returns the final label set to write back.
    """
    proposed_set = set(proposed)

    # Step 1: strip List-3 from proposed
    proposed_set -= LIST_3_NEVER_TOUCH

    # Step 2: terminal hard-guard — re-add List-2 labels that were present before
    before_set = set(before)
    for terminal in LIST_2_TERMINAL:
        if terminal in before_set and terminal not in proposed_set:
            proposed_set.add(terminal)

    # Step 3: mutex enforcement
    proposed_set = _enforce_mutex(proposed_set, before_set)

    # Step 4: merge — start from 'before', apply diff
    # Labels in neither list nor proposed stay (untouched by TagAssigner).
    # Labels in List-3 that were in 'before' are preserved (never-touch).
    final = set(before_set)

    # Remove List-1 labels from 'before' that Gemini did NOT propose
    # (Gemini's absence of a List-1 label is an explicit removal)
    for label in LIST_1_USABLE:
        if label in final and label not in proposed_set:
            final.discard(label)

    # Add proposed List-1 and List-2 labels that aren't already present
    for label in proposed_set:
        if label in LIST_1_USABLE or label in LIST_2_TERMINAL:
            final.add(label)

    return sorted(final)


def _enforce_mutex(proposed: set[str], before: set[str]) -> set[str]:
    """Apply List-4 mutually-exclusive group rules to the proposed set."""
    result = set(proposed)

    # Academic year: keep most advanced
    result = _apply_ordered_mutex(result, before, _ACADEMIC_YEAR_ORDER)

    # Enrollment progression: keep most advanced
    result = _apply_ordered_mutex(result, before, _ENROLLMENT_ORDER)

    # Visit progression: keep highest-level label(s), then resolve ties
    result = _apply_visit_mutex(result, before)

    # Contact identity: keep exactly one (prefer existing if tie)
    result = _apply_one_only_mutex(result, before, _CONTACT_IDENTITY)

    # Deal terminal: keep exactly one (prefer existing if tie)
    result = _apply_one_only_mutex(result, before, _DEAL_TERMINAL)

    return result


def _apply_ordered_mutex(
    proposed: set[str],
    before: set[str],
    order: list[str],
) -> set[str]:
    """
    Within a forward-progression group, keep only the most-advanced label.
    If multiple are proposed, the one with the highest index in 'order' wins.
    """
    present = [label for label in order if label in proposed]
    if len(present) <= 1:
        return proposed

    keep = present[-1]  # highest index = most advanced
    result = set(proposed)
    for label in present:
        if label != keep:
            result.discard(label)
    return result


def _apply_visit_mutex(proposed: set[str], before: set[str]) -> set[str]:
    """
    Visit progression has a branching structure:
    ziyaret (0) → ziyaret-etti (1) | ziyaret-etmedi (1) → ziyaret-ama-almayacak (2)

    Keep only the label(s) at the highest level. If both level-1 labels are proposed,
    keep whichever was already in 'before'; otherwise keep the first alphabetically.
    """
    result = set(proposed)
    visit_in_proposed = {label for label in _VISIT_LEVELS if label in result}
    if len(visit_in_proposed) <= 1:
        return result

    max_level = max(_VISIT_LEVELS[label] for label in visit_in_proposed)
    at_max = {label for label in visit_in_proposed if _VISIT_LEVELS[label] == max_level}

    # Drop everything below max level
    for label in visit_in_proposed:
        if _VISIT_LEVELS[label] < max_level:
            result.discard(label)

    # If multiple at the same level (etti + etmedi both proposed at level 1)
    if len(at_max) > 1:
        keep = next((label for label in at_max if label in before), sorted(at_max)[0])
        for label in at_max:
            if label != keep:
                result.discard(label)

    return result


def _apply_one_only_mutex(
    proposed: set[str],
    before: set[str],
    group: frozenset[str],
) -> set[str]:
    """
    Within a 'one only' group, keep exactly one label.
    Prefer whichever member was already in 'before'; otherwise keep the first alphabetically.
    """
    present = [label for label in group if label in proposed]
    if len(present) <= 1:
        return proposed

    keep = next((label for label in present if label in before), sorted(present)[0])
    result = set(proposed)
    for label in present:
        if label != keep:
            result.discard(label)
    return result


# ---------------------------------------------------------------------------
# Convenience helper for the 'tag' label cleanup
# ---------------------------------------------------------------------------

def remove_tag_trigger_label(labels: list[str]) -> list[str]:
    """Remove the manual 'tag' label that triggered this run."""
    return [l for l in labels if l != "tag"]
