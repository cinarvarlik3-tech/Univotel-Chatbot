"""Unit tests for app/tagassigner/attribute_merger.py (spec 018)."""
import uuid
import pytest

from app.db.models import Conversation, Message
from app.tagassigner.attribute_merger import (
    inbound_gender_signal,
    merge_attributes,
    reconcile_chatwoot_attributes,
)


def _msg(content, message_type: str = "inbound") -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        chatwoot_message_id=1,
        content=content,
        message_type=message_type,
    )


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


def test_should_block_campus_ambiguous_sentinel_for_info_check():
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor-kampus", "ogrenci_cinsiyet": "bilinmiyor", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
    )
    assert result.university_id is None
    assert "university" not in result.chatwoot_patches
    assert len(result.blocked_mismatches) == 1
    assert result.blocked_mismatches[0].reason == "campus_ambiguous"
    assert result.blocked_mismatches[0].proposed == "bilinmiyor-kampus"


def test_should_block_validation_failed_when_invented_university_unresolved():
    conv = _conv()
    result = merge_attributes(
        conv,
        {
            "university": "İstanbul Kültür Üniversitesi - Ataköy",
            "ogrenci_cinsiyet": "bilinmiyor",
            "oda_tiipi": "boş",
        },
        current_university_display=None,
        resolved_university_id=None,
    )
    assert result.university_id is None
    assert "university" not in result.chatwoot_patches
    assert any(m.reason == "validation_failed" for m in result.blocked_mismatches)


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


def test_should_emit_patch_when_db_has_value_and_chatwoot_is_empty():
    uid = uuid.uuid4()
    conv = _conv(university_id=uid, gender="female")
    patches = reconcile_chatwoot_attributes(
        conv,
        {},
        university_display="Yeni Yüzyıl Üniversitesi",
    )
    assert patches["university"] == "Yeni Yüzyıl Üniversitesi"
    assert patches["ogrenci_cinsiyet"] == "Kız"


def test_should_not_emit_patch_when_chatwoot_already_matches_db():
    uid = uuid.uuid4()
    conv = _conv(university_id=uid, gender="male")
    patches = reconcile_chatwoot_attributes(
        conv,
        {
            "university": "Boğaziçi Üniversitesi",
            "ogrenci_cinsiyet": "Erkek",
        },
        university_display="Boğaziçi Üniversitesi",
    )
    assert patches == {}


def test_should_not_overwrite_human_set_chatwoot_value():
    uid = uuid.uuid4()
    conv = _conv(university_id=uid, university_set_by="human", gender="female", gender_set_by="human")
    patches = reconcile_chatwoot_attributes(
        conv,
        {
            "university": "Human Picked Uni",
            "ogrenci_cinsiyet": "Erkek",
        },
        university_display="Yeni Yüzyıl Üniversitesi",
    )
    assert "university" not in patches
    assert "ogrenci_cinsiyet" not in patches


def test_should_only_reconcile_bot_writable_keys():
    conv = _conv(gender="female", ilgili_otel="Some Hotel")
    patches = reconcile_chatwoot_attributes(conv, {}, university_display=None)
    assert set(patches.keys()).issubset({"university", "ogrenci_cinsiyet", "oda_tiipi"})
    assert "ilgili_otel" not in patches


# ---------------------------------------------------------------------------
# A3 — inbound_gender_signal (TAGASSIGNER_ACCURACY_FIXES_PLAN.md)
# ---------------------------------------------------------------------------

def test_inbound_gender_signal_ignores_outbound_bot_pitch_text():
    """berkan (cw924): the bot's 'erkek öğrenci yurdumuzdur' pitch is OUTBOUND and must
    never be read as the lead's own gender."""
    messages = [
        _msg("Üniversitem: İstanbul Teknik Üniversitesi", "inbound"),
        _msg("Academia Seyrantepe ... erkek öğrenci yurdumuzdur", "outbound"),
        _msg("Maşallah fiyatlara bak", "inbound"),
        _msg("teşekkürler", "inbound"),
    ]
    assert inbound_gender_signal(messages) is None


def test_inbound_gender_signal_detects_bare_erkek_answer():
    assert inbound_gender_signal([_msg("erkek", "inbound")]) == "male"


def test_inbound_gender_signal_detects_bare_kiz_answer():
    assert inbound_gender_signal([_msg("kız", "inbound")]) == "female"


def test_inbound_gender_signal_detects_kizim_icin_as_female():
    """A veli's 'kızım için' legitimately reveals the housed student's gender."""
    assert inbound_gender_signal([_msg("kızım için soruyorum", "inbound")]) == "female"


def test_inbound_gender_signal_detects_oglum_icin_as_male():
    assert inbound_gender_signal([_msg("oğlum için bakıyorum", "inbound")]) == "male"


def test_inbound_gender_signal_none_when_no_inbound_text():
    messages = [_msg("erkek öğrenci yurdu", "outbound")]
    assert inbound_gender_signal(messages) is None


def test_inbound_gender_signal_none_when_contradictory():
    messages = [_msg("kız", "inbound"), _msg("erkek", "inbound")]
    assert inbound_gender_signal(messages) is None


def test_inbound_gender_signal_empty_messages():
    assert inbound_gender_signal([]) is None


# ---------------------------------------------------------------------------
# A3 — _merge_gender withholds without inbound corroboration
# ---------------------------------------------------------------------------

def test_merge_gender_withholds_concrete_proposal_with_no_inbound_signal():
    """berkan shape: LLM proposes Erkek from contaminated bot text; no inbound
    corroboration -> gender withheld, and NOT surfaced as a blocked_mismatch (would
    otherwise flood info-check on every lead who simply hasn't stated gender yet)."""
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "Erkek", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
        inbound_gender=None,
    )
    assert result.gender is None
    assert not result.gender_clear
    assert "ogrenci_cinsiyet" not in result.chatwoot_patches
    assert not result.blocked_mismatches


def test_merge_gender_accepts_when_inbound_corroborates():
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "Erkek", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
        inbound_gender="male",
    )
    assert result.gender == "male"
    assert result.chatwoot_patches["ogrenci_cinsiyet"] == "Erkek"


def test_merge_gender_withholds_when_inbound_disagrees():
    conv = _conv()
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "Erkek", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
        inbound_gender="female",
    )
    assert result.gender is None
    assert not result.blocked_mismatches


def test_merge_gender_clear_to_bilinmiyor_needs_no_inbound_corroboration():
    """Clearing (LLM says Bilinmiyor) is a different path — the no-clear guard already
    protects it; the inbound guard only gates a CONCRETE proposal."""
    conv = _conv(gender="male")
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "Bilinmiyor", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
        inbound_gender=None,
    )
    assert result.gender is None
    assert not result.gender_clear  # no-clear guard: don't erase an existing DB value


def test_merge_gender_human_set_still_wins_regardless_of_inbound_signal():
    conv = _conv(gender="female", gender_set_by="human")
    result = merge_attributes(
        conv,
        {"university": "bilinmiyor", "ogrenci_cinsiyet": "Erkek", "oda_tiipi": "boş"},
        current_university_display=None,
        resolved_university_id=None,
        inbound_gender="male",
    )
    assert result.gender is None
    assert len(result.blocked_mismatches) == 1
    assert result.blocked_mismatches[0].reason == "human_set"
