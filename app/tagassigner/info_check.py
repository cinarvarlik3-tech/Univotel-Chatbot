"""
Router-owned info-check label logic (spec 018).

Gemini must never assign info-check; the Router adds/removes it based on blocked
attribute mismatches and TTL / human-dismiss rules.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.config import INFO_CHECK_TTL_HOURS
from app.db.models import Conversation
from app.tagassigner.attribute_merger import BlockedMismatch

INFO_CHECK_LABEL = "info-check"

_FIELD_PRIORITY = ("university", "ogrenci_cinsiyet", "oda_tiipi")


@dataclass
class InfoCheckDecision:
    labels: list[str]
    fingerprint: Optional[str] = None
    added_at: Optional[datetime] = None
    clear_active: bool = False
    suppressed_fingerprint: Optional[str] = None


def build_fingerprint(mismatch: BlockedMismatch) -> str:
    """Stable fingerprint for suppress / re-add logic."""
    return f"{mismatch.field}:{mismatch.current}:{mismatch.proposed}:{mismatch.reason}"


def pick_primary_mismatch(blocked: list[BlockedMismatch]) -> Optional[BlockedMismatch]:
    """Choose highest-priority blocked mismatch for fingerprint storage."""
    if not blocked:
        return None
    by_field = {m.field: m for m in blocked}
    for field in _FIELD_PRIORITY:
        if field in by_field:
            return by_field[field]
    return blocked[0]


def apply_info_check(
    resolved_labels: list[str],
    conv: Conversation,
    blocked: list[BlockedMismatch],
    now: datetime,
) -> InfoCheckDecision:
    """
    Compute final label set and DB info-check state updates.
    Input labels must not include Gemini-proposed info-check (Router strips that earlier).
    """
    labels = list(resolved_labels)
    has_label = INFO_CHECK_LABEL in labels

    # 48h TTL — stale flag cleanup (intentional; mismatch may persist)
    if (
        has_label
        and conv.info_check_added_at is not None
        and now >= conv.info_check_added_at + timedelta(hours=INFO_CHECK_TTL_HOURS)
    ):
        labels = [l for l in labels if l != INFO_CHECK_LABEL]
        return InfoCheckDecision(labels=labels, clear_active=True)

    if not blocked:
        if has_label:
            labels = [l for l in labels if l != INFO_CHECK_LABEL]
        return InfoCheckDecision(labels=labels, clear_active=has_label)

    primary = pick_primary_mismatch(blocked)
    if primary is None:
        return InfoCheckDecision(labels=labels)

    fp = build_fingerprint(primary)

    if fp == conv.info_check_suppressed_fingerprint:
        if has_label:
            labels = [l for l in labels if l != INFO_CHECK_LABEL]
        return InfoCheckDecision(labels=labels, clear_active=has_label)

    if INFO_CHECK_LABEL not in labels:
        labels.append(INFO_CHECK_LABEL)

    return InfoCheckDecision(
        labels=sorted(labels),
        fingerprint=fp,
        added_at=now,
    )


def strip_gemini_info_check(proposed_labels: list[str]) -> list[str]:
    """Remove info-check if Gemini incorrectly proposed it."""
    return [l for l in proposed_labels if l != INFO_CHECK_LABEL]
