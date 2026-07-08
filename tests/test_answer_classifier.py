"""
Unit tests for answer-vs-off-script classification (app/layers/answer_classifier.py).

Validates the classifier that runs after match_university() and match_out_of_city()
both return NONE in awaiting_university.
"""
from __future__ import annotations

import uuid

from app.layers.answer_classifier import AnswerAssessment, classify_university_reply
from app.db.models import University


def _uni(name: str, short_name: str | None = None) -> University:
    return University(id=uuid.uuid4(), name=name, university_short_name=short_name)


def test_should_return_not_an_answer_when_message_is_a_wh_question():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("yeriniz nerde", unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_not_an_answer_when_message_has_third_person_referent():
    unis = [_uni("Boğaziçi Üniversitesi")]
    text = "kızım üniversiteye geçti ona yurt bakıyoruz"
    assert classify_university_reply(text, unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_not_an_answer_when_message_ends_with_question_mark():
    unis = [_uni("Marmara Üniversitesi")]
    assert classify_university_reply("fiyatlar ne kadar?", unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_not_an_answer_when_message_has_request_verb():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("konaklama arıyorum", unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_not_an_answer_when_message_has_question_clitic():
    unis = [_uni("Marmara Üniversitesi")]
    assert classify_university_reply("fiyat bilgisi alabilir miyim", unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_not_an_answer_when_message_is_long_rambling_without_answer_shape():
    unis = [_uni("Boğaziçi Üniversitesi")]
    text = "bugün çok yorgunum ve parka gittim sonra eve döndüm"
    assert classify_university_reply(text, unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_return_answer_attempt_when_message_is_a_near_miss_typo():
    unis = [_uni("Marmara Üniversitesi")]
    assert classify_university_reply("marmxxyy", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_return_answer_attempt_when_message_is_short_gibberish():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("asdfgh", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_return_answer_attempt_when_message_is_a_bare_proper_noun():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("TÖÜ", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_return_answer_attempt_when_message_is_long_fake_university_name():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply(
        "totally fake university name", unis,
    ) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_return_answer_attempt_when_message_mentions_university_with_typo():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("qwerty üniversitesi", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_prefer_off_script_over_near_miss_when_both_present():
    unis = [_uni("Marmara Üniversitesi")]
    assert classify_university_reply("marmxxyy nerede", unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_prefer_off_script_over_education_anchor_when_both_present():
    unis = [_uni("Boğaziçi Üniversitesi")]
    text = "kızım üniversiteye geçti ona yurt bakıyoruz"
    assert classify_university_reply(text, unis) == AnswerAssessment.NOT_AN_ANSWER


def test_should_treat_cihangir_as_answer_attempt_not_off_script():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("Cihangir", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_treat_kagithane_as_answer_attempt_not_off_script():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("Kağıthane", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_treat_gunesli_as_answer_attempt_not_off_script():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("Güneşli", unis) == AnswerAssessment.ANSWER_ATTEMPT


def test_should_still_flag_ne_kadar_as_off_script():
    unis = [_uni("Boğaziçi Üniversitesi")]
    assert classify_university_reply("ne kadar", unis) == AnswerAssessment.NOT_AN_ANSWER
