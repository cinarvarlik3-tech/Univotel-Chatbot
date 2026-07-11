"""
Unit tests for InfoGatherer invalid-input and campus-clarification handlers.
Mocks DB and Chatwoot send — no live Supabase required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Conversation, OutOfCityUniversity, University, UniversityAlias, UniversityParentMap
from app.layers import info_gatherer


@pytest.fixture(autouse=True)
def _mock_pre_recengine_catalog():
    """Uniform pre-RecEngine pipeline loads reference tables on every turn."""
    with patch.object(info_gatherer.queries, "get_all_hotels", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=None):
        yield


def _conversation(**kwargs) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "chatwoot_conversation_id": 52,
        "flow_state": "awaiting_university",
        "clarification_attempt": 0,
    }
    defaults.update(kwargs)
    return Conversation(**defaults)


def _ooc(name: str, short_name: str | None = None) -> OutOfCityUniversity:
    return OutOfCityUniversity(
        id=uuid.uuid4(),
        name=name,
        short_name=short_name,
        city="Ankara",
    )


def _istanbul_uni(name: str) -> University:
    return University(id=uuid.uuid4(), name=name)


@pytest.mark.asyncio
async def test_should_fire_out_of_city_on_first_none_in_awaiting_university():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    ooc = [_ooc("Hacettepe Üniversitesi", short_name="HÜ")]

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=ooc), \
         patch.object(info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True), \
         patch.object(info_gatherer, "_fire_out_of_city", new_callable=AsyncMock) as fire_ooc, \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match:
        await info_gatherer._handle_awaiting_university(conv, 52, "Hacettepe Üniversitesi")

    fire_ooc.assert_awaited_once_with(conv, 52)
    no_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_unknown_input_to_divergence_not_clarify():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_fire_out_of_city", new_callable=AsyncMock) as fire_ooc, \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_awaiting_university(conv, 52, "qwerty üniversitesi")

    divergence.assert_awaited_once_with(
        conv, 52, "qwerty üniversitesi",
        flow_state="awaiting_university", fallback="escalate_off_script",
    )
    no_match.assert_not_awaited()
    fire_ooc.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_off_script_university_reply_to_divergence():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence:
        await info_gatherer._handle_awaiting_university(conv, 52, "yeriniz nerde")

    divergence.assert_awaited_once_with(
        conv, 52, "yeriniz nerde",
        flow_state="awaiting_university", fallback="escalate_off_script",
    )
    no_match.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["konum neresi", "fiyat ne"])
async def test_should_route_short_question_to_divergence_not_clarify(content: str):
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence:
        await info_gatherer._handle_awaiting_university(conv, 52, content)

    divergence.assert_awaited_once_with(
        conv, 52, content,
        flow_state="awaiting_university", fallback="escalate_off_script",
    )
    no_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_unmatched_short_reply_to_divergence_not_clarify():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_awaiting_university(conv, 52, "TÖÜ")

    divergence.assert_awaited_once_with(
        conv, 52, "TÖÜ",
        flow_state="awaiting_university", fallback="escalate_off_script",
    )
    no_match.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_long_fake_university_name_to_divergence():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_awaiting_university(
            conv, 52, "totally fake university name",
        )

    divergence.assert_awaited_once()
    no_match.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_clarify_near_miss_typo_via_divergence_fallback():
    """Genuine typo'd uni names reach clarification via near-miss fallback, not persistence."""
    from app.layers.divergence_classifier import ClassificationResult, Intent

    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    marmara = _istanbul_uni("Marmara Üniversitesi")

    with patch("app.layers.divergence_classifier.classify", new_callable=AsyncMock, return_value=ClassificationResult(intent=Intent.NO_INTENT)), \
         patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[marmara]), \
         patch.object(info_gatherer, "is_near_miss_university", return_value=True), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer.queries, "update_divergence_persistence", new_callable=AsyncMock) as persist:
        await info_gatherer._run_divergence_recovery(
            conv, 52, "Marmaraa",
            flow_state="awaiting_university", fallback="escalate_off_script",
        )

    no_match.assert_awaited_once_with(conv, 52, "Marmaraa")
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_resolve_typo_to_parent_via_matcher():
    """F1: dist-1 alias typo resolves to parent before divergence/clarify."""
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    parent_id = uuid.uuid4()
    campus = _istanbul_uni("Marmara Üniversitesi - Göztepe Kampüsü")
    marmara_alias = UniversityAlias(
        id=uuid.uuid4(),
        parent_university_id=parent_id,
        alias="marmara",
    )

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[campus]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[marmara_alias]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_handle_parent_match", new_callable=AsyncMock, return_value=True) as parent_match, \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        result = await info_gatherer._run_deterministic_extraction(
            conv, 52, "Marmaraa", "awaiting_university",
        )

    assert result == "progress"
    parent_match.assert_awaited_once()
    no_match.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_question_to_divergence_when_university_pending():
    """A4: question-shaped input must not accept embedded university tokens."""
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    parent_id = uuid.uuid4()
    istanbul_alias = UniversityAlias(
        id=uuid.uuid4(),
        parent_university_id=parent_id,
        alias="istanbul üniversitesi",
    )

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[istanbul_alias]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_parent_match", new_callable=AsyncMock, return_value=True) as parent_match, \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True) as route_match:
        result = await info_gatherer._run_deterministic_extraction(
            conv, 52, "sadece İstanbul mu", "awaiting_university",
        )

    assert result == "none"
    parent_match.assert_not_awaited()
    route_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_still_match_bare_university_answer():
    """Bare one-word university answers must still resolve when not question-shaped."""
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    parent_id = uuid.uuid4()
    istanbul_alias = UniversityAlias(
        id=uuid.uuid4(),
        parent_university_id=parent_id,
        alias="istanbul üniversitesi",
    )

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[istanbul_alias]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_handle_parent_match", new_callable=AsyncMock, return_value=True) as parent_match, \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True) as route_match:
        result = await info_gatherer._run_deterministic_extraction(
            conv, 52, "İstanbul", "awaiting_university",
        )

    assert result == "progress"
    parent_match.assert_awaited_once()
    route_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_post_match_when_valid_university_before_classifier_runs():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)
    bogazici = _istanbul_uni("Boğaziçi Üniversitesi")

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[bogazici]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True) as route, \
         patch.object(info_gatherer, "_handle_post_match", new_callable=AsyncMock) as post_match, \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_awaiting_university(conv, 52, "boğaziçi")

    route.assert_awaited_once()
    post_match.assert_not_awaited()
    no_match.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_off_script_to_divergence_even_when_clarification_attempt_is_one():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=1)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_handle_university_no_match", new_callable=AsyncMock) as no_match, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence:
        await info_gatherer._handle_awaiting_university(conv, 52, "yeriniz nerede")

    divergence.assert_awaited_once()
    no_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_fire_out_of_city_on_clarification_retry():
    conv = _conversation(flow_state="awaiting_university_clarification", clarification_attempt=1)
    ooc = [_ooc("Hacettepe Üniversitesi", short_name="HÜ")]

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=ooc), \
         patch.object(info_gatherer, "_fire_out_of_city", new_callable=AsyncMock) as fire_ooc, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_clarification(conv, 52, "Hacettepe")

    fire_ooc.assert_awaited_once_with(conv, 52)
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_continue_istanbul_flow_on_clarification_retry():
    conv = _conversation(flow_state="awaiting_university_clarification", clarification_attempt=1)
    bogazici = _istanbul_uni("Boğaziçi Üniversitesi")

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[bogazici]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "reset_divergence_persistence", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_route_university_match", new_callable=AsyncMock, return_value=True) as route, \
         patch.object(info_gatherer, "_handle_post_match", new_callable=AsyncMock) as post_match, \
         patch.object(info_gatherer, "_fire_out_of_city", new_callable=AsyncMock) as fire_ooc, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_clarification(conv, 52, "boğaziçi")

    route.assert_awaited_once()
    post_match.assert_not_awaited()
    fire_ooc.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_escalate_silently_on_second_short_invalid_university():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=1)

    with patch.object(info_gatherer.queries, "increment_clarification_attempt", new_callable=AsyncMock) as inc, \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_university_no_match(conv, 52, "xyz")

    escalate.assert_awaited_once()
    send.assert_not_awaited()
    inc.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_reprompt_once_on_first_short_invalid_university():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "increment_clarification_attempt", new_callable=AsyncMock) as inc, \
         patch.object(info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock) as state, \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_university_no_match(conv, 52, "TÖÜ")

    send.assert_awaited_once_with(52, info_gatherer.CANNED_CLARIFY_UNI_NAME)
    inc.assert_awaited_once_with(conv.id)
    state.assert_not_awaited()
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_invalid_clarification_to_divergence():
    conv = _conversation(flow_state="awaiting_university_clarification", clarification_attempt=1)

    with patch.object(info_gatherer.queries, "get_all_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "get_all_out_of_city_universities", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send, \
         patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence:
        await info_gatherer._handle_clarification(conv, 52, "totally fake university name")

    divergence.assert_awaited_once()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_write_human_needed_label_on_escalate():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=1)

    with patch.object(info_gatherer.queries, "write_log", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_human_needed", new_callable=AsyncMock) as set_state, \
         patch.object(info_gatherer, "_write_human_needed_label", new_callable=AsyncMock) as write_label:
        await info_gatherer._escalate_human_needed(
            conv.id, 52, "University clarification reply failed twice — FallBack stub",
        )

    set_state.assert_awaited_once_with(conv.id)
    write_label.assert_awaited_once_with(52)


@pytest.mark.asyncio
async def test_should_append_human_needed_label_when_missing():
    with patch("app.chatwoot_client.get_labels", new_callable=AsyncMock, return_value=["ogrenci"]), \
         patch("app.chatwoot_client.set_labels", new_callable=AsyncMock) as set_labels:
        set_labels.return_value.ok = True
        await info_gatherer._write_human_needed_label(52)

    set_labels.assert_awaited_once_with(52, ["ogrenci", "human_needed"])


@pytest.mark.asyncio
async def test_should_send_istanbul_canned_and_complete_on_fire_out_of_city():
    conv = _conversation(flow_state="awaiting_university", clarification_attempt=0)

    with patch.object(info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True) as state, \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send:
        await info_gatherer._fire_out_of_city(conv, 52)

    state.assert_awaited_once_with(conv.id, "completed", "awaiting_university")
    send.assert_awaited_once_with(52, info_gatherer.CANNED_ISTANBUL)


@pytest.mark.asyncio
async def test_should_match_campus_via_alias_in_clarification():
    parent_id = uuid.uuid4()
    macaka_id = uuid.uuid4()
    conv = _conversation(
        flow_state="awaiting_campus_clarification",
        pending_parent_university_id=parent_id,
    )
    campuses = [
        UniversityParentMap(
            university_id=macaka_id,
            parent_university_id=parent_id,
            campus_label="Maçka",
        ),
    ]
    aliases = [
        UniversityAlias(
            id=uuid.uuid4(),
            university_id=macaka_id,
            alias="taşkışla",
        ),
    ]

    with patch.object(info_gatherer.queries, "get_campuses_for_parent", new_callable=AsyncMock, return_value=campuses), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=aliases), \
         patch.object(info_gatherer.queries, "set_conversation_pending_parent", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "reset_clarification_attempt", new_callable=AsyncMock), \
         patch.object(info_gatherer, "_handle_post_match", new_callable=AsyncMock) as post_match, \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock):
        await info_gatherer._handle_awaiting_campus_clarification(conv, 52, "taşkışla")

    post_match.assert_awaited_once_with(conv, 52, macaka_id)


@pytest.mark.asyncio
async def test_should_reprompt_on_first_invalid_campus_reply():
    parent_id = uuid.uuid4()
    conv = _conversation(
        flow_state="awaiting_campus_clarification",
        pending_parent_university_id=parent_id,
        clarification_attempt=0,
    )
    campuses = [
        UniversityParentMap(
            university_id=uuid.uuid4(),
            parent_university_id=parent_id,
            campus_label="Maslak",
        ),
    ]

    with patch.object(info_gatherer.queries, "get_campuses_for_parent", new_callable=AsyncMock, return_value=campuses), \
         patch.object(info_gatherer.queries, "get_all_university_aliases", new_callable=AsyncMock, return_value=[]), \
         patch.object(info_gatherer.queries, "increment_clarification_attempt", new_callable=AsyncMock) as inc, \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send, \
         patch.object(info_gatherer, "_escalate_human_needed", new_callable=AsyncMock) as escalate:
        await info_gatherer._handle_awaiting_campus_clarification(conv, 52, "Beşiktaş")

    send.assert_awaited_once_with(52, info_gatherer.CANNED_CLARIFY_CAMPUS_NAME)
    inc.assert_awaited_once_with(conv.id)
    escalate.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_proceed_to_gender_when_university_on_deal_awaiting_list():
    """Post-match no longer short-circuits deal_awaiting members — RecEngine decides."""
    conv = _conversation(flow_state="awaiting_university")
    uni = _istanbul_uni("İstanbul Üniversitesi Cerrahpaşa")

    with patch.object(info_gatherer.queries, "reset_clarification_attempt", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "set_conversation_university", new_callable=AsyncMock), \
         patch.object(info_gatherer.queries, "get_conversation_by_id", new_callable=AsyncMock, return_value=conv), \
         patch.object(info_gatherer.queries, "update_conversation_state", new_callable=AsyncMock, return_value=True) as update, \
         patch.object(info_gatherer.queries, "is_deal_awaiting_university", new_callable=AsyncMock, return_value=True), \
         patch.object(info_gatherer, "_send_canned", new_callable=AsyncMock) as send, \
         patch.object(info_gatherer, "_write_deal_awaiting_label", new_callable=AsyncMock) as write_label, \
         patch.object(info_gatherer, "_send_hotel_responses", new_callable=AsyncMock) as send_hotel:
        await info_gatherer._handle_post_match(conv, 52, uni.id)

    update.assert_awaited_once_with(conv.id, "awaiting_gender", conv.flow_state)
    send.assert_awaited_once_with(52, info_gatherer.CANNED_KIZ_ERKEK)
    write_label.assert_not_awaited()
    send_hotel.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_off_script_gender_reply_to_divergence():
    conv = _conversation(flow_state="awaiting_gender", clarification_attempt=0)

    with patch.object(info_gatherer, "_run_divergence_recovery", new_callable=AsyncMock) as divergence, \
         patch.object(info_gatherer.queries, "set_conversation_gender", new_callable=AsyncMock) as set_gender:
        await info_gatherer._handle_awaiting_gender(conv, 52, "yeriniz nerde")

    divergence.assert_awaited_once_with(
        conv, 52, "yeriniz nerde",
        flow_state="awaiting_gender", fallback="escalate_off_script",
    )
    set_gender.assert_not_awaited()
