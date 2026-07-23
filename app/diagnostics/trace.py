"""
Central trace recorder for live-test diagnostics.

Captures structured events from webhooks, debounce, InfoGatherer, RecEngine,
Chatwoot client calls, and HTTP edges. Events fan out to SSE subscribers and
optional JSONL on disk for post-mortem analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Deque, Optional

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 4000
_MAX_RING = 8000


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Redact secrets and truncate large strings for trace payloads."""
    if depth > 6:
        return "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_BODY_CHARS:
            return value[:_MAX_BODY_CHARS] + f"…[+{len(value) - _MAX_BODY_CHARS}]"
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            kl = str(k).lower()
            if any(x in kl for x in ("secret", "token", "password", "authorization", "api_key")):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = _sanitize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value[:200]]
    return str(value)


@dataclass(frozen=True)
class TraceEvent:
    """One observable step in the pipeline."""

    seq: int
    ts: str
    layer: str
    event: str
    level: str = "info"
    chatwoot_conversation_id: Optional[int] = None
    conversation_id: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class TraceHub:
    """Thread-safe async hub: ring buffer, SSE fan-out, JSONL append."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seq = 0
        self._ring: Deque[TraceEvent] = deque(maxlen=_MAX_RING)
        self._subscribers: list[asyncio.Queue[TraceEvent | None]] = []
        self._jsonl_path: Optional[Path] = None
        self._enabled = False

    def configure(self, *, enabled: bool, jsonl_path: Optional[str]) -> None:
        self._enabled = enabled
        if jsonl_path:
            path = Path(jsonl_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._jsonl_path = path
        else:
            self._jsonl_path = None
        if enabled:
            logger.info(
                "Live trace enabled (ring=%d, jsonl=%s)",
                _MAX_RING,
                self._jsonl_path,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def emit(
        self,
        layer: str,
        event: str,
        *,
        level: str = "info",
        chatwoot_conversation_id: Optional[int] = None,
        conversation_id: Optional[uuid.UUID | str] = None,
        **detail: Any,
    ) -> None:
        if not self._enabled:
            return
        async with self._lock:
            self._seq += 1
            conv_str = str(conversation_id) if conversation_id is not None else None
            ev = TraceEvent(
                seq=self._seq,
                ts=_utc_now_iso(),
                layer=layer,
                event=event,
                level=level,
                chatwoot_conversation_id=chatwoot_conversation_id,
                conversation_id=conv_str,
                detail=_sanitize(detail) if detail else {},
            )
            self._ring.append(ev)
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
        if self._jsonl_path:
            try:
                with self._jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(ev.to_json() + "\n")
            except OSError as exc:
                logger.warning("Live trace JSONL write failed: %s", exc)

    async def recent(
        self,
        limit: int = 500,
        *,
        chatwoot_conversation_id: Optional[int] = None,
        layer: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            items = list(self._ring)
        if chatwoot_conversation_id is not None:
            items = [e for e in items if e.chatwoot_conversation_id == chatwoot_conversation_id]
        if layer:
            items = [e for e in items if e.layer == layer]
        tail = items[-limit:]
        return [asdict(e) for e in tail]

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            total = len(self._ring)
            by_layer: dict[str, int] = {}
            for e in self._ring:
                by_layer[e.layer] = by_layer.get(e.layer, 0) + 1
        return {
            "enabled": self._enabled,
            "total_in_ring": total,
            "max_ring": _MAX_RING,
            "seq": self._seq,
            "jsonl_path": str(self._jsonl_path) if self._jsonl_path else None,
            "by_layer": by_layer,
            "subscribers": len(self._subscribers),
        }

    async def subscribe(self) -> AsyncIterator[TraceEvent]:
        q: asyncio.Queue[TraceEvent | None] = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield item
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


_hub = TraceHub()


def get_trace_hub() -> TraceHub:
    return _hub


def trace_event(
    layer: str,
    event: str,
    *,
    level: str = "info",
    chatwoot_conversation_id: Optional[int] = None,
    conversation_id: Optional[uuid.UUID | str] = None,
    **detail: Any,
) -> None:
    """
    Fire-and-forget trace emit (schedules on the running event loop).
    Safe to call from sync code paths only when a loop is running.
    """
    if not _hub.enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _hub.emit(
            layer,
            event,
            level=level,
            chatwoot_conversation_id=chatwoot_conversation_id,
            conversation_id=conversation_id,
            **detail,
        )
    )


async def trace_event_async(
    layer: str,
    event: str,
    *,
    level: str = "info",
    chatwoot_conversation_id: Optional[int] = None,
    conversation_id: Optional[uuid.UUID | str] = None,
    **detail: Any,
) -> None:
    """Awaitable trace emit for async handlers."""
    await _hub.emit(
        layer,
        event,
        level=level,
        chatwoot_conversation_id=chatwoot_conversation_id,
        conversation_id=conversation_id,
        **detail,
    )
