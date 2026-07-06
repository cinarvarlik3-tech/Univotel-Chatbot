"""
InfoGatherer — ContextRun state machine (§5.1).

Entry point: process_message(conversation_id, chatwoot_conversation_id, message_content)
Called from the webhook background task for every inbound text message.
"""
from __future__ import annotations
import asyncio
import logging
import re
import uuid
from typing import Optional

from app.db import queries
from app.db.models import ChatbotLog, Conversation
from app.layers.matching import (
    MatchConfidence,
    match_hotel_by_ngram,
    match_out_of_city,
    match_university,
    scan_entities_by_ngram,
    word_count_after_normalize,
)
from app.layers.phrase_gate import PhraseGateAction, evaluate_phrase_gate
from app.background.send_retry import send_with_retry

logger = logging.getLogger(__name__)

UNIVERSITY_KEYWORDS = re.compile(
    r"(Üniversitesi|Universitesi|Üni|uni\b)",
    re.IGNORECASE,
)

GENDER_FEMALE = re.compile(r"\b(kiz|kız|bayan|kadın|kadin)\b", re.IGNORECASE)
GENDER_MALE = re.compile(r"\b(bay|erkek|oglan|oğlan)\b", re.IGNORECASE)

CANNED_HANGI = "hangi"
CANNED_KIZ_ERKEK = "kiz-erkek"
CANNED_ISTANBUL = "istanbul"
CANNED_CLARIFY = "clarify_uni"
CANNED_CLARIFY_UNI_NAME = "clarify_uni_name"
CANNED_CLARIFY_CAMPUS_NAME = "clarify_campus_name"

LAYER = "infoGatherer"

_VOWEL_SUFFIX: dict[str, str] = {
    'a': 'mı', 'A': 'mı', 'ı': 'mı', 'I': 'mı',
    'e': 'mi', 'E': 'mi', 'i': 'mi', 'İ': 'mi',
    'o': 'mu', 'O': 'mu', 'u': 'mu', 'U': 'mu',
    'ö': 'mü', 'Ö': 'mü', 'ü': 'mü', 'Ü': 'mü',
}


async def _send_canned(chatwoot_id: int, short_code: str) -> bool:
    cr = await queries.get_canned_response_by_short_code(short_code)
    if not cr:
        logger.fatal("InfoGatherer: canned response '%s' not found in DB", short_code)
        return False
    result = await send_with_retry(chatwoot_id, cr.content)
    return result.ok


async def _send_hotel_responses(
    conversation_id: uuid.UUID,
    chatwoot_id: int,
    hotel_id: uuid.UUID,
) -> bool:
    contents = await queries.get_canned_responses_for_hotel(hotel_id)
    if not contents:
        logger.fatal(
            "InfoGatherer: no response_schemas rows for hotel_id=%s (conversation=%s)",
            hotel_id, conversation_id,
        )
        await queries.write_log(ChatbotLog(
            conversation_id=conversation_id,
            operation_layer=LAYER,
            which_run="outputRun",
            log_level="fatal",
            is_success=False,
            status_code="404",
            explanation=f"No matching row in response_schemas for hotel_id={hotel_id}",
        ))
        await queries.set_conversation_human_needed(conversation_id)
        await _write_human_needed_label(chatwoot_id)
        return False

    for content in contents:
        result = await send_with_retry(chatwoot_id, content)
        if not result.ok:
            logger.error(
                "InfoGatherer: failed to send canned response for hotel_id=%s", hotel_id
            )
            return False
    return True


async def _fire_hotel_path(
    conversation: Conversation,
    cwid: int,
    hotel_id: uuid.UUID,
) -> None:
    """Direct hotel path — sends schemas and refreshes ilgili_otel without clearing uni/gender."""
    cid = conversation.id
    if conversation.flow_state != "completed":
        advanced = await queries.update_conversation_state(
            cid, "completed", conversation.flow_state
        )
        if not advanced:
            return

    await _send_hotel_responses(cid, cwid, hotel_id)

    from app.tagassigner.attribute_resolver import write_attributes_at_flow_completion
    await write_attributes_at_flow_completion(cid, cwid)


async def _log_phrase_gate_ignore(conversation_id: uuid.UUID, reason: str) -> None:
    logger.info(
        "InfoGatherer: phrase gate ignored for conversation %s — %s",
        conversation_id, reason,
    )
    await queries.write_log(ChatbotLog(
        conversation_id=conversation_id,
        operation_layer=LAYER,
        which_run="contextRun",
        log_level="info",
        is_success=True,
        explanation=f"Phrase gate ignored: {reason}",
    ))


async def _escalate_human_needed(
    conversation_id: uuid.UUID,
    chatwoot_id: int,
    explanation: str,
    internal_class: Optional[str] = None,
    status_code: Optional[str] = None,
) -> None:
    await queries.write_log(ChatbotLog(
        conversation_id=conversation_id,
        operation_layer=LAYER,
        which_run="contextRun",
        log_level="fatal",
        is_success=False,
        status_code=status_code,
        internal_class=internal_class,
        explanation=explanation,
    ))
    await queries.set_conversation_human_needed(conversation_id)
    await _write_human_needed_label(chatwoot_id)


def _extract_university_candidate(text: str) -> Optional[str]:
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if "Üniversitem:" in line or "My University:" in line:
            colon_idx = line.find(":")
            candidate = line[colon_idx + 1:].strip() if colon_idx != -1 else ""
            if not candidate and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
            return candidate if candidate else None

    match = UNIVERSITY_KEYWORDS.search(text)
    if match:
        before = text[: match.start()].strip()
        words_before = before.split()
        narrow = " ".join(words_before[-4:]) if words_before else ""
        if narrow:
            return narrow
        for i, line in enumerate(lines):
            if UNIVERSITY_KEYWORDS.search(line):
                context_lines = lines[max(0, i - 1): i + 2]
                return " ".join(context_lines)

    return None


def _extract_gender(text: str) -> Optional[str]:
    if GENDER_FEMALE.search(text):
        return "female"
    if GENDER_MALE.search(text):
        return "male"
    return None


async def _resolve_university_from_greeting(content: str, all_unis, all_aliases):
    candidate = _extract_university_candidate(content)
    if candidate:
        result = match_university(candidate, all_unis, all_aliases)
        if result.confidence != MatchConfidence.NONE:
            return result
    return scan_entities_by_ngram(content, all_unis, all_aliases)


def _turkish_question_suffix(word: str) -> str:
    for ch in reversed(word):
        if ch in _VOWEL_SUFFIX:
            return _VOWEL_SUFFIX[ch]
    return "mı"


async def _build_campus_question(parent_id: uuid.UUID) -> Optional[str]:
    parent = await queries.get_parent_university_by_id(parent_id)
    if not parent:
        logger.error("InfoGatherer: parent_university_id=%s not found", parent_id)
        return None
    campuses = await queries.get_campuses_for_parent(parent_id)
    if not campuses:
        logger.error("InfoGatherer: no campus rows for parent_university_id=%s", parent_id)
        return None
    parts = [f"{c.campus_label} {_turkish_question_suffix(c.campus_label)}" for c in campuses]
    return parent.question.format(name=parent.name, campuses=", ".join(parts))


async def _write_deal_awaiting_label(chatwoot_id: int) -> None:
    await _append_chatwoot_label(chatwoot_id, "deal_awaiting")


async def _write_human_needed_label(chatwoot_id: int) -> None:
    await _append_chatwoot_label(chatwoot_id, "human_needed")


async def _append_chatwoot_label(chatwoot_id: int, label: str) -> None:
    from app.chatwoot_client import get_labels, set_labels

    current = await get_labels(chatwoot_id)
    if current is None:
        logger.error(
            "InfoGatherer: could not fetch labels for conversation %d — skipping label write",
            chatwoot_id,
        )
        return
    if label not in current:
        result = await set_labels(chatwoot_id, current + [label])
        if not result.ok:
            logger.error(
                "InfoGatherer: failed to write %s label for conversation %d: %s",
                label, chatwoot_id, result.error,
            )


async def _handle_post_match(
    conversation: Conversation,
    cwid: int,
    university_id: uuid.UUID,
) -> None:
    cid = conversation.id
    await queries.reset_clarification_attempt(cid)

    await queries.set_conversation_university(cid, university_id)
    advanced = await queries.update_conversation_state(cid, "awaiting_gender", conversation.flow_state)
    if not advanced:
        return
    await _send_canned(cwid, CANNED_KIZ_ERKEK)


async def _handle_parent_match(
    conversation: Conversation,
    cwid: int,
    parent_university_id: uuid.UUID,
) -> None:
    cid = conversation.id
    await queries.reset_clarification_attempt(cid)
    campuses = await queries.get_campuses_for_parent(parent_university_id)

    if len(campuses) == 1:
        await _handle_post_match(conversation, cwid, campuses[0].university_id)
        return

    if not campuses:
        await _escalate_human_needed(
            cid, cwid,
            f"Parent university {parent_university_id} has no campus rows — cannot escalate",
        )
        return

    question = await _build_campus_question(parent_university_id)
    if not question:
        await _escalate_human_needed(
            cid, cwid,
            f"Failed to build campus question for parent {parent_university_id}",
        )
        return

    advanced = await queries.update_conversation_state(
        cid, "awaiting_campus_clarification", conversation.flow_state
    )
    if not advanced:
        return
    await queries.set_conversation_pending_parent(cid, parent_university_id)
    result = await send_with_retry(cwid, question)
    if not result.ok:
        logger.error(
            "InfoGatherer: failed to send campus escalation question for conversation %s", cid
        )


async def _route_university_match(
    conversation: Conversation,
    cwid: int,
    result,
) -> bool:
    if result.confidence == MatchConfidence.NONE:
        return False

    if result.confidence == MatchConfidence.AMBIGUOUS:
        advanced = await queries.update_conversation_state(
            conversation.id, "awaiting_university_clarification", conversation.flow_state
        )
        if not advanced:
            return True
        await _send_canned(cwid, CANNED_CLARIFY)
        return True

    if result.parent_university_id:
        await _handle_parent_match(conversation, cwid, result.parent_university_id)
        return True

    if result.university_id:
        await _handle_post_match(conversation, cwid, result.university_id)
        return True

    return False


async def process_message(
    conversation: Conversation,
    chatwoot_conversation_id: int,
    message_content: str,
    chatwoot_message_id: Optional[int] = None,
) -> None:
    state = conversation.flow_state
    cid = conversation.id
    cwid = chatwoot_conversation_id
    content = (message_content or "").strip()

    if state in ("stopped", "human_needed"):
        logger.info("InfoGatherer: conversation %s is terminal (%s) — no action", cid, state)
        return

    if not content:
        logger.info("InfoGatherer: empty message in conversation %s — keeping state", cid)
        return

    if state == "awaiting_campus_clarification":
        await _handle_awaiting_campus_clarification(conversation, cwid, content)
        return

    if state == "awaiting_gender":
        await _handle_awaiting_gender(conversation, cwid, content)
        return

    if state == "awaiting_university_clarification":
        await _handle_clarification(conversation, cwid, content)
        return

    if state == "awaiting_university":
        await _handle_awaiting_university(conversation, cwid, content)
        return

    if state == "recengine_running":
        logger.info(
            "InfoGatherer: conversation %s still in recengine_running — ignoring text reply", cid
        )
        return

    if state == "completed":
        await _handle_post_completion(conversation, cwid, content)
        return

    await _handle_new(conversation, cwid, content, chatwoot_message_id)


async def _handle_new(
    conversation: Conversation,
    cwid: int,
    content: str,
    chatwoot_message_id: Optional[int],
) -> None:
    cid = conversation.id

    if chatwoot_message_id is not None:
        is_first = await queries.is_first_inbound_message(cid, chatwoot_message_id)
    else:
        is_first = conversation.flow_state == "new"

    all_hotels = await queries.get_all_hotels()
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()

    gate = evaluate_phrase_gate(
        content,
        is_first_inbound=is_first,
        hotels=all_hotels,
        universities=all_unis,
        aliases=all_aliases,
    )

    if gate.action == PhraseGateAction.IGNORE:
        await _log_phrase_gate_ignore(cid, gate.reason)
        return

    if gate.action == PhraseGateAction.HOTEL_PATH and gate.matched_hotel is not None:
        await _fire_hotel_path(conversation, cwid, gate.matched_hotel.id)
        return

    hotel = match_hotel_by_ngram(content, all_hotels)
    if hotel is not None:
        await _fire_hotel_path(conversation, cwid, hotel.id)
        return

    gender = _extract_gender(content)
    if gender:
        await queries.set_conversation_gender(cid, gender)

    uni_result = await _resolve_university_from_greeting(content, all_unis, all_aliases)
    if await _route_university_match(conversation, cwid, uni_result):
        return

    advanced = await queries.update_conversation_state(
        cid, "awaiting_university", conversation.flow_state
    )
    if not advanced:
        return
    await _send_canned(cwid, CANNED_HANGI)


async def _fire_out_of_city(conversation: Conversation, cwid: int) -> None:
    cid = conversation.id
    advanced = await queries.update_conversation_state(
        cid, "completed", conversation.flow_state
    )
    if not advanced:
        return
    await _send_canned(cwid, CANNED_ISTANBUL)


async def _handle_university_no_match(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id

    if conversation.clarification_attempt >= 1:
        await _escalate_human_needed(
            cid, cwid,
            f"University clarification reply '{content[:80]}' failed twice — FallBack stub",
        )
        return

    await _send_canned(cwid, CANNED_CLARIFY_UNI_NAME)
    await queries.increment_clarification_attempt(cid)
    if word_count_after_normalize(content) > 2:
        await queries.update_conversation_state(
            cid, "awaiting_university_clarification", "awaiting_university"
        )


async def _handle_awaiting_university(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    result = match_university(content, all_unis, all_aliases)

    if result.confidence == MatchConfidence.NONE:
        all_ooc = await queries.get_all_out_of_city_universities()
        ooc_match = match_out_of_city(content, all_ooc)
        if ooc_match:
            await _fire_out_of_city(conversation, cwid)
            return
        await _handle_university_no_match(conversation, cwid, content)
        return

    await _route_university_match(conversation, cwid, result)


async def _handle_clarification(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    result = match_university(content, all_unis, all_aliases)

    if result.confidence in (MatchConfidence.NONE, MatchConfidence.AMBIGUOUS):
        all_ooc = await queries.get_all_out_of_city_universities()
        ooc_match = match_out_of_city(content, all_ooc)
        if ooc_match:
            await _fire_out_of_city(conversation, cwid)
            return
        await _escalate_human_needed(
            cid, cwid,
            f"University clarification reply '{content[:80]}' matched neither Istanbul nor out-of-city — FallBack stub",
        )
        return

    if result.parent_university_id:
        await _handle_parent_match(conversation, cwid, result.parent_university_id)
        return

    if result.university_id:
        await _handle_post_match(conversation, cwid, result.university_id)


async def _handle_awaiting_campus_clarification(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    from app.layers.matching import normalize

    cid = conversation.id
    parent_id = conversation.pending_parent_university_id
    if not parent_id:
        await _escalate_human_needed(
            cid, cwid,
            "awaiting_campus_clarification with no pending_parent_university_id — data inconsistency",
            internal_class="missing_pending_parent",
        )
        return

    campuses = await queries.get_campuses_for_parent(parent_id)
    if not campuses:
        await _escalate_human_needed(cid, cwid, f"No campus rows for pending parent {parent_id}")
        return

    all_aliases = await queries.get_all_university_aliases()

    normalized_reply = normalize(content)
    matched = None
    for campus in campuses:
        if normalize(campus.campus_label) == normalized_reply:
            matched = campus
            break
        campus_aliases = [
            a for a in all_aliases if a.university_id == campus.university_id
        ]
        for alias in campus_aliases:
            if normalize(alias.alias) == normalized_reply:
                matched = campus
                break
        if matched:
            break

    if not matched:
        if conversation.clarification_attempt >= 1:
            await _escalate_human_needed(
                cid, cwid,
                f"Campus clarification reply '{content[:80]}' failed twice — FallBack stub",
            )
            return
        await queries.increment_clarification_attempt(cid)
        await _send_canned(cwid, CANNED_CLARIFY_CAMPUS_NAME)
        return

    await queries.set_conversation_pending_parent(cid, None)
    await queries.reset_clarification_attempt(cid)
    await _handle_post_match(conversation, cwid, matched.university_id)


async def _handle_awaiting_gender(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id

    if GENDER_FEMALE.search(content):
        gender = "female"
    elif GENDER_MALE.search(content):
        gender = "male"
    else:
        await _escalate_human_needed(cid, cwid, "Gender reply did not match known keywords")
        return

    await queries.set_conversation_gender(cid, gender)

    fresh = await queries.get_conversation_by_chatwoot_id(conversation.chatwoot_conversation_id)
    if not fresh or not fresh.university_id or not fresh.gender:
        await _escalate_human_needed(
            cid, cwid,
            "Custom attribute write failed, retried to parse but failed; aborted after retry. FallBack call.",
            internal_class="attr_write_failed",
            status_code="500",
        )
        return

    advanced = await queries.update_conversation_state(
        cid, "recengine_running", conversation.flow_state
    )
    if not advanced:
        return

    from app.background.rec_engine_ladder import fire_rec_engine
    idempotency_key = uuid.uuid4()
    asyncio.create_task(fire_rec_engine(cid, cwid, idempotency_key))


async def _handle_post_completion(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id
    all_hotels = await queries.get_all_hotels()
    hotel = match_hotel_by_ngram(content, all_hotels)
    if hotel is not None:
        await _fire_hotel_path(conversation, cwid, hotel.id)
        return
    await _escalate_human_needed(
        cid, cwid,
        "Post-completion message did not name a specific hotel — deferred to human",
    )
