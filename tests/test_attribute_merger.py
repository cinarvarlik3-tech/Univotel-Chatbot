"""Unit tests for app/tagassigner/attribute_merger.py (spec 018)."""
import uuid
import pytest

from app.db.models import Conversation
from app.tagassigner.attribute_merger import merge_attributes


def _conv(**kwargs) -> Conversation:
    defaults = dict(
        id=uuid.uuid4(),
        chatwoot_conversation_id=1,
        flow_state="new",
        university_id=None,
        gender=None,
        oda_tiipi=None,
        university_set_by=None,
        gender_set_by=None,
        oda_tiipi_set_by=None,
    )
    defaults.update(kwargs)
    return Conversation(**defaults)


def test_should_accept_university_when_db_empty_and_proposal_valid():
    conv = _conv()
    uid = uuid.uuid4()
    result = merge_attributes(
        conv,
        {"university": "Boğaziçi Üniversitesi", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=uid,
    )
    assert result.university_id == uid
    assert result.chatwoot_patches["university"] == "Boğaziçi Üniversitesi"


def test_should_block_university_when_human_set():
    conv = _conv(university_id=uuid.uuid4(), university_set_by="human")
    uid = uuid.uuid4()
    result = merge_attributes(
        conv,
        {"university": "Other Uni", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
        current_university_display="Current Uni",
        resolved_university_id=uid,
    )
    assert result.university_id is None
    assert len(result.blocked_mismatches) == 1
    assert result.blocked_mismatches[0].reason == "human_set"


def test_should_not_clear_oda_tiipi_when_proposed_bos():
    conv = _conv(oda_tiipi="Tek Kişilik")
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
    )
    assert result.oda_tiipi is None
    assert not result.blocked_mismatches


def test_should_set_oda_tiipi_when_db_empty_and_explicit_value():
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "Tek Kişilik"},
        current_university_display=None,
        resolved_university_id=None,
    )
    assert result.oda_tiipi == "Tek Kişilik"


def test_should_block_invalid_oda_tiipi():
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "Not A Real Type"},
        current_university_display=None,
        resolved_university_id=None,
    )
    assert result.oda_tiipi is None
    assert any(m.reason == "validation_failed" for m in result.blocked_mismatches)
