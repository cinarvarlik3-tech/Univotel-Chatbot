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
from app.db.models import ChatbotLog, Conversation, DivergenceAction, RoutingDecision
from app.diagnostics.trace import trace_event_async
from app.layers.matching import (
    MatchConfidence,
    is_near_miss_university,
    is_question_form,
    match_campus,
    match_hotel_by_ngram,
    match_out_of_city,
    match_university,
    scan_entities_by_ngram,
    word_count_after_normalize,
)
from app.layers.phrase_gate import PhraseGateAction, evaluate_phrase_gate
from app.layers.divergence_classifier import Intent
from app.background.send_retry import send_with_retry

logger = logging.getLogger(__name__)

# Pause between consecutive outbound schema messages (Chatwoot rate limits).
_INTER_MESSAGE_DELAY_SECONDS = 1.5

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


async def _send_canned_by_id(chatwoot_id: int, canned_id: Optional[uuid.UUID]) -> bool:
    """Send a canned response looked up by divergence routing FK."""
    if not canned_id:
        logger.fatal("InfoGatherer: divergence canned_response_id is null")
        return False
    cr = await queries.get_canned_response_by_id(canned_id)
    if not cr:
        logger.fatal("InfoGatherer: canned response id=%s not found in DB", canned_id)
        return False
    result = await send_with_retry(chatwoot_id, cr.content)
    return result.ok


async def _send_hotel_responses(
    conversation_id: uuid.UUID,
    chatwoot_id: int,
    hotel_id: uuid.UUID,
) -> bool:
    """Send all schema lines for one hotel (sentinel / legacy single-id paths)."""
    if queries.is_recengine_sentinel_hotel_id(hotel_id):
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
            await asyncio.sleep(_INTER_MESSAGE_DELAY_SECONDS)
        return True

    sent = await _send_all_eligible_hotel_responses(
        conversation_id, chatwoot_id, [hotel_id], escalate_if_none_sent=True,
    )
    return sent > 0


async def _send_all_eligible_hotel_responses(
    conversation_id: uuid.UUID,
    chatwoot_id: int,
    hotel_ids: list[uuid.UUID],
    *,
    escalate_if_none_sent: bool,
) -> int:
    """
    Send response_schemas for each eligible hotel in order.
    Lenient: skip hotels with no schemas; retry failed sends once after the first pass.
    Returns the number of messages successfully delivered.
    """
    real_ids = [
        hid for hid in hotel_ids
        if not queries.is_recengine_sentinel_hotel_id(hid)
    ]
    failures: list[tuple[uuid.UUID, str]] = []
    sent_count = 0

    async def _attempt(content: str) -> bool:
        result = await send_with_retry(chatwoot_id, content)
        return result.ok

    async def _send_content(hotel_id: uuid.UUID, content: str, track_failures: bool) -> None:
        nonlocal sent_count
        if await _attempt(content):
            sent_count += 1
            await asyncio.sleep(_INTER_MESSAGE_DELAY_SECONDS)
        elif track_failures:
            failures.append((hotel_id, content))

    for hotel_id in real_ids:
        contents = await queries.get_canned_responses_for_hotel(hotel_id)
        if not contents:
            logger.warning(
                "InfoGatherer: no response_schemas for hotel_id=%s (conversation=%s) — skipping",
                hotel_id, conversation_id,
            )
            continue
        for content in contents:
            await _send_content(hotel_id, content, track_failures=True)

    for hotel_id, content in failures:
        if await _attempt(content):
            sent_count += 1
            await asyncio.sleep(_INTER_MESSAGE_DELAY_SECONDS)
        else:
            logger.error(
                "InfoGatherer: permanent send failure hotel_id=%s conversation=%s",
                hotel_id, conversation_id,
            )

    if sent_count == 0 and escalate_if_none_sent:
        logger.fatal(
            "InfoGatherer: zero schema messages sent for conversation=%s hotels=%s",
            conversation_id, real_ids,
        )
        await queries.write_log(ChatbotLog(
            conversation_id=conversation_id,
            operation_layer=LAYER,
            which_run="outputRun",
            log_level="fatal",
            is_success=False,
            status_code="404",
            explanation="No response schema messages could be sent for eligible hotels",
        ))
        await queries.set_conversation_human_needed(conversation_id)
        await _write_human_needed_label(chatwoot_id)
    elif failures:
        logger.warning(
            "InfoGatherer: partial schema delivery conversation=%s sent=%d hotels=%s",
            conversation_id, sent_count, real_ids,
        )

    return sent_count


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


async def _log_divergence_turn(
    conversation_id: uuid.UUID,
    intent: str,
    action: str,
    repeat_count: int,
    flow_state: str,
) -> None:
    """Observability for divergence classifier + router (Suite D)."""
    await queries.write_log(ChatbotLog(
        conversation_id=conversation_id,
        operation_layer=LAYER,
        which_run="contextRun",
        log_level="info",
        is_success=True,
        internal_class=f"divergence:{intent}",
        explanation=(
            f"Divergence turn: intent={intent} action={action} "
            f"repeat={repeat_count} flow_state={flow_state}"
        ),
    ))


async def _fire_rec_engine_if_ready(conversation: Conversation, cwid: int) -> None:
    """Start RecEngine when both university and gender slots are filled."""
    cid = conversation.id
    if conversation.flow_state in ("recengine_running", "completed", "human_needed", "stopped"):
        return
    if not conversation.university_id or not conversation.gender:
        return

    advanced = await queries.update_conversation_state(
        cid, "recengine_running", conversation.flow_state
    )
    if not advanced:
        return

    from app.background.rec_engine_ladder import fire_rec_engine
    asyncio.create_task(fire_rec_engine(cid, cwid, uuid.uuid4()))


async def _run_deterministic_extraction(
    conversation: Conversation,
    cwid: int,
    content: str,
    flow_state: str,
) -> str:
    """
    Spec 020 Part A Steps 1–3: gender → entity (n-gram/campus/ooc) → advance.
    Returns 'progress' when handled, 'clarify' after a clarify prompt, 'none' → divergence.
    """
    cid = conversation.id
    conv = conversation
    gender_filled = False
    entity_filled = False

    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    all_ooc = await queries.get_all_out_of_city_universities()

    if not conv.gender:
        gender = _extract_gender(content)
        if gender:
            await queries.set_conversation_gender(cid, gender)
            gender_filled = True
            fresh = await queries.get_conversation_by_id(cid)
            if fresh:
                conv = fresh

    if flow_state == "awaiting_campus_clarification" and conv.pending_parent_university_id:
        parent_id = conv.pending_parent_university_id
        campuses = await queries.get_campuses_for_parent(parent_id)
        matched = match_campus(content, parent_id, campuses, all_aliases)
        if matched:
            await queries.set_conversation_pending_parent(cid, None)
            await queries.reset_clarification_attempt(cid)
            await _handle_post_match(conv, cwid, matched.university_id)
            await queries.reset_divergence_persistence(cid)
            return "progress"
        if conv.clarification_attempt >= 1:
            return "none"
        await queries.increment_clarification_attempt(cid)
        await _send_canned(cwid, CANNED_CLARIFY_CAMPUS_NAME)
        return "clarify"

    if not conv.university_id:
        # Question-shaped replies skip university entity acceptance (gender still extracted above).
        if not is_question_form(content):
            result = scan_entities_by_ngram(content, all_unis, all_aliases)
            if result.confidence == MatchConfidence.AMBIGUOUS:
                advanced = await queries.update_conversation_state(
                    cid, "awaiting_university_clarification", conv.flow_state
                )
                if advanced:
                    await _send_canned(cwid, CANNED_CLARIFY)
                await queries.reset_divergence_persistence(cid)
                return "progress"

            if result.parent_university_id:
                if await _handle_parent_match(
                    conv, cwid, result.parent_university_id, content=content
                ):
                    await queries.reset_divergence_persistence(cid)
                    return "progress"

            if result.university_id:
                if await _route_university_match(conv, cwid, result):
                    entity_filled = True
                    fresh = await queries.get_conversation_by_id(cid)
                    if fresh:
                        conv = fresh

            if not entity_filled and result.confidence == MatchConfidence.NONE:
                if flow_state in ("new", "awaiting_university", "awaiting_university_clarification"):
                    if match_out_of_city(content, all_ooc):
                        await _fire_out_of_city(conv, cwid)
                        await queries.reset_divergence_persistence(cid)
                        return "progress"

                # No deterministic match. Everything (short, question-shaped, typo'd) goes to
                # divergence. Near-miss typo detection re-enters as a fallback inside
                # _run_divergence_recovery (Fix 1.2), never here.
                return "none"

    if gender_filled or entity_filled:
        await queries.reset_divergence_persistence(cid)
        fresh = await queries.get_conversation_by_id(cid)
        if fresh:
            conv = fresh
        if gender_filled and flow_state == "awaiting_gender":
            if not conv.university_id or not conv.gender:
                await _escalate_human_needed(
                    cid, cwid,
                    "Gender set but university missing after gender slot reply",
                    internal_class="attr_write_failed",
                    status_code="500",
                )
                return "progress"
        if conv.university_id and conv.gender:
            await _fire_rec_engine_if_ready(conv, cwid)
        return "progress"

    return "none"


async def _try_extract_slots_and_advance(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> bool:
    """Backward-compatible wrapper for divergence Layer 0 (spec §7)."""
    result = await _run_deterministic_extraction(
        conversation, cwid, content, conversation.flow_state
    )
    return result != "none"


async def _process_pre_recengine_turn(
    conversation: Conversation,
    cwid: int,
    content: str,
    *,
    flow_state: str,
    fallback: str,
    if_empty: str = "divergence",
) -> None:
    """
    Spec 020 Part A uniform block: hotel interrupt → deterministic extraction → divergence.
    if_empty: 'divergence' (default) or 'activate' (send earliest slot question).
    """
    all_hotels = await queries.get_all_hotels()
    hotel = match_hotel_by_ngram(content, all_hotels)
    if hotel is not None:
        await _fire_hotel_path(conversation, cwid, hotel.id)
        return

    extraction = await _run_deterministic_extraction(
        conversation, cwid, content, flow_state
    )
    if extraction != "none":
        return

    if if_empty == "activate":
        await _activate_flow(conversation, cwid, flow_state)
        return

    await _run_divergence_recovery(
        conversation, cwid, content,
        flow_state=flow_state, fallback=fallback,
    )


async def _activate_flow(
    conversation: Conversation,
    cwid: int,
    flow_state: str,
) -> None:
    """Send the standard slot question for the earliest empty slot."""
    cid = conversation.id

    if flow_state == "new":
        advanced = await queries.update_conversation_state(
            cid, "awaiting_university", conversation.flow_state
        )
        if advanced:
            if not await queries.has_automation_outbound(cid):
                await _send_canned(cwid, CANNED_HANGI)
        return

    if flow_state == "awaiting_university":
        await _send_canned(cwid, CANNED_HANGI)
        return

    if flow_state == "awaiting_gender":
        await _send_canned(cwid, CANNED_KIZ_ERKEK)
        return

    if flow_state == "awaiting_university_clarification":
        await _send_canned(cwid, CANNED_CLARIFY_UNI_NAME)
        return

    if flow_state == "awaiting_campus_clarification":
        parent_id = conversation.pending_parent_university_id
        if parent_id:
            question = await _build_campus_question(parent_id)
            if question:
                await send_with_retry(cwid, question)


async def _execute_divergence_decision(
    conversation: Conversation,
    cwid: int,
    decision: RoutingDecision,
    flow_state: str,
    repeat_count: int,
) -> None:
    """Perform the router action: canned send, activate, ignore, or escalate."""
    cid = conversation.id
    action = decision.action

    if action == DivergenceAction.IGNORE:
        return

    if action == DivergenceAction.ESCALATE:
        await _escalate_human_needed(
            cid, cwid,
            "Divergence routing escalate (missing row or persistence cap)",
            internal_class="divergence_unhandled",
        )
        return

    if action == DivergenceAction.ACTIVATE_FLOW:
        await _activate_flow(conversation, cwid, flow_state)
        return

    if action == DivergenceAction.ANSWER_AND_REANCHOR:
        canned_id = (
            decision.canned_response_id if repeat_count <= 1
            else decision.canned_response_alt_id
        )
        await _send_canned_by_id(cwid, canned_id)
        if flow_state == "new":
            await queries.update_conversation_state(
                cid, "awaiting_university", conversation.flow_state
            )
        return


async def _run_divergence_recovery(
    conversation: Conversation,
    cwid: int,
    content: str,
    *,
    flow_state: str,
    fallback: str,
) -> None:
    """
    Layer 0–3 divergence pipeline: slot extraction → classify → route → execute.
    fallback: 'ignore' (new state) or 'escalate_off_script' (mid-flow).
    """
    from app.layers.divergence_classifier import classify
    from app.layers.divergence_router import route

    cid = conversation.id

    classification = await classify(content)
    if classification.llm_failed:
        if fallback == "ignore":
            await _log_phrase_gate_ignore(cid, "divergence_classifier_failed")
            return
        await _escalate_human_needed(
            cid, cwid,
            f"Divergence classifier failed for '{content[:80]}'",
            internal_class="off_script_no_answer",
        )
        return

    intent = classification.intent

    # Near-miss fallback (Fix 1.2): LLM found no real inquiry, but the message
    # looks like a typo'd university name and the pending slot is university.
    # Deterministic, DB-grounded; the LLM never names a university.
    if (
        intent in (Intent.NO_INTENT, Intent.COMPLEX)
        and flow_state in ("awaiting_university", "awaiting_university_clarification")
    ):
        all_unis = await queries.get_all_universities()
        if is_near_miss_university(content, all_unis):
            await _handle_university_no_match(conversation, cwid, content)
            return

    if conversation.last_divergence_intent == intent.value:
        repeat_count = conversation.divergence_repeat_count + 1
    else:
        repeat_count = 1
    await queries.update_divergence_persistence(cid, intent.value, repeat_count)

    decision = await route(intent, flow_state)
    action = decision.action
    if repeat_count >= 3 and action == DivergenceAction.ANSWER_AND_REANCHOR:
        decision = RoutingDecision(action=DivergenceAction.ESCALATE)

    await _log_divergence_turn(
        cid, intent.value, decision.action.value, repeat_count, flow_state
    )
    await _execute_divergence_decision(
        conversation, cwid, decision, flow_state, repeat_count
    )


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
    fresh = await queries.get_conversation_by_id(cid)
    if fresh and fresh.gender:
        await _fire_rec_engine_if_ready(fresh, cwid)
        return

    advanced = await queries.update_conversation_state(cid, "awaiting_gender", conversation.flow_state)
    if not advanced:
        return
    await _send_canned(cwid, CANNED_KIZ_ERKEK)


async def _handle_parent_match(
    conversation: Conversation,
    cwid: int,
    parent_university_id: uuid.UUID,
    *,
    content: Optional[str] = None,
) -> bool:
    """Resolve parent uni; campus from same message when present. Returns True if handled."""
    cid = conversation.id
    await queries.reset_clarification_attempt(cid)
    campuses = await queries.get_campuses_for_parent(parent_university_id)
    all_aliases = await queries.get_all_university_aliases()

    if len(campuses) == 1:
        await _handle_post_match(conversation, cwid, campuses[0].university_id)
        return True

    if not campuses:
        await _escalate_human_needed(
            cid, cwid,
            f"Parent university {parent_university_id} has no campus rows — cannot escalate",
        )
        return True

    if content:
        matched = match_campus(content, parent_university_id, campuses, all_aliases)
        if matched:
            await _handle_post_match(conversation, cwid, matched.university_id)
            return True

    question = await _build_campus_question(parent_university_id)
    if not question:
        await _escalate_human_needed(
            cid, cwid,
            f"Failed to build campus question for parent {parent_university_id}",
        )
        return True

    advanced = await queries.update_conversation_state(
        cid, "awaiting_campus_clarification", conversation.flow_state
    )
    if not advanced:
        return True
    await queries.set_conversation_pending_parent(cid, parent_university_id)
    result = await send_with_retry(cwid, question)
    if not result.ok:
        logger.error(
            "InfoGatherer: failed to send campus escalation question for conversation %s", cid
        )
    return True


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
        await trace_event_async(
            "infoGatherer",
            "terminal_no_action",
            level="warn",
            chatwoot_conversation_id=cwid,
            conversation_id=cid,
            flow_state=state,
        )
        return

    if not conversation.bot_enabled:
        logger.info("InfoGatherer: conversation %s bot_enabled=false — no action", cid)
        await trace_event_async(
            "infoGatherer",
            "bot_disabled",
            level="warn",
            chatwoot_conversation_id=cwid,
            conversation_id=cid,
            abstain_reason=conversation.infogatherer_abstain_reason,
        )
        return

    if not content:
        logger.info("InfoGatherer: empty message in conversation %s — keeping state", cid)
        return

    if state in (
        "awaiting_campus_clarification",
        "awaiting_gender",
        "awaiting_university_clarification",
        "awaiting_university",
    ):
        await _process_pre_recengine_turn(
            conversation, cwid, content,
            flow_state=state,
            fallback="escalate_off_script",
        )
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

    if gate.action == PhraseGateAction.HOTEL_PATH and gate.matched_hotel is not None:
        await _fire_hotel_path(conversation, cwid, gate.matched_hotel.id)
        return

    if_empty = "divergence" if gate.action == PhraseGateAction.IGNORE else "activate"
    await _process_pre_recengine_turn(
        conversation, cwid, content,
        flow_state="new",
        fallback="ignore",
        if_empty=if_empty,
    )


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
    await _process_pre_recengine_turn(
        conversation, cwid, content,
        flow_state="awaiting_university",
        fallback="escalate_off_script",
    )


async def _handle_clarification(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    await _process_pre_recengine_turn(
        conversation, cwid, content,
        flow_state="awaiting_university_clarification",
        fallback="escalate_off_script",
    )


async def _handle_awaiting_campus_clarification(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    parent_id = conversation.pending_parent_university_id
    if not parent_id:
        await _escalate_human_needed(
            conversation.id, cwid,
            "awaiting_campus_clarification with no pending_parent_university_id — data inconsistency",
            internal_class="missing_pending_parent",
        )
        return

    campuses = await queries.get_campuses_for_parent(parent_id)
    if not campuses:
        await _escalate_human_needed(
            conversation.id, cwid,
            f"No campus rows for pending parent {parent_id}",
        )
        return

    await _process_pre_recengine_turn(
        conversation, cwid, content,
        flow_state="awaiting_campus_clarification",
        fallback="escalate_off_script",
    )


async def _handle_awaiting_gender(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    await _process_pre_recengine_turn(
        conversation, cwid, content,
        flow_state="awaiting_gender",
        fallback="escalate_off_script",
    )


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
