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
from app.layers.matching import MatchConfidence, match_university
from app.background.send_retry import send_with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PHRASE_GATE = [
    "Üniversitem:",
    "Merhaba!",
    "My University:",
    "Hello!",
    "Başvuru Kodu:",
]

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

LAYER = "infoGatherer"

# Turkish vowel → question particle for vowel harmony (last-vowel rule)
_VOWEL_SUFFIX: dict[str, str] = {
    'a': 'mı', 'A': 'mı', 'ı': 'mı', 'I': 'mı',
    'e': 'mi', 'E': 'mi', 'i': 'mi', 'İ': 'mi',
    'o': 'mu', 'O': 'mu', 'u': 'mu', 'U': 'mu',
    'ö': 'mü', 'Ö': 'mü', 'ü': 'mü', 'Ü': 'mü',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        return False

    for content in contents:
        result = await send_with_retry(chatwoot_id, content)
        if not result.ok:
            logger.error(
                "InfoGatherer: failed to send canned response for hotel_id=%s", hotel_id
            )
            return False
    return True


async def _escalate_human_needed(
    conversation_id: uuid.UUID,
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


def _turkish_question_suffix(word: str) -> str:
    """Return the vowel-harmonised question particle (mı/mi/mu/mü) for a Turkish word."""
    for ch in reversed(word):
        if ch in _VOWEL_SUFFIX:
            return _VOWEL_SUFFIX[ch]
    return "mı"  # fallback for words with no recognisable vowel


async def _build_campus_question(parent_id: uuid.UUID) -> Optional[str]:
    """
    Assemble the parent university's escalation question with live campus options.
    Returns None if the parent or its campuses cannot be fetched.
    """
    parent = await queries.get_parent_university_by_id(parent_id)
    if not parent:
        logger.error("InfoGatherer: parent_university_id=%s not found", parent_id)
        return None
    campuses = await queries.get_campuses_for_parent(parent_id)
    if not campuses:
        logger.error("InfoGatherer: no campus rows for parent_university_id=%s", parent_id)
        return None
    parts = [f"{c.campus_label} {_turkish_question_suffix(c.campus_label)}" for c in campuses]
    campuses_str = ", ".join(parts)
    return parent.question.format(name=parent.name, campuses=campuses_str)


async def _write_deal_awaiting_label(chatwoot_id: int) -> None:
    """
    Push the 'deal_awaiting' label to Chatwoot.
    Reads current labels first, adds 'deal_awaiting', then writes the full set.
    This is a net-new Chatwoot write path (see V0 Amendment §4 and build brief #2).
    """
    from app.chatwoot_client import get_labels, set_labels
    from app.background.send_retry import SendRetryResult

    current = await get_labels(chatwoot_id)
    if current is None:
        logger.error("InfoGatherer: could not fetch labels for conversation %d — skipping label write", chatwoot_id)
        return
    if "deal_awaiting" not in current:
        result = await set_labels(chatwoot_id, current + ["deal_awaiting"])
        if not result.ok:
            logger.error(
                "InfoGatherer: failed to write deal_awaiting label for conversation %d: %s",
                chatwoot_id, result.error,
            )


async def _handle_post_match(
    conversation: Conversation,
    cwid: int,
    university_id: uuid.UUID,
) -> None:
    """
    Common path after a successful university match.
    Checks deal_awaiting membership; if member → terminal; else → awaiting_gender.
    """
    cid = conversation.id

    if await queries.is_deal_awaiting_university(university_id):
        advanced = await queries.update_conversation_state(cid, "completed", conversation.flow_state)
        if not advanced:
            return
        await queries.set_conversation_university(cid, university_id)
        await _write_deal_awaiting_label(cwid)
        await _send_hotel_responses(cid, cwid, queries.DEAL_AWAITING_STATE_ID)
        return

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
    """
    Alias resolved to a parent university. If the parent has exactly one campus,
    resolve directly. If it has multiple, send the escalation question and park
    the conversation in awaiting_campus_clarification.
    """
    cid = conversation.id
    campuses = await queries.get_campuses_for_parent(parent_university_id)

    if len(campuses) == 1:
        await _handle_post_match(conversation, cwid, campuses[0].university_id)
        return

    if not campuses:
        await _escalate_human_needed(
            cid,
            f"Parent university {parent_university_id} has no campus rows — cannot escalate",
        )
        return

    question = await _build_campus_question(parent_university_id)
    if not question:
        await _escalate_human_needed(
            cid,
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_message(
    conversation: Conversation,
    chatwoot_conversation_id: int,
    message_content: str,
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

    await _handle_new(conversation, cwid, content)


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------

async def _handle_new(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id

    if not any(phrase in content for phrase in PHRASE_GATE):
        logger.info("InfoGatherer: phrase gate failed for conversation %s", cid)
        await _escalate_human_needed(cid, "Phrase gate failed — no matching trigger phrase")
        return

    all_hotels = await queries.get_all_hotels()
    for hotel in all_hotels:
        if hotel.name.lower() in content.lower():
            advanced = await queries.update_conversation_state(cid, "completed", conversation.flow_state)
            if not advanced:
                return
            await _send_hotel_responses(cid, cwid, hotel.id)
            return

    candidate = _extract_university_candidate(content)
    if candidate:
        all_unis = await queries.get_all_universities()
        all_aliases = await queries.get_all_university_aliases()
        result = match_university(candidate, all_unis, all_aliases)

        if result.confidence == MatchConfidence.NONE:
            if UNIVERSITY_KEYWORDS.search(content):
                advanced = await queries.update_conversation_state(cid, "completed", conversation.flow_state)
                if not advanced:
                    return
                await _send_canned(cwid, CANNED_ISTANBUL)
                return

        elif result.confidence == MatchConfidence.AMBIGUOUS:
            advanced = await queries.update_conversation_state(
                cid, "awaiting_university_clarification", conversation.flow_state
            )
            if not advanced:
                return
            await _send_canned(cwid, CANNED_CLARIFY)
            return

        elif result.parent_university_id:
            await _handle_parent_match(conversation, cwid, result.parent_university_id)
            return

        elif result.university_id:
            await _handle_post_match(conversation, cwid, result.university_id)
            return

    advanced = await queries.update_conversation_state(cid, "awaiting_university", conversation.flow_state)
    if not advanced:
        return
    await _send_canned(cwid, CANNED_HANGI)


async def _handle_awaiting_university(
    conversation: Conversation,
    cwid: int,
    content: str,
) -> None:
    cid = conversation.id
    all_unis = await queries.get_all_universities()
    all_aliases = await queries.get_all_university_aliases()
    result = match_university(content, all_unis, all_aliases)

    if result.confidence == MatchConfidence.NONE:
        if UNIVERSITY_KEYWORDS.search(content):
            advanced = await queries.update_conversation_state(cid, "completed", conversation.flow_state)
            if not advanced:
                return
            await _send_canned(cwid, CANNED_ISTANBUL)
            return
        await _escalate_human_needed(cid, "University reply did not match any known university")
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        advanced = await queries.update_conversation_state(
            cid, "awaiting_university_clarification", conversation.flow_state
        )
        if not advanced:
            return
        await _send_canned(cwid, CANNED_CLARIFY)
        return

    if result.parent_university_id:
        await _handle_parent_match(conversation, cwid, result.parent_university_id)
        return

    if result.university_id:
        await _handle_post_match(conversation, cwid, result.university_id)


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
        await _escalate_human_needed(
            cid,
            "University clarification reply still ambiguous or unmatched — one attempt exhausted",
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
    """
    The lead replied to a campus escalation question (e.g. "Maçka mı, Ayazağa mı?").
    Match the reply against the pending parent's campus list.
    """
    from app.layers.matching import normalize

    cid = conversation.id
    parent_id = conversation.pending_parent_university_id
    if not parent_id:
        await _escalate_human_needed(
            cid,
            "awaiting_campus_clarification with no pending_parent_university_id — data inconsistency",
            internal_class="missing_pending_parent",
        )
        return

    campuses = await queries.get_campuses_for_parent(parent_id)
    if not campuses:
        await _escalate_human_needed(
            cid, f"No campus rows for pending parent {parent_id}"
        )
        return

    normalized_reply = normalize(content)
    matched = None
    for campus in campuses:
        if normalize(campus.campus_label) == normalized_reply:
            matched = campus
            break

    if not matched:
        await _escalate_human_needed(
            cid,
            f"Campus clarification reply '{content[:80]}' did not match any campus label — escalating to human",
        )
        return

    await queries.set_conversation_pending_parent(cid, None)
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
        await _escalate_human_needed(cid, "Gender reply did not match known keywords")
        return

    await queries.set_conversation_gender(cid, gender)

    fresh = await queries.get_conversation_by_chatwoot_id(conversation.chatwoot_conversation_id)
    if not fresh or not fresh.university_id or not fresh.gender:
        await _escalate_human_needed(
            cid,
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
    for hotel in all_hotels:
        if hotel.name.lower() in content.lower():
            await _send_hotel_responses(cid, cwid, hotel.id)
            return
    await _escalate_human_needed(
        cid,
        "Post-completion message did not name a specific hotel — deferred to human",
    )
