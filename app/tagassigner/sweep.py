"""
Manual sweep operations: enqueue a filtered population of conversations for
TagAssigner processing. Enqueue only — the existing queue drain runs the Router.
"""
from __future__ import annotations
import logging
from typing import Optional

from app.db import queries

logger = logging.getLogger(__name__)

VALID_OPERATIONS = ("sweep", "sweepEmpty", "sweepSafe")
SWEEP_TRIGGER_TYPE = "sweep"


async def run_sweep(operation: str, limit: Optional[int]) -> int:
    """
    Enqueue conversations matching the operation's filter. Returns the number
    actually enqueued (dedupe-guarded — already-queued conversations are skipped).
    Operation name is matched case-insensitively by the caller; pass canonical form.
    """
    if operation == "sweep":
        convos = await queries.get_conversations_for_sweep(limit)
    elif operation == "sweepEmpty":
        convos = await queries.get_conversations_for_sweep_empty(limit)
    elif operation == "sweepSafe":
        convos = await queries.get_conversations_for_sweep_safe(limit)
    else:
        raise ValueError(f"unknown sweep operation: {operation}")

    enqueued = 0
    for c in convos:
        if await queries.enqueue_tagassigner_run(c.id, trigger_type=SWEEP_TRIGGER_TYPE):
            enqueued += 1
    logger.info(
        "sweep '%s' (limit=%s): matched=%d enqueued=%d",
        operation, limit, len(convos), enqueued,
    )
    return enqueued
