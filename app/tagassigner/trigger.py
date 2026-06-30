"""
TagAssigner trigger sweeps (§5.2, §5.3, §5.4 of tagassigner-v1-spec.md).

Three in-process asyncio loops:
1. Idle-scan sweep — every ~90s, enqueues conversations that have crossed the
   5-message / 15-min-idle gate.
2. Istanbul-midnight reset — daily at 21:00 UTC (= midnight Istanbul, UTC+3),
   resets auto_run_count and manual_run_count for all conversations.
3. Nightly batch trigger — daily at 20:40 UTC (= 23:40 Istanbul), submits the
   batch sweep via batch_client.

All use in-process asyncio loops, consistent with reprompt_sweep.py and
integrity_check.py. No pg_cron.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.db import queries

logger = logging.getLogger(__name__)

_IDLE_SCAN_INTERVAL_SECONDS = 90

# Istanbul is UTC+3, no DST since 2016.
_MIDNIGHT_ISTANBUL_UTC_HOUR = 21   # 21:00 UTC = 00:00 Istanbul
_NIGHTLY_BATCH_UTC_HOUR = 20       # 20:40 UTC = 23:40 Istanbul
_NIGHTLY_BATCH_UTC_MINUTE = 40


async def start_idle_scan_sweep() -> None:
    """
    Polls for conversations that have crossed the 5-message / 15-min-idle gate
    and enqueues them for automated tagging.
    """
    logger.info("TagAssigner idle-scan sweep started (interval=%ds)", _IDLE_SCAN_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(_IDLE_SCAN_INTERVAL_SECONDS)
            if settings.tagassigner_auto_runs:
                await _run_idle_scan()
        except asyncio.CancelledError:
            logger.info("TagAssigner idle-scan sweep cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("TagAssigner idle-scan sweep error: %s", exc)


async def _run_idle_scan() -> None:
    conversations = await queries.get_conversations_eligible_for_tagging()
    if not conversations:
        return

    logger.info("TagAssigner idle-scan: %d conversation(s) eligible", len(conversations))

    for conv in conversations:
        enqueued = await queries.enqueue_tagassigner_run(conv.id, "message")
        if enqueued:
            await queries.increment_auto_run_count(conv.id)
            logger.info(
                "TagAssigner idle-scan: enqueued conversation %s (auto_run_count now %d)",
                conv.id, conv.auto_run_count + 1,
            )


async def start_midnight_reset_sweep() -> None:
    """
    Daily job: resets auto_run_count and manual_run_count for all conversations
    at Istanbul midnight (21:00 UTC).
    """
    logger.info("TagAssigner midnight reset sweep started (fires at %02d:00 UTC)", _MIDNIGHT_ISTANBUL_UTC_HOUR)
    while True:
        try:
            await _sleep_until_utc_hour(_MIDNIGHT_ISTANBUL_UTC_HOUR, 0)
            logger.info("TagAssigner midnight reset: resetting daily run counts")
            await queries.reset_daily_run_counts()
        except asyncio.CancelledError:
            logger.info("TagAssigner midnight reset sweep cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("TagAssigner midnight reset sweep error: %s", exc)


async def start_nightly_batch_sweep() -> None:
    """
    Nightly batch trigger at 23:40 Istanbul (20:40 UTC).
    Submits eligible conversations to the Gemini Batch API.
    """
    logger.info(
        "TagAssigner nightly batch sweep started (fires at %02d:%02d UTC)",
        _NIGHTLY_BATCH_UTC_HOUR, _NIGHTLY_BATCH_UTC_MINUTE,
    )
    while True:
        try:
            await _sleep_until_utc_hour(_NIGHTLY_BATCH_UTC_HOUR, _NIGHTLY_BATCH_UTC_MINUTE)
            if settings.tagassigner_auto_runs:
                logger.info("TagAssigner nightly batch: starting sweep")
                from app.tagassigner.batch_client import submit_nightly_batch
                await submit_nightly_batch()
        except asyncio.CancelledError:
            logger.info("TagAssigner nightly batch sweep cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("TagAssigner nightly batch sweep error: %s", exc)


async def _sleep_until_utc_hour(target_hour: int, target_minute: int) -> None:
    """Sleep until the next occurrence of target_hour:target_minute UTC."""
    while True:
        now = datetime.now(tz=timezone.utc)
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if target <= now:
            # Already past today's window — schedule for tomorrow
            target = target.replace(day=target.day + 1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        # Verify we've actually crossed the target (avoids early wakeup drift)
        if datetime.now(tz=timezone.utc) >= target:
            return
