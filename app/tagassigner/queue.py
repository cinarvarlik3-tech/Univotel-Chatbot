"""
Durable queue drain for TagAssigner (§6.2 of tagassigner-v1-spec.md).

Drains the tag_assigner_queue table at a rate held under the Gemini RPM ceiling.
Uses the durable Postgres table (not an in-process queue) so a Railway restart
mid-drain loses nothing.

On a 429 from Gemini the run is retried with exponential backoff.
"""
from __future__ import annotations
import asyncio
import logging
import uuid

from app.db import queries

logger = logging.getLogger(__name__)

# Drain interval: how often the worker polls for pending items.
_DRAIN_INTERVAL_SECONDS = 10

# Gemini Tier 1 ceiling: 150 RPM → one request every 0.4s minimum.
# We target well below that; 6 RPM (one per 10s poll) leaves headroom.
# The batch path handles the nightly burst independently.
_INTER_REQUEST_DELAY_SECONDS = 0.5

# 429 backoff: 5s → 30s → 120s
_BACKOFF_DELAYS = [5.0, 30.0, 120.0]


async def start_queue_drain() -> None:
    """
    Long-running in-process worker. Drains pending queue items one at a time.
    Cancelled gracefully on app shutdown.
    """
    logger.info("TagAssigner queue drain started (poll_interval=%ds)", _DRAIN_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(_DRAIN_INTERVAL_SECONDS)
            await _drain_one()
        except asyncio.CancelledError:
            logger.info("TagAssigner queue drain cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("TagAssigner queue drain error: %s", exc)


async def _drain_one() -> None:
    """Process up to one pending item per drain tick."""
    items = await queries.get_pending_queue_items(limit=1)
    if not items:
        return

    item = items[0]
    run_id = uuid.uuid4()
    trigger_type = item.trigger_type or "message"

    # Write the 'processing' run row BEFORE binding it on the queue item.
    # tag_assigner_queue.run_id has an FK to tag_assigner_runs, and run_tagging's
    # idempotency contract assumes this row already exists when it is called.
    await queries.insert_tagassigner_run(run_id, item.conversation_id, trigger_type)

    claimed = await queries.claim_queue_item(item.id, run_id)
    if not claimed:
        return

    logger.info(
        "TagAssigner queue: processing item %s (conversation=%s trigger=%s run_id=%s)",
        item.id, item.conversation_id, trigger_type, run_id,
    )

    try:
        success = await _run_with_backoff(
            run_id=run_id,
            conversation_id=item.conversation_id,
            trigger_type=trigger_type,
            read_full_history=(trigger_type in ("manual", "scheduled")),
        )
    except Exception as exc:
        logger.error(
            "TagAssigner queue: run %s for conversation %s crashed: %s",
            run_id, item.conversation_id, exc,
        )
        success = False

    # Always drive both rows to a terminal state. A crash inside the run must never
    # leave an orphaned 'processing' run row — that would block every future trigger
    # for this conversation (has_processing_run would stay True forever).
    if not success:
        await queries.update_tagassigner_run_failed(run_id)
    await queries.update_queue_item_status(item.id, "done" if success else "failed")

    await asyncio.sleep(_INTER_REQUEST_DELAY_SECONDS)


async def _run_with_backoff(
    run_id: uuid.UUID,
    conversation_id: uuid.UUID,
    trigger_type: str,
    read_full_history: bool,
) -> bool:
    """
    Attempt a TagAssigner run. On 429-equivalent (Gemini rate limit), back off and retry.
    Other failures fall through to the router's own retry logic.
    """
    from app.tagassigner.router import run_tagging

    for attempt, backoff in enumerate(_BACKOFF_DELAYS, start=1):
        try:
            result = await run_tagging(
                conversation_id=conversation_id,
                run_id=run_id,
                trigger_type=trigger_type,
                read_full_history=read_full_history,
            )
            return result
        except _RateLimitError:
            logger.warning(
                "TagAssigner queue: 429 rate limit on attempt %d for conversation %s — "
                "backing off %ds",
                attempt, conversation_id, int(backoff),
            )
            if attempt < len(_BACKOFF_DELAYS):
                await asyncio.sleep(backoff)

    logger.error(
        "TagAssigner queue: rate-limit backoff exhausted for conversation %s",
        conversation_id,
    )
    return False


class _RateLimitError(Exception):
    """Raised by the router when Gemini returns a 429."""
