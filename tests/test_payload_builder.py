"""Unit tests for app/tagassigner/payload_builder.py.

parse_gemini_response: pure JSON parsing, no I/O.
build_payload / _build_transcript / _build_context: need Conversation + Message
  model objects — constructed directly, no DB calls.
"""
import uuid
import pytest
from unittest.mock import patch

from app.tagassigner.payload_builder import (
    parse_gemini_response,
    build_payload,
    build_batch_request,
    _build_transcript,
    _build_context,
)


# ---------------------------------------------------------------------------
# parse_gemini_response
# ---------------------------------------------------------------------------

def test_parse_clean_json():
    raw = '{"labels": ["ogrenci", "ziyaret"]}'
    result = parse_gemini_response(raw)
    assert result == ["ogrenci", "ziyaret"]


def test_parse_empty_labels():
    raw = '{"labels": []}'
    result = parse_gemini_response(raw)
    assert result == []


def test_parse_strips_markdown_fence_json():
    raw = '```json\n{"labels": ["ogrenci"]}\n```'
    result = parse_gemini_response(raw)
    assert result == ["ogrenci"]


def test_parse_strips_plain_markdown_fence():
    raw = '```\n{"labels": ["veli"]}\n```'
    result = parse_gemini_response(raw)
    assert result == ["veli"]


def test_parse_returns_none_on_invalid_json():
    assert parse_gemini_response("not json at all") is None


def test_parse_returns_none_on_json_array():
    assert parse_gemini_response('["ogrenci"]') is None


def test_parse_returns_none_when_labels_key_missing():
    assert parse_gemini_response('{"tags": ["ogrenci"]}') is None


def test_parse_returns_none_when_labels_not_list():
    assert parse_gemini_response('{"labels": "ogrenci"}') is None


def test_parse_drops_non_string_items():
    raw = '{"labels": ["ogrenci", 42, null, "ziyaret"]}'
    result = parse_gemini_response(raw)
    assert result == ["ogrenci", "ziyaret"]


def test_parse_extra_keys_ignored():
    raw = '{"labels": ["ogrenci"], "extra": "ignored"}'
    assert parse_gemini_response(raw) == ["ogrenci"]


def test_parse_empty_string_returns_none():
    assert parse_gemini_response("") is None


def test_parse_whitespace_only_returns_none():
    assert parse_gemini_response("   ") is None


# ---------------------------------------------------------------------------
# Helpers — _build_transcript
# ---------------------------------------------------------------------------

def _msg(message_type, content):
    from app.db.models import Message
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        chatwoot_message_id=1,
        message_type=message_type,
        content=content,
    )


def test_transcript_inbound_prefix():
    msgs = [_msg("inbound", "Merhaba")]
    result = _build_transcript(msgs)
    assert result.startswith("Müşteri:")


def test_transcript_outbound_prefix():
    msgs = [_msg("outbound", "Nasıl yardımcı olabilirim?")]
    result = _build_transcript(msgs)
    assert result.startswith("Bot:")


def test_transcript_empty_messages():
    result = _build_transcript([])
    assert result == "(Konuşma mesajı bulunamadı)"


def test_transcript_skips_empty_content():
    msgs = [_msg("inbound", ""), _msg("inbound", "Merhaba")]
    result = _build_transcript(msgs)
    assert result.count("Müşteri:") == 1
    assert "Merhaba" in result


def test_transcript_skips_none_content():
    from app.db.models import Message
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        chatwoot_message_id=1,
        message_type="inbound",
        content=None,
    )
    result = _build_transcript([msg])
    assert result == "(Konuşma mesajı bulunamadı)"


def test_transcript_multiple_messages_order():
    msgs = [
        _msg("inbound", "Merhaba"),
        _msg("outbound", "Selam"),
        _msg("inbound", "Oda soracaktım"),
    ]
    result = _build_transcript(msgs)
    lines = result.splitlines()
    assert lines[0].startswith("Müşteri:")
    assert lines[1].startswith("Bot:")
    assert lines[2].startswith("Müşteri:")


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------

def _conv(**kwargs):
    from app.db.models import Conversation
    defaults = dict(
        id=uuid.uuid4(),
        chatwoot_conversation_id=42,
        flow_state="new",
        university_id=None,
        gender=None,
        ilgili_otel=None,
        tasinma_tarihi=None,
        kayip_nedeni=None,
        oda_tiipi=None,
        butce=None,
        labels=[],
    )
    defaults.update(kwargs)
    return Conversation(**defaults)


def test_context_contains_university_id():
    conv = _conv(university_id=uuid.UUID("11111111-0000-0000-0000-000000000001"))
    ctx = _build_context(conv, [])
    assert "11111111-0000-0000-0000-000000000001" in ctx


def test_context_shows_bilinmiyor_when_no_university():
    conv = _conv()
    ctx = _build_context(conv, [])
    assert "bilinmiyor" in ctx


def test_context_contains_current_labels():
    conv = _conv()
    ctx = _build_context(conv, ["ogrenci", "ziyaret"])
    assert "ogrenci" in ctx
    assert "ziyaret" in ctx


def test_context_shows_yok_when_no_labels():
    conv = _conv()
    ctx = _build_context(conv, [])
    assert "yok" in ctx


def test_context_shows_bos_for_none_attributes():
    conv = _conv(ilgili_otel=None)
    ctx = _build_context(conv, [])
    assert "boş" in ctx


def test_context_shows_attribute_value():
    conv = _conv(ilgili_otel="Univotel Kadıköy")
    ctx = _build_context(conv, [])
    assert "Univotel Kadıköy" in ctx


# ---------------------------------------------------------------------------
# build_payload — keys and structure
# ---------------------------------------------------------------------------

def test_build_payload_keys():
    conv = _conv()
    result = build_payload(conv, [], [])
    assert "system_prompt" in result
    assert "user_content" in result


def test_build_payload_system_prompt_is_string():
    conv = _conv()
    result = build_payload(conv, [], [])
    assert isinstance(result["system_prompt"], str)


def test_build_payload_user_content_contains_transcript_header():
    conv = _conv()
    result = build_payload(conv, [], [])
    assert "## Konuşma" in result["user_content"]


def test_build_payload_user_content_contains_context_header():
    conv = _conv()
    result = build_payload(conv, [], [])
    assert "## Mevcut Durum" in result["user_content"]


# ---------------------------------------------------------------------------
# build_batch_request — custom_id threading
# ---------------------------------------------------------------------------

def test_build_batch_request_has_custom_id():
    conv = _conv()
    result = build_batch_request(conv, [], [], custom_id="abc-123")
    assert result["custom_id"] == "abc-123"


def test_build_batch_request_inherits_payload():
    conv = _conv()
    result = build_batch_request(conv, [], [], custom_id="x")
    assert "system_prompt" in result
    assert "user_content" in result
