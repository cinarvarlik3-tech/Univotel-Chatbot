"""
POST /webhooks/chatwoot — inbound Chatwoot webhook handler.

Handles two event types:
- message_created: inbound messages for InfoGatherer dispatch.
- conversation_updated: label/attribute sync, feedback-loop guard, manual 'tag' trigger.

Contract (§4.1, §6.1):
- HMAC verified before any parsing; mismatch → 401.
- Always returns 200 immediately after cheap bookkeeping.
- All real work runs in a detached background task.
"""
import logging
import re
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import queries
from app.security import verify_chatwoot_hmac

logger = logging.getLogger(__name__)

router = APIRouter()

from app.config import TESTING_PHONE_ALLOWLIST as _TESTING_ALLOWLIST

_NON_DIGIT = re.compile(r"\D")

# In-memory self-write record for the feedback-loop guard fallback (§6.5).
# Maps chatwoot_conversation_id → UTC timestamp of last bot write.
# Used when the conversation_updated payload does not include the acting agent.
_recent_self_writes: dict[int, datetime] = {}
_SELF_WRITE_TTL_SECONDS = 30


@dataclass
class _DebounceState:
    """Buffered inbound fragments coalesced into one InfoGatherer turn (Spec 020 Part E)."""
    conversation_id: Any
    parts: list[str] = field(default_factory=list)
    task: asyncio.Task | None = None
    last_message_id: int | None = None


_debounce_buffers: dict[int, _DebounceState] = {}


def _cancel_debounce(chatwoot_conversation_id: int) -> None:
    """Discard a pending debounce buffer (human takeover or terminal flush)."""
    state = _debounce_buffers.pop(chatwoot_conversation_id, None)
    if state and state.task and not state.task.done():
        state.task.cancel()


async def _flush_debounce(chatwoot_conversation_id: int) -> None:
    """Process coalesced inbound content after the debounce window expires."""
    state = _debounce_buffers.pop(chatwoot_conversation_id, None)
    if not state or not state.parts:
        return
    combined = "\n".join(state.parts)
    await _process_inbound(
        conversation_id=state.conversation_id,
        chatwoot_conversation_id=chatwoot_conversation_id,
        content=combined,
        chatwoot_message_id=state.last_message_id,
    )


async def _enqueue_debounced_inbound(
    conversation_id,
    chatwoot_conversation_id: int,
    content: str,
    chatwoot_message_id: int | None = None,
) -> None:
    """Append to per-conversation buffer and (re)start debounce timer."""
    window = settings.debounce_window_seconds
    if window <= 0:
        await _process_inbound(
            conversation_id, chatwoot_conversation_id, content, chatwoot_message_id
        )
        return

    state = _debounce_buffers.get(chatwoot_conversation_id)
    if state is None:
        state = _DebounceState(conversation_id=conversation_id)
        _debounce_buffers[chatwoot_conversation_id] = state

    state.parts.append(content)
    state.last_message_id = chatwoot_message_id

    if state.task and not state.task.done():
        state.task.cancel()

    async def _timer() -> None:
        try:
            await asyncio.sleep(window)
            await _flush_debounce(chatwoot_conversation_id)
        except asyncio.CancelledError:
            return

    state.task = asyncio.create_task(_timer())


def _normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    return _NON_DIGIT.sub("", raw)


def _is_allowed(payload: dict) -> bool:
    if not settings.testing_limitations_mode:
        return True

    candidates: list[str | None] = [
        (payload.get("contact") or {}).get("phone_number"),
        (((payload.get("conversation") or {}).get("meta") or {}).get("sender") or {}).get("phone_number"),
    ]

    for raw in candidates:
        if _normalize_phone(raw) in _TESTING_ALLOWLIST:
            return True

    return False


def record_self_write(chatwoot_conversation_id: int) -> None:
    """
    Called by the Router before each Chatwoot write.
    Used as the fallback in the feedback-loop guard when the webhook payload lacks author info.
    """
    _recent_self_writes[chatwoot_conversation_id] = datetime.now(tz=timezone.utc)


def _is_recent_self_write(chatwoot_conversation_id: int) -> bool:
    ts = _recent_self_writes.get(chatwoot_conversation_id)
    if ts is None:
        return False
    age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
    if age > _SELF_WRITE_TTL_SECONDS:
        _recent_self_writes.pop(chatwoot_conversation_id, None)
        return False
    return True


def _is_bot_authored(payload: dict) -> bool:
    """
    Feedback-loop guard (§6.5).
    Primary: check if the acting agent is the ChatBot agent.
    Fallback: check the in-memory self-write record.
    """
    # Primary: acting agent from the payload
    agent = (
        (payload.get("current_conversation") or {}).get("meta", {}).get("assignee")
        or payload.get("meta", {}).get("assignee")
        or {}
    )
    agent_id = agent.get("id")
    if agent_id is not None:
        return str(agent_id) == str(settings.chatwoot_bot_agent_id)

    # Fallback: self-write timestamp record
    conv_id = None
    try:
        conv_id = int(
            (payload.get("current_conversation") or {}).get("id")
            or payload.get("id")
        )
    except (TypeError, ValueError):
        pass

    if conv_id is not None:
        return _is_recent_self_write(conv_id)

    return False


@router.post("/webhooks/chatwoot")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.info("WEBHOOK: received request, verifying HMAC")
    await verify_chatwoot_hmac(request)
    logger.info("WEBHOOK: HMAC OK")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        logger.fatal("WEBHOOK: malformed JSON — dropping request")
        return JSONResponse(status_code=200, content={"status": "dropped_malformed"})

    event = payload.get("event", "")
    _mp = payload.get("message") or payload
    logger.info(
        "WEBHOOK: event=%r private=%r message_type=%r content=%r conv=%r",
        event,
        bool(_mp.get("private", False)),
        _mp.get("message_type"),
        (_mp.get("content") or "")[:40],
        (payload.get("conversation") or {}).get("id"),
    )

    if not _is_allowed(payload):
        logger.info("WEBHOOK: TESTING_MODE — contact not on allowlist, ignoring (status=ignored)")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    if event == "conversation_updated":
        logger.info("WEBHOOK: dispatching conversation_updated to background task")
        background_tasks.add_task(_process_conversation_updated, payload)
        return JSONResponse(status_code=200, content={"status": "ok"})

    # message_created (and any unrecognised event — fall through to existing logic)
    chatwoot_conversation_id: int | None = None
    try:
        chatwoot_conversation_id = int(payload["conversation"]["id"])
    except (KeyError, TypeError, ValueError):
        logger.fatal("WEBHOOK: cannot extract chatwoot_conversation_id — dropping")
        return JSONResponse(status_code=200, content={"status": "dropped_no_conversation_id"})

    message_payload = payload.get("message") or payload
    chatwoot_message_id: int | None = message_payload.get("id")
    content: str | None = message_payload.get("content")
    is_private: bool = bool(message_payload.get("private", False))
    sender = message_payload.get("sender") or {}
    sender_id: str | None = str(sender.get("id")) if sender.get("id") else None
    sender_name: str | None = sender.get("name")

    mtype_raw = message_payload.get("message_type", "")
    if mtype_raw in (0, "incoming", "inbound"):
        our_message_type = "inbound"
    elif mtype_raw in (1, "outgoing", "outbound"):
        our_message_type = "outbound"
    else:
        our_message_type = "inbound"

    if chatwoot_message_id and await queries.message_exists(chatwoot_message_id):
        logger.info("WEBHOOK: duplicate message_id=%s — no-op", chatwoot_message_id)
        return JSONResponse(status_code=200, content={"status": "duplicate"})

    raw_phone = (
        (payload.get("contact") or {}).get("phone_number")
        or (((payload.get("conversation") or {}).get("meta") or {}).get("sender") or {}).get("phone_number")
    )
    contact_phone = _normalize_phone(raw_phone) or None
    logger.info("WEBHOOK: upserting conversation cw_id=%s phone=%r", chatwoot_conversation_id, contact_phone)
    conversation = await queries.upsert_conversation(chatwoot_conversation_id, contact_phone)
    logger.info("WEBHOOK: conversation upserted id=%s", conversation.id)

    # Capture 'tag' private note → manual trigger (bypasses the 5-message gate)
    if is_private and content and content.strip().lower() == "tag":
        logger.info("WEBHOOK: 'tag' manual trigger detected for conversation %s", conversation.id)
        if chatwoot_message_id:
            await queries.insert_message(
                conversation.id, chatwoot_message_id, content,
                "inbound", "user", sender_id, sender_name, is_private=True,
            )
        background_tasks.add_task(
                _process_manual_tag_trigger,
                conversation_id=conversation.id,
                chatwoot_conversation_id=chatwoot_conversation_id,
            )
        logger.info("WEBHOOK: 'tag' trigger enqueued as background task, returning 200")
        return JSONResponse(status_code=200, content={"status": "ok"})

    if our_message_type == "outbound":
        is_bot = sender_id and str(sender_id) == str(settings.chatwoot_bot_agent_id)
        if not is_bot:
            logger.info(
                "WEBHOOK: human agent takeover on conversation %s (sender_id=%s)",
                conversation.id, sender_id,
            )
            await queries.set_conversation_stopped(conversation.id)
            _cancel_debounce(chatwoot_conversation_id)
            sender_type_val = "user"
            if chatwoot_message_id and not await queries.conversation_has_messages(conversation.id):
                await queries.set_conversation_bot_enabled(conversation.id, False)
        else:
            sender_type_val = "infoGatherer"

        if chatwoot_message_id:
            await queries.insert_message(
                conversation.id, chatwoot_message_id, content,
                our_message_type, sender_type_val, sender_id, sender_name,
            )
        return JSONResponse(status_code=200, content={"status": "ok"})

    if chatwoot_message_id:
        await queries.insert_message(
            conversation.id, chatwoot_message_id, content,
            "inbound", "contact", sender_id, sender_name, is_private=is_private,
        )

    if not is_private:
        background_tasks.add_task(
            _enqueue_debounced_inbound,
            conversation_id=conversation.id,
            chatwoot_conversation_id=chatwoot_conversation_id,
            content=content or "",
            chatwoot_message_id=chatwoot_message_id,
        )

    return JSONResponse(status_code=200, content={"status": "ok"})


async def _process_inbound(
    conversation_id,
    chatwoot_conversation_id: int,
    content: str,
    chatwoot_message_id: int | None = None,
) -> None:
    from app.layers.info_gatherer import process_message

    conversation = await queries.get_conversation_by_id(conversation_id)
    if not conversation:
        logger.error("WEBHOOK bg: conversation %s not found after upsert", conversation_id)
        return

    try:
        await process_message(
            conversation,
            chatwoot_conversation_id,
            content,
            chatwoot_message_id=chatwoot_message_id,
        )
    except Exception as exc:
        logger.error(
            "WEBHOOK bg: unhandled error in process_message for conversation %s: %s",
            conversation_id, exc,
        )


async def _process_conversation_updated(payload: dict) -> None:
    """
    Sync labels and custom attributes into the DB replica.
    Applies the feedback-loop guard: bot-authored updates are ignored for triggering.
    Also captures the 'tag' label as a manual trigger.
    """
    if _is_bot_authored(payload):
        logger.debug("WEBHOOK: conversation_updated from bot — skipping (feedback-loop guard)")
        return

    conv_data = payload.get("current_conversation") or payload
    chatwoot_conv_id = None
    try:
        chatwoot_conv_id = int(conv_data.get("id") or payload.get("id"))
    except (TypeError, ValueError):
        logger.error("WEBHOOK conversation_updated: cannot extract conversation id")
        return

    conversation = await queries.get_conversation_by_chatwoot_id(chatwoot_conv_id)
    if not conversation:
        logger.info(
            "WEBHOOK conversation_updated: unknown conversation %d — no-op", chatwoot_conv_id
        )
        return

    # Extract updated label set
    labels: list[str] | None = conv_data.get("labels")

    # Extract updated custom attributes
    attrs = conv_data.get("custom_attributes") or {}

    ilgili_otel = attrs.get("ilgili_otel")
    tasinma_tarihi_raw = attrs.get("tasinma_tarihi")
    kayip_nedeni = attrs.get("kayip_nedeni")
    oda_tiipi = attrs.get("oda_tiipi")
    butce = attrs.get("butce")
    university_raw = attrs.get("university")
    ogrenci_cinsiyet_raw = attrs.get("ogrenci_cinsiyet")

    # Human removed info-check (spec 018)
    prior_labels = conversation.labels or []
    if labels is not None and "info-check" in prior_labels and "info-check" not in labels:
        await queries.set_info_check_suppressed_from_dismiss(
            conversation.id,
            conversation.info_check_fingerprint,
        )

    # Parse date if string
    from datetime import date
    tasinma_tarihi = None
    if isinstance(tasinma_tarihi_raw, str):
        try:
            tasinma_tarihi = date.fromisoformat(tasinma_tarihi_raw)
        except ValueError:
            pass
    elif isinstance(tasinma_tarihi_raw, date):
        tasinma_tarihi = tasinma_tarihi_raw

    now = datetime.now(tz=timezone.utc)

    # ilgili_otel companions: human/CRM edits arrive here — update atomically (§6.7)
    ilgili_otel_set_at = None
    ilgili_otel_set_by = None
    if ilgili_otel is not None and ilgili_otel != conversation.ilgili_otel:
        ilgili_otel_set_at = now
        ilgili_otel_set_by = "human"

    university_id = None
    university_set_at = None
    university_set_by = None
    if "university" in attrs:
        if isinstance(university_raw, str) and university_raw.strip():
            mapped = await queries.get_university_id_for_chatwoot_list_value(university_raw.strip())
            if mapped:
                university_id = mapped
                university_set_at = now
                university_set_by = "human"
            else:
                logger.warning(
                    "WEBHOOK: unknown Chatwoot university value %r — skipping FK update",
                    university_raw,
                )

    gender_key_present = "ogrenci_cinsiyet" in attrs
    if gender_key_present:
        from app.tagassigner.attribute_helpers import gender_display_to_enum
        try:
            gender_val = gender_display_to_enum(ogrenci_cinsiyet_raw or "Bilinmiyor")
        except ValueError:
            logger.warning(
                "WEBHOOK: unknown ogrenci_cinsiyet value %r — skipping",
                ogrenci_cinsiyet_raw,
            )
            gender_key_present = False
            gender_val = None
    else:
        gender_val = None

    oda_tiipi_set_at = None
    oda_tiipi_set_by = None
    if oda_tiipi is not None and oda_tiipi != conversation.oda_tiipi:
        oda_tiipi_set_at = now
        oda_tiipi_set_by = "human"

    await queries.sync_conversation_labels_and_attributes(
        conversation_id=conversation.id,
        labels=labels,
        ilgili_otel=ilgili_otel,
        ilgili_otel_set_at=ilgili_otel_set_at or conversation.ilgili_otel_set_at,
        ilgili_otel_set_by=ilgili_otel_set_by or conversation.ilgili_otel_set_by,
        tasinma_tarihi=tasinma_tarihi,
        kayip_nedeni=kayip_nedeni,
        oda_tiipi=oda_tiipi,
        butce=butce,
        university_id=university_id,
        gender=None,
        university_set_at=university_set_at,
        university_set_by=university_set_by,
        gender_set_at=None,
        gender_set_by=None,
        oda_tiipi_set_at=oda_tiipi_set_at,
        oda_tiipi_set_by=oda_tiipi_set_by,
    )

    if gender_key_present:
        await queries.set_conversation_gender_human(conversation.id, gender_val)

    # 'tag' label → manual trigger (TagAssigner removes it during the run)
    if labels and "tag" in labels:
        await _process_manual_tag_trigger(
            conversation_id=conversation.id,
            chatwoot_conversation_id=chatwoot_conv_id,
        )


async def _process_manual_tag_trigger(
    conversation_id,
    chatwoot_conversation_id: int,
) -> None:
    """
    Manual 'tag' trigger: bypasses the 5-message gate, draws from manual_run_count cap.
    Rejected as redundant if a run is already processing for this conversation.
    """
    conversation = await queries.get_conversation_by_id(conversation_id)
    if not conversation:
        return

    if conversation.manual_run_count >= 5:
        logger.info(
            "WEBHOOK: manual tag trigger rejected — daily cap reached for conversation %s",
            conversation_id,
        )
        return

    if await queries.has_processing_run(conversation_id):
        logger.info(
            "WEBHOOK: manual tag trigger rejected — run already processing for conversation %s",
            conversation_id,
        )
        return

    enqueued = await queries.enqueue_tagassigner_run(conversation_id, "manual")
    if enqueued:
        await queries.increment_manual_run_count(conversation_id)
        logger.info("WEBHOOK: manual tag trigger enqueued for conversation %s", conversation_id)
