"""Unit tests for phrase gate evaluation (app/layers/phrase_gate.py)."""
import uuid

from app.db.models import Hotel, University, UniversityAlias
from app.layers.phrase_gate import PhraseGateAction, evaluate_phrase_gate


def _hotel(name: str) -> Hotel:
    return Hotel(id=uuid.uuid4(), name=name, is_visible=True)


def _uni(name: str) -> University:
    return University(id=uuid.uuid4(), name=name, university_short_name=None)


def test_phrase_gate_merhaba_first_message():
    result = evaluate_phrase_gate(
        "merhaba",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING
    assert result.reason == "filter3_greeting"


def test_phrase_gate_selam_first_message():
    result = evaluate_phrase_gate(
        "selam",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING


def test_phrase_gate_konaklama_first_message():
    result = evaluate_phrase_gate(
        "Merhabalar konaklama için yazıyorum",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING


def test_phrase_gate_yakin_first_message():
    result = evaluate_phrase_gate(
        "üniversiteme yakın yer arıyorum",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING
    assert result.reason == "filter6_proximity"


def test_phrase_gate_mid_conversation_ignored():
    result = evaluate_phrase_gate(
        "merhaba",
        is_first_inbound=False,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.IGNORE


def test_phrase_gate_hi_substring_false_positive_blocked():
    result = evaluate_phrase_gate(
        "this is a test",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.IGNORE


def test_phrase_gate_hotel_precondition_b():
    hotel = _hotel("Univotel Kadıköy")
    result = evaluate_phrase_gate(
        "Univotel Kadıköy hakkında bilgi",
        is_first_inbound=False,
        hotels=[hotel],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.HOTEL_PATH
    assert result.matched_hotel is not None
    assert result.matched_hotel.id == hotel.id


def test_phrase_gate_entity_filter2():
    uni = _uni("Marmara Üniversitesi")
    result = evaluate_phrase_gate(
        "Marmara Üniversitesi öğrencisiyim",
        is_first_inbound=True,
        hotels=[],
        universities=[uni],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING
    assert result.reason == "filter2_entity"


def test_phrase_gate_sa_greeting_variant():
    result = evaluate_phrase_gate(
        "sa",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING


def test_phrase_gate_slm_greeting_variant():
    result = evaluate_phrase_gate(
        "slm",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING


def test_phrase_gate_heyy_greeting_variant():
    result = evaluate_phrase_gate(
        "Heyy",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.GREETING


def test_phrase_gate_sa_substring_in_masa_not_matched():
    result = evaluate_phrase_gate(
        "masa",
        is_first_inbound=True,
        hotels=[],
        universities=[],
        aliases=[],
    )
    assert result.action == PhraseGateAction.IGNORE
