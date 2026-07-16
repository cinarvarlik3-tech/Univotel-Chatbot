"""
Terminal tag/sweep entry point (Spec 021 + Spec 022).

Usage:
    tag sweep              # all conversations, no limit
    tag sweep --5          # 5 oldest conversations
    tag sweepSafe 10
    tag sweepEmpty
    tag importConvo --10   # import 10 random CRM conversations into chatbot DB
    tag sweepclean --confirm       # wipe DB + clear Chatwoot labels/attributes
    tag sweepclean --confirm --db-only   # DB wipe only (skip Chatwoot API)

Run via ./scripts/tag from the project root (see scripts/tag wrapper).
"""
from __future__ import annotations
import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from app.db.client import create_pool, close_pool
from app.tagassigner.sweep import run_sweep, VALID_OPERATIONS
from app.tagassigner.sweep_clean import run_sweep_clean
from app.tagassigner.crm_import import run_import_from_crm

_CANON = {op.lower(): op for op in VALID_OPERATIONS}
_SWEEPCLEAN = "sweepclean"
_IMPORT_CONVO = "importconvo"


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
        f"usage: tag <{ops}|importConvo|sweepclean> [limit] [--confirm] [--db-only]\n"
        "  limit forms: 5  --5  --limit=5\n"
        "examples:\n"
        "  tag sweep --5\n"
        "  tag importConvo --10\n"
        "  tag sweepSafe 10\n"
        "  tag sweepEmpty\n"
        "  tag sweepclean --confirm"
    )


def _parse_sweepclean_flags(argv: list[str]) -> tuple[bool, bool]:
    confirm = "--confirm" in argv
    db_only = "--db-only" in argv
    return confirm, db_only


async def _main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(_usage())
        sys.exit(2)

    op_raw = argv[0].lower()

    if op_raw == _IMPORT_CONVO:
        if len(argv) < 2:
            print("importConvo requires a limit (e.g. tag importConvo --10)")
            sys.exit(2)
        try:
            limit = _parse_limit(argv[1])
        except ValueError:
            print("limit must be a positive integer (e.g. 10, --10, --limit=10)")
            sys.exit(2)
        result = await run_import_from_crm(limit)
        print(
            f"importConvo done: {result.conversations_imported} conversation(s), "
            f"{result.messages_inserted} message(s)."
        )
        return

    await create_pool()
    try:
        if op_raw == _SWEEPCLEAN:
            confirm, db_only = _parse_sweepclean_flags(argv[1:])
            if not confirm:
                print(
                    "sweepclean is destructive — clears Chatwoot labels/attributes and "
                    "deletes all conversations, messages, queue rows, and logs.\n"
                    "Re-run with: tag sweepclean --confirm"
                )
                sys.exit(2)
            result = await run_sweep_clean(skip_chatwoot=db_only)
            print(
                f"sweepclean done: {result.conversations_found} conversation(s) found, "
                f"{result.chatwoot_cleared} Chatwoot cleared, "
                f"{result.chatwoot_failed} Chatwoot failed."
            )
            for table, count in result.db_deleted.items():
                print(f"  {table}: deleted {count} row(s)")
            return

        if op_raw not in _CANON:
            valid = ", ".join([*VALID_OPERATIONS, "importConvo", _SWEEPCLEAN])
            print(f"unknown operation '{argv[0]}'. valid: {valid}")
            sys.exit(2)
        operation = _CANON[op_raw]

        limit = None
        if len(argv) >= 2:
            try:
                limit = _parse_limit(argv[1])
            except ValueError:
                print("limit must be a positive integer (e.g. 5, --5, --limit=5)")
                sys.exit(2)

        count = await run_sweep(operation, limit)
        print(f"sweep '{operation}' (limit={limit}) enqueued {count} conversation(s).")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
