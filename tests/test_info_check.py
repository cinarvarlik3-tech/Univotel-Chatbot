"""Unit tests for app/tagassigner/info_check.py (spec 018)."""
import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import Conversation
from app.tagassigner.attribute_merger import BlockedMismatch
from app.tagassigner.info_check import (
    INFO_CHECK_LABEL,
    apply_info_check,
    build_fingerprint,
    strip_gemini_info_check,
)


def _conv(**kwargs) -> Conversation:
    defaults = dict(
        id=uuid.uuid4(),
        chatwoot_conversation_id=1,
        flow_state="new",
        info_check_fingerprint=None,
        info_check_added_at=None,
        info_check_suppressed_fingerprint=None,
    )
    defaults.update(kwargs)
    return Conversation(**defaults)


def test_should_add_info_check_when_blocked_mismatch():
    blocked = [BlockedMismatch("university", "a", "b", "human_set")]
    now = datetime.now(tz=timezone.utc)
    decision = apply_info_check(["ogrenci"], _conv(), blocked, now)
    assert INFO_CHECK_LABEL in decision.labels
    assert decision.fingerprint == build_fingerprint(blocked[0])


def test_should_add_info_check_when_university_validation_failed():
    blocked = [BlockedMismatch(
        "university",
        "",
        "İstanbul Kültür Üniversitesi - Ataköy",
        "validation_failed",
    )]
    decision = apply_info_check(["fiyat-soruyor"], _conv(), blocked, datetime.now(tz=timezone.utc))
    assert INFO_CHECK_LABEL in decision.labels
    assert decision.fingerprint == build_fingerprint(blocked[0])


def test_should_add_info_check_when_campus_ambiguous_sentinel():
    blocked = [BlockedMismatch("university", "", "bilinmiyor-kampus", "campus_ambiguous")]
    decision = apply_info_check(["universitede"], _conv(), blocked, datetime.now(tz=timezone.utc))
    assert INFO_CHECK_LABEL in decision.labels
    assert decision.fingerprint == build_fingerprint(blocked[0])


def test_should_not_readd_when_suppressed_fingerprint_matches():
    blocked = [BlockedMismatch("university", "a", "b", "human_set")]
    fp = build_fingerprint(blocked[0])
    conv = _conv(info_check_suppressed_fingerprint=fp)
    decision = apply_info_check(["ogrenci"], conv, blocked, datetime.now(tz=timezone.utc))
    assert INFO_CHECK_LABEL not in decision.labels


def test_should_remove_info_check_after_48h_ttl():
    now = datetime.now(tz=timezone.utc)
    conv = _conv(info_check_added_at=now - timedelta(hours=49))
    decision = apply_info_check(
        ["ogrenci", INFO_CHECK_LABEL], conv, [], now
    )
    assert INFO_CHECK_LABEL not in decision.labels
    assert decision.clear_active is True


def test_should_clear_fingerprint_when_no_blocked_mismatches_and_label_absent():
    conv = _conv(info_check_fingerprint="university::x:y:validation_failed")
    decision = apply_info_check(["ogrenci"], conv, [], datetime.now(tz=timezone.utc))
    assert INFO_CHECK_LABEL not in decision.labels
    assert decision.clear_active is True


def test_strip_gemini_info_check():
    assert strip_gemini_info_check(["ogrenci", "info-check"]) == ["ogrenci"]
