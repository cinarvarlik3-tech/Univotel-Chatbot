"""
Divergence routing table — pure (intent × flow_state) → action policy (spec 019).

No LLM. Missing row defaults to escalate in code.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.db.models import DivergenceAction, DivergenceRoutingRow, RoutingDecision
from app.layers.divergence_classifier import Intent

logger = logging.getLogger(__name__)

_routing_cache: Optional[dict[tuple[str, str], RoutingDecision]] = None


def _row_to_decision(row: DivergenceRoutingRow) -> RoutingDecision:
    """Convert a DB routing row to a RoutingDecision."""
    return RoutingDecision(
        action=DivergenceAction(row.action),
        canned_response_id=row.canned_response_id,
        canned_response_alt_id=row.canned_response_alt_id,
    )


async def load_routing_table() -> dict[tuple[str, str], RoutingDecision]:
    """Load all divergence_routing rows into an in-memory lookup."""
    from app.db import queries

    rows = await queries.get_all_divergence_routing()
    table: dict[tuple[str, str], RoutingDecision] = {}
    for row in rows:
        table[(row.intent, row.flow_state)] = _row_to_decision(row)
    logger.info("divergence_router: loaded %d routing rows", len(table))
    return table


async def ensure_routing_cache() -> dict[tuple[str, str], RoutingDecision]:
    """Return cached routing table, loading from DB on first call."""
    global _routing_cache
    if _routing_cache is None:
        _routing_cache = await load_routing_table()
    return _routing_cache


def invalidate_routing_cache() -> None:
    """Clear cache (for tests)."""
    global _routing_cache
    _routing_cache = None


async def route(intent: Intent, flow_state: str) -> RoutingDecision:
    """
    Map (intent, flow_state) to an action. Missing row → escalate.
    """
    table = await ensure_routing_cache()
    decision = table.get((intent.value, flow_state))
    if decision is None:
        return RoutingDecision(action=DivergenceAction.ESCALATE)
    return decision
