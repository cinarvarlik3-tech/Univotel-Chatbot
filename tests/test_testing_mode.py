"""Tests for TESTING_LIMITATIONS_MODE phone-number gate."""
import pytest
from app.webhooks.chatwoot import _normalize_phone, _is_allowed
from app.config import TESTING_PHONE_ALLOWLIST as _TESTING_ALLOWLIST


# ---------------------------------------------------------------------------
# _normalize_phone
# ---------------------------------------------------------------------------

def test_normalize_strips_spaces_and_dashes():
    assert _normalize_phone("+90 555 183 96 44") == "905551839644"
    assert _normalize_phone("+90-544-554-52-44") == "905445545244"


def test_normalize_none():
    assert _normalize_phone(None) == ""


def test_normalize_empty():
    assert _normalize_phone("") == ""


# ---------------------------------------------------------------------------
# _is_allowed — mode OFF (default)
# ---------------------------------------------------------------------------

def test_allowed_when_mode_off(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "testing_limitations_mode", False)
    # Any payload passes when mode is off
    assert _is_allowed({}) is True
    assert _is_allowed({"contact": {"phone_number": "+90 999 000 00 00"}}) is True


# ---------------------------------------------------------------------------
# _is_allowed — mode ON
# ---------------------------------------------------------------------------

def test_whitelisted_number_via_contact(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    payload = {"contact": {"phone_number": "+90 555 183 96 44"}}
    assert _is_allowed(payload) is True


def test_whitelisted_number_via_conversation_meta(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    payload = {
        "conversation": {
            "meta": {"sender": {"phone_number": "+90 544 554 52 44"}}
        }
    }
    assert _is_allowed(payload) is True


def test_non_whitelisted_number_blocked(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    payload = {"contact": {"phone_number": "+90 999 000 00 00"}}
    assert _is_allowed(payload) is False


def test_missing_phone_blocked(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    assert _is_allowed({}) is False
    assert _is_allowed({"contact": {}}) is False


def test_both_numbers_are_in_allowlist():
    assert "905551839644" in _TESTING_ALLOWLIST
    assert "905445545244" in _TESTING_ALLOWLIST


# ---------------------------------------------------------------------------
# TagAssigner router backstop — _is_taggable_in_testing_mode
# ---------------------------------------------------------------------------

import uuid


def _conv(contact_phone):
    from app.db.models import Conversation
    return Conversation(
        id=uuid.uuid4(),
        chatwoot_conversation_id=1,
        flow_state="new",
        contact_phone=contact_phone,
    )


def test_router_taggable_when_mode_off(monkeypatch):
    from app import config
    from app.tagassigner.router import _is_taggable_in_testing_mode
    monkeypatch.setattr(config.settings, "testing_limitations_mode", False)
    # Off-allowlist (and even None) phones are taggable when mode is off
    assert _is_taggable_in_testing_mode(_conv("905999000000")) is True
    assert _is_taggable_in_testing_mode(_conv(None)) is True


def test_router_taggable_allowlisted_when_mode_on(monkeypatch):
    from app import config
    from app.tagassigner.router import _is_taggable_in_testing_mode
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    assert _is_taggable_in_testing_mode(_conv("905551839644")) is True


def test_router_blocked_off_allowlist_when_mode_on(monkeypatch):
    from app import config
    from app.tagassigner.router import _is_taggable_in_testing_mode
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    assert _is_taggable_in_testing_mode(_conv("905999000000")) is False


def test_router_blocked_none_phone_when_mode_on(monkeypatch):
    from app import config
    from app.tagassigner.router import _is_taggable_in_testing_mode
    monkeypatch.setattr(config.settings, "testing_limitations_mode", True)
    assert _is_taggable_in_testing_mode(_conv(None)) is False
