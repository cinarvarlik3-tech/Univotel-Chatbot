"""
Terminal tag/sweep entry point (Spec 021 + Spec 022).

Usage:
    tag sweep              # all conversations, no limit
    tag sweep --5          # 5 oldest conversations
    tag sweepSafe 10
    tag sweepEmpty

Run via ./scripts/tag from the project root (see scripts/tag wrapper).
"""
from __future__ import annotations
import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app.db.client import create_pool, close_pool
from app.tagassigner.sweep import run_sweep, VALID_OPERATIONS

_CANON = {op.lower(): op for op in VALID_OPERATIONS}


def _parse_limit(raw: str) -> int:
    """Accept 5, --5, or --limit=5."""
    s = raw.strip()
    if s.startswith("--limit="):
        s = s.split("=", 1)[1]
    elif s.startswith("--"):
        s = s[2:]
    limit = int(s)
    if limit <= 0:
        raise ValueError("limit must be positive")
    return limit


def _usage() -> str:
    ops = "|".join(VALID_OPERATIONS)
    return (
        f"usage: tag <{ops}> [limit]\n"
        "  limit forms: 5  --5  --limit=5\n"
        "examples:\n"
        "  tag sweep --5\n"
        "  tag sweepSafe 10\n"
        "  tag sweepEmpty"
    )


async def _main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(_usage())
        sys.exit(2)

    op_raw = argv[0].lower()
    if op_raw not in _CANON:
        print(f"unknown operation '{argv[0]}'. valid: {', '.join(VALID_OPERATIONS)}")
        sys.exit(2)
    operation = _CANON[op_raw]

    limit = None
    if len(argv) >= 2:
        try:
            limit = _parse_limit(argv[1])
        except ValueError:
            print("limit must be a positive integer (e.g. 5, --5, --limit=5)")
            sys.exit(2)

    await create_pool()
    try:
        count = await run_sweep(operation, limit)
        print(f"sweep '{operation}' (limit={limit}) enqueued {count} conversation(s).")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
