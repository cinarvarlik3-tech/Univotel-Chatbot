"""Unit tests for app/tagassigner/crm_import.py."""
from datetime import datetime, timezone

from app.tagassigner.crm_import import map_crm_message, normalize_phone, parse_ts


def test_should_normalize_turkish_local_phone_to_country_prefix():
    assert normalize_phone("05421374898") == "905421374898"


def test_should_keep_international_phone_digits():
    assert normalize_phone("+923332009521") == "923332009521"


def test_should_map_incoming_crm_message_to_inbound_contact():
    row = {
        "chatwoot_message_id": 101,
        "message_type": "incoming",
        "direction": "incoming",
        "content": "Merhaba",
        "sender_type": "contact",
        "sender_id": 12,
        "sender_name": "Lead",
        "is_private": False,
        "created_at": "2026-01-01T10:00:00+00:00",
    }
    mapped = map_crm_message(row)
    assert mapped is not None
    assert mapped["message_type"] == "inbound"
    assert mapped["sender_type"] == "contact"


def test_should_skip_private_and_activity_messages():
    assert map_crm_message({"message_type": "activity", "is_private": False}) is None
    assert map_crm_message({"message_type": "incoming", "is_private": True}) is None


def test_should_parse_iso_timestamp_with_z_suffix():
    ts = parse_ts("2026-01-01T10:00:00Z")
    assert ts == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
