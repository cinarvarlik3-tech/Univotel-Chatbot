"""
Terminal sweep entry point. Unlimited, all operations.
Usage:
    python3 scripts/tag_sweep.py sweep              # all conversations, no limit
    python3 scripts/tag_sweep.py sweepSafe 50       # 50 oldest not-successfully-run-in-24h
    python3 scripts/tag_sweep.py sweepEmpty         # all unlabeled, no limit
Operation is case-insensitive. Limit optional (omit = unlimited).
"""
from __future__ import annotations
import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app.db.client import create_pool, close_pool
from app.tagassigner.sweep import run_sweep, VALID_OPERATIONS

_CANON = {op.lower(): op for op in VALID_OPERATIONS}


async def _main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: tag_sweep.py <{'|'.join(VALID_OPERATIONS)}> [limit]")
        sys.exit(2)
    op_raw = sys.argv[1].lower()
    if op_raw not in _CANON:
        print(f"unknown operation '{sys.argv[1]}'. valid: {', '.join(VALID_OPERATIONS)}")
        sys.exit(2)
    operation = _CANON[op_raw]
    limit = None
    if len(sys.argv) >= 3:
        try:
            limit = int(sys.argv[2])
            if limit <= 0:
                raise ValueError
        except ValueError:
            print("limit must be a positive integer")
            sys.exit(2)
    await create_pool()
    try:
        count = await run_sweep(operation, limit)
        print(f"sweep '{operation}' (limit={limit}) enqueued {count} conversation(s).")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
