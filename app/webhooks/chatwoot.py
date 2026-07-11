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

_SWEEP_CHAT_REJECTION_MESSAGE = (
    'You may only use "tag sweepSafe [limit]" or "tag sweepEmpty [limit]" from the chat, '
    "with a maximum limit of 20. Input a numeric limit where the examples say [limit]. "
    "Standart \"tag sweep\" operations and other operations with limit above 20 are guarded "
    "terminal operations, contact your developer if you need them."
)

_SWEEP_OP_CANON: dict[str, str] = {
    "sweep": "sweep",
    "sweepempty": "sweepEmpty",
    "sweepsafe": "sweepSafe",
}
_SWEEP_CHAT_ALLOWED = frozenset({"sweepEmpty", "sweepSafe"})
_SWEEP_CHAT_DEFAULT_LIMIT = 20
_SWEEP_CHAT_MAX_LIMIT = 20


# Grace period (seconds) for burst siblings still stuck in our pipeline when a
# message reaches the buffer having already consumed most of the debounce window.
_MIN_FLUSH_DELAY = 1.0


@dataclass
class _DebounceFragment:
    """A single buffered inbound message awaiting coalescing into one turn."""
    content: str
    chatwoot_message_id: int | None
    sent_at: datetime
    sender_id: str | None = None
    sender_name: str | None = None


@dataclass
class _DebounceState:
    """Buffered inbound fragments coalesced into one InfoGatherer turn (Spec 020 Part E)."""
    chatwoot_conversation_id: int
    contact_phone: str | None = None
    fragments: list[_DebounceFragment] = field(default_factory=list)
    task: asyncio.Task | None = None
    last_sent_at: datetime | None = None


_debounce_buffers: dict[int, _DebounceState] = {}

# Per-conversation processing locks. Serialize turns so a late flush or a
# spaced follow-up message never runs process_message concurrently on stale state.
_processing_locks: dict[int, asyncio.Lock] = {}


def _get_processing_lock(chatwoot_conversation_id: int) -> asyncio.Lock:
    """Return (creating if needed) the processing lock for a conversation."""
    lock = _processing_locks.get(chatwoot_conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _processing_locks[chatwoot_conversation_id] = lock
    return lock


def _coerce_timestamp(raw: Any) -> datetime | None:
    """Best-effort parse of a Chatwoot timestamp into tz-aware UTC; None if unusable."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        seconds = float(raw)
        if seconds > 1e12:  # epoch milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.isdigit():
            return _coerce_timestamp(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _parse_sent_at(message_payload: dict, payload: dict) -> datetime:
    """
    Extract the customer's true send time from a Chatwoot message_created payload.
    Chatwoot exposes the timestamp in a few shapes across versions (message.created_at
    as epoch seconds, an ISO 8601 string, or a top-level created_at). Falls back to
    now(UTC) if absent/unparseable so cadence timing never breaks the request path.
    """
    for raw in (
        message_payload.get("created_at"),
        payload.get("created_at"),
        message_payload.get("timestamp"),
    ):
        parsed = _coerce_timestamp(raw)
        if parsed is not None:
            return parsed
    return datetime.now(tz=timezone.utc)


def _compute_flush_wait(
    sent_at: datetime, window: float, now: datetime | None = None
) -> float:
    """
    Seconds to wait before flushing, measured from the customer's send time.
    Pipeline latency already elapsed counts against the window; the result is
    floored at _MIN_FLUSH_DELAY so late-arriving burst siblings still coalesce.
    """
    now = now or datetime.now(tz=timezone.utc)
    elapsed = (now - sent_at).total_seconds()
    return max(_MIN_FLUSH_DELAY, window - elapsed)


def _cancel_debounce(chatwoot_conversation_id: int) -> None:
    """Discard a pending debounce buffer (human takeover or terminal flush)."""
    state = _debounce_buffers.pop(chatwoot_conversation_id, None)
    if state and state.task and not state.task.done():
        state.task.cancel()


async def _flush_debounce(chatwoot_conversation_id: int) -> None:
    """Process coalesced inbound content after the debounce window expires."""
    state = _debounce_buffers.pop(chatwoot_conversation_id, None)
    if not state or not state.fragments:
        return
    await _process_inbound(
        chatwoot_conversation_id=chatwoot_conversation_id,
        contact_phone=state.contact_phone,
        fragments=list(state.fragments),
    )


async def _enqueue_debounced_inbound(
    chatwoot_conversation_id: int,
    content: str,
    chatwoot_message_id: int | None,
    sent_at: datetime,
    *,
    contact_phone: str | None = None,
    sender_id: str | None = None,
    sender_name: str | None = None,
) -> None:
    """Append to the per-conversation buffer and (re)start a cadence-anchored timer."""
    fragment = _DebounceFragment(
        content=content,
        chatwoot_message_id=chatwoot_message_id,
        sent_at=sent_at,
        sender_id=sender_id,
        sender_name=sender_name,
    )

    window = settings.debounce_window_seconds
    if window <= 0:
        await _process_inbound(
            chatwoot_conversation_id=chatwoot_conversation_id,
            contact_phone=contact_phone,
            fragments=[fragment],
        )
        return

    state = _debounce_buffers.get(chatwoot_conversation_id)
    if state is None:
        state = _DebounceState(chatwoot_conversation_id=chatwoot_conversation_id)
        _debounce_buffers[chatwoot_conversation_id] = state

    if contact_phone:
        state.contact_phone = contact_phone
    state.fragments.append(fragment)
    state.last_sent_at = sent_at

    if state.task and not state.task.done():
        state.task.cancel()

    # Anchor the window to the customer's send time, not our arrival time: time our
    # pipeline already burned counts against the window, so a burst still coalesces
    # when per-message processing is slow. A floor keeps a grace period for late
    # siblings and bounds how quickly we respond after the last message.
    wait = _compute_flush_wait(sent_at, float(window))

    async def _timer() -> None:
        try:
            await asyncio.sleep(wait)
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


async def _is_live_testing_new_conversation_rejected(chatwoot_conversation_id: int) -> bool:
    """
    True when live-testing mode is on, this is a first-seen conversation, and the
    total conversations row count has reached LIVE_TESTING_LIMIT (Spec 022).
    """
    if not settings.live_testing_mode:
        return False
    existing = await queries.get_conversation_by_chatwoot_id(chatwoot_conversation_id)
    if existing is not None:
        return False
    current = await queries.count_live_testing_conversations()
    limit = settings.live_testing_limit
    if limit is not None and current >= limit:
        logger.info(
            "LIVE_TESTING_LIMIT reached (%d); rejecting new conversation %d",
            limit, chatwoot_conversation_id,
        )
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


def _parse_tag_private_note(content: str) -> dict[str, str | int] | None:
    """
    Parse a private-note tag command. Returns None if not a tag command.
    Otherwise returns {"kind": "manual"|"sweep"|"reject", ...}.
    """
    tokens = content.strip().split()
    if not tokens or tokens[0].lower() != "tag":
        return None
    if len(tokens) == 1:
        return {"kind": "manual"}

    op_raw = tokens[1].lower()
    if op_raw == "sweep":
        return {"kind": "reject"}

    operation = _SWEEP_OP_CANON.get(op_raw)
    if operation is None or operation not in _SWEEP_CHAT_ALLOWED:
        return {"kind": "reject"}

    limit = _SWEEP_CHAT_DEFAULT_LIMIT
    if len(tokens) >= 3:
        try:
            limit = int(tokens[2])
            if limit <= 0:
                return {"kind": "reject"}
        except ValueError:
            return {"kind": "reject"}
        if limit > _SWEEP_CHAT_MAX_LIMIT:
            return {"kind": "reject"}

    return {"kind": "sweep", "operation": operation, "limit": limit}


async def _reject_tag_sweep_command(chatwoot_conversation_id: int) -> None:
    from app.chatwoot_client import send_private_note
    await send_private_note(chatwoot_conversation_id, _SWEEP_CHAT_REJECTION_MESSAGE)


async def _process_tag_sweep_command(
    chatwoot_conversation_id: int,
    operation: str,
    limit: int,
) -> None:
    from app.chatwoot_client import send_private_note
    from app.tagassigner.sweep import run_sweep

    count = await run_sweep(operation, limit)
    await send_private_note(
        chatwoot_conversation_id,
        f"Sweep '{operation}' enqueued {count} conversation(s).",
    )


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

    if await _is_live_testing_new_conversation_rejected(chatwoot_conversation_id):
        return JSONResponse(status_code=200, content={"status": "live_testing_limit_reached"})

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
    sent_at = _parse_sent_at(message_payload, payload)

    # Private notes and outbound messages need synchronous handling (tag trigger,
    # human-takeover detection, direct persistence) and are never debounced.
    if is_private or our_message_type == "outbound":
        logger.info("WEBHOOK: upserting conversation cw_id=%s phone=%r", chatwoot_conversation_id, contact_phone)
        conversation = await queries.upsert_conversation(chatwoot_conversation_id, contact_phone)
        logger.info("WEBHOOK: conversation upserted id=%s", conversation.id)

        # Capture private-note tag commands (manual trigger or sweep)
        if is_private and content:
            tag_cmd = _parse_tag_private_note(content)
            if tag_cmd is not None:
                if tag_cmd["kind"] == "manual":
                    logger.info(
                        "WEBHOOK: 'tag' manual trigger detected for conversation %s",
                        conversation.id,
                    )
                else:
                    logger.info(
                        "WEBHOOK: tag sweep command kind=%s for conversation %s",
                        tag_cmd["kind"], conversation.id,
                    )
                if chatwoot_message_id:
                    await queries.insert_message(
                        conversation.id, chatwoot_message_id, content,
                        "inbound", "user", sender_id, sender_name, is_private=True, sent_at=sent_at,
                    )
                if tag_cmd["kind"] == "manual":
                    background_tasks.add_task(
                        _process_manual_tag_trigger,
                        conversation_id=conversation.id,
                        chatwoot_conversation_id=chatwoot_conversation_id,
                    )
                elif tag_cmd["kind"] == "reject":
                    background_tasks.add_task(
                        _reject_tag_sweep_command,
                        chatwoot_conversation_id=chatwoot_conversation_id,
                    )
                else:
                    background_tasks.add_task(
                        _process_tag_sweep_command,
                        chatwoot_conversation_id=chatwoot_conversation_id,
                        operation=tag_cmd["operation"],
                        limit=tag_cmd["limit"],
                    )
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
                    our_message_type, sender_type_val, sender_id, sender_name, sent_at=sent_at,
                )
            return JSONResponse(status_code=200, content={"status": "ok"})

        # Private, non-tag note: persist only, no processing.
        if chatwoot_message_id:
            await queries.insert_message(
                conversation.id, chatwoot_message_id, content,
                "inbound", "contact", sender_id, sender_name, is_private=True, sent_at=sent_at,
            )
        return JSONResponse(status_code=200, content={"status": "ok"})

    # Inbound, non-private → enqueue immediately (before the slow conversation upsert),
    # keyed by chatwoot_conversation_id. Upsert + persistence happen once at flush time
    # so the debounce timer tracks the customer's send cadence, not our latency.
    background_tasks.add_task(
        _enqueue_debounced_inbound,
        chatwoot_conversation_id=chatwoot_conversation_id,
        content=content or "",
        chatwoot_message_id=chatwoot_message_id,
        sent_at=sent_at,
        contact_phone=contact_phone,
        sender_id=sender_id,
        sender_name=sender_name,
    )

    return JSONResponse(status_code=200, content={"status": "ok"})


async def _process_inbound(
    *,
    chatwoot_conversation_id: int,
    contact_phone: str | None,
    fragments: list[_DebounceFragment],
) -> None:
    """
    Upsert the conversation, persist each buffered fragment, and run one coalesced
    InfoGatherer turn. Serialized per conversation so overlapping flushes never
    process stale state.
    """
    from app.layers.info_gatherer import process_message

    if not fragments:
        return

    async with _get_processing_lock(chatwoot_conversation_id):
        conversation = await queries.upsert_conversation(chatwoot_conversation_id, contact_phone)

        for fragment in fragments:
            if fragment.chatwoot_message_id is not None:
                await queries.insert_message(
                    conversation.id,
                    fragment.chatwoot_message_id,
                    fragment.content,
                    "inbound",
                    "contact",
                    fragment.sender_id,
                    fragment.sender_name,
                    is_private=False,
                    sent_at=fragment.sent_at,
                )

        combined = "\n".join(f.content for f in fragments)
        # Phrase-gate first-message detection keys on the earliest message id, so
        # pass the burst's minimum id, not the last.
        ids = [f.chatwoot_message_id for f in fragments if f.chatwoot_message_id is not None]
        first_message_id = min(ids) if ids else None

        try:
            await process_message(
                conversation,
                chatwoot_conversation_id,
                combined,
                chatwoot_message_id=first_message_id,
            )
        except Exception as exc:
            logger.error(
                "WEBHOOK bg: unhandled error in process_message for conversation %s: %s",
                conversation.id, exc,
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
