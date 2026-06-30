"""
Reprompt sweep — runs every 3 hours as an in-process asyncio loop (§6.4).

Reprompt ladder per conversation:
  reprompt_count=0, 3h elapsed  → send "Efendim?"        count→1
  reprompt_count=1, 3h elapsed  → send "Orada mısınız?"  count→2
  reprompt_count=2, 3h elapsed  → send long message       count→3
  reprompt_count≥3              → nothing further

No terminal state is set — the conversation simply waits indefinitely.
"""
import asyncio
import logging

from app.db import queries
from app.background.send_retry import send_with_retry

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 3 * 60 * 60  # 3 hours

REPROMPT_MESSAGES = [
    "Efendim?",
    "Orada mısınız?",
    "Müsait olduğunuzda dönüşünüzü bekliyorum efendim.",
]


async def start_reprompt_sweep() -> None:
    """Long-running in-process sweep. Cancelled gracefully on app shutdown."""
    logger.info("Reprompt sweep started (interval=%ds)", SWEEP_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            await _run_sweep()
        except asyncio.CancelledError:
            logger.info("Reprompt sweep cancelled — shutting down")
            return
        except Exception as exc:
            logger.error("Reprompt sweep error: %s", exc)


async def _run_sweep() -> None:
    conversations = await queries.get_conversations_awaiting_reprompt()
    logger.info("Reprompt sweep: %d conversations eligible", len(conversations))

    for conv in conversations:
        count = conv.reprompt_count
        if count >= len(REPROMPT_MESSAGES):
            continue

        message = REPROMPT_MESSAGES[count]
        result = await send_with_retry(conv.chatwoot_conversation_id, message)
        if result.ok:
            await queries.increment_reprompt_count(conv.id)
            logger.info(
                "Reprompt sweep: sent reprompt %d to conversation %s",
                count + 1, conv.id,
            )
        else:
            logger.error(
                "Reprompt sweep: failed to send reprompt to conversation %s: %s",
                conv.id, result.error,
            )
