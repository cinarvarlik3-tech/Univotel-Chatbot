"""Unit tests for app/tagassigner/conflict.py — Option A timestamp conflict rule."""
from datetime import datetime, timezone
import pytest

from app.tagassigner.conflict import may_overwrite

_T0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2025, 1, 1, 12, 0, 1, tzinfo=timezone.utc)   # 1s after T0
_T_SAME = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)  # same as T0


# ---------------------------------------------------------------------------
# No current value — always allow (first-time write)
# ---------------------------------------------------------------------------

def test_no_current_value_always_allowed():
    assert may_overwrite("otel-a", None, None, None) is True


def test_no_current_value_with_timestamps():
    assert may_overwrite("otel-a", None, _T0, _T1) is True


# ---------------------------------------------------------------------------
# Proposed == current — allow (no actual change)
# ---------------------------------------------------------------------------

def test_same_value_always_allowed():
    assert may_overwrite("otel-a", "otel-a", _T0, None) is True


def test_same_value_no_timestamps():
    assert may_overwrite("x", "x", None, None) is True


# ---------------------------------------------------------------------------
# No field_set_at — allow (legacy row, no timestamp companion)
# ---------------------------------------------------------------------------

def test_no_set_at_allows_overwrite():
    assert may_overwrite("otel-b", "otel-a", None, _T1) is True


def test_no_set_at_no_evidence_at_allows():
    assert may_overwrite("otel-b", "otel-a", None, None) is True


# ---------------------------------------------------------------------------
# Core rule: newest_evidence_at STRICTLY > field_set_at
# ---------------------------------------------------------------------------

def test_evidence_strictly_newer_allows():
    assert may_overwrite("otel-b", "otel-a", _T0, _T1) is True


def test_evidence_equal_to_set_at_blocks():
    """Equal timestamps are NOT strictly newer — blocked."""
    assert may_overwrite("otel-b", "otel-a", _T0, _T_SAME) is False


def test_evidence_older_than_set_at_blocks():
    # Evidence at T0, field_set_at at T1 (newer) → blocked
    assert may_overwrite("otel-b", "otel-a", _T1, _T0) is False


def test_no_evidence_at_blocks():
    """Field has a set_at but we have no evidence timestamp → blocked."""
    assert may_overwrite("otel-b", "otel-a", _T0, None) is False


# ---------------------------------------------------------------------------
# Combinations confirming precedence order
# ---------------------------------------------------------------------------

def test_none_current_beats_evidence_check():
    """No current value → allowed regardless of timestamps."""
    assert may_overwrite("otel-b", None, _T1, _T0) is True


def test_same_value_beats_evidence_check():
    """Proposed == current → allowed regardless of timestamps."""
    assert may_overwrite("same", "same", _T1, _T0) is True


def test_no_set_at_beats_evidence_check():
    """No field_set_at → allowed regardless of evidence."""
    assert may_overwrite("otel-b", "otel-a", None, _T0) is True
