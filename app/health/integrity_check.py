"""
Boot-time + daily referential integrity sweep.

Checks:
1. Every visible hotel has >= 1 response_schemas row.
2. Every response_schemas row points to a live canned_responses row and a live hotel.
3. GLOBAL-NULL-STATE hotel exists and has its response_schemas wired.
4. DEAL-AWAITING-STATE hotel exists and has its response_schemas wired.
5. Every visible (recommendable) hotel has a hotel_chatwoot_label_map row.
6. Every campus in university_parent_map has a university_chatwoot_label_map row.
7. Every university has a university_parent_map row.
8. No orphaned campus rows in university_parent_map (parent must exist).
9. No duplicate campus_label values within a single parent university.

Any failure logs fatal and raises RuntimeError on boot (fast-fail).
Daily sweep logs fatal but does not kill the process.
Bypassable via INTEGRITY_CHECK_BYPASS env flag.
"""
import asyncio
import logging

from app.db import queries

logger = logging.getLogger(__name__)

_DAILY_INTERVAL = 24 * 60 * 60


async def run_integrity_check(fatal_on_failure: bool = True) -> bool:
    ok = True

    missing = await queries.get_hotels_missing_response_schemas()
    if missing:
        logger.fatal(
            "INTEGRITY: %d visible hotel(s) have no response_schemas rows: %s",
            len(missing), [str(h) for h in missing],
        )
        ok = False

    orphans = await queries.get_orphaned_response_schema_entries()
    if orphans:
        logger.fatal(
            "INTEGRITY: %d orphaned response_schemas row(s) "
            "(missing canned_response or hotel): %s",
            len(orphans), [str(o) for o in orphans],
        )
        ok = False

    null_wired = await queries.global_null_state_is_wired()
    if not null_wired:
        logger.fatal(
            "INTEGRITY: GLOBAL-NULL-STATE hotel has no response_schemas row — "
            "run migration 003 and wire the 'henuz' canned response"
        )
        ok = False

    deal_wired = await queries.deal_awaiting_state_is_wired()
    if not deal_wired:
        logger.fatal(
            "INTEGRITY: DEAL-AWAITING-STATE hotel has no response_schemas row — "
            "run migration 006 and confirm the 'deal_awaiting_msg' canned response is seeded"
        )
        ok = False

    unmapped = await queries.get_visible_hotels_missing_label_map()
    if unmapped:
        logger.fatal(
            "INTEGRITY: %d visible hotel(s) have no hotel_chatwoot_label_map row "
            "(TagAssigner ilgili_otel writes will fail for these hotels): %s",
            len(unmapped), [str(h) for h in unmapped],
        )
        ok = False

    campus_unmapped = await queries.get_campus_university_ids_missing_chatwoot_label_map()
    if campus_unmapped:
        logger.fatal(
            "INTEGRITY: %d campus(es) have no university_chatwoot_label_map row "
            "(TagAssigner university writes will fail for these): %s",
            len(campus_unmapped), [str(u) for u in campus_unmapped],
        )
        ok = False

    missing_parent_map = await queries.get_universities_missing_parent_map()
    if missing_parent_map:
        logger.fatal(
            "INTEGRITY: %d university/universities have no university_parent_map row "
            "(campus escalation logic assumes every university has a parent): %s",
            len(missing_parent_map), [str(u) for u in missing_parent_map],
        )
        ok = False

    orphan_campuses = await queries.get_parent_map_orphan_campuses()
    if orphan_campuses:
        logger.fatal(
            "INTEGRITY: %d campus row(s) in university_parent_map reference a "
            "non-existent parent_universities row: %s",
            len(orphan_campuses), [str(u) for u in orphan_campuses],
        )
        ok = False

    dupe_label_parents = await queries.get_parent_ids_with_duplicate_campus_labels()
    if dupe_label_parents:
        logger.fatal(
            "INTEGRITY: %d parent university/universities have duplicate campus_label "
            "values (escalation question would repeat the same option): %s",
            len(dupe_label_parents), [str(p) for p in dupe_label_parents],
        )
        ok = False

    if ok:
        ooc_count = await queries.get_out_of_city_university_count()
        if ooc_count != 148:
            logger.warning(
                "INTEGRITY: out_of_city_universities has %d rows (expected 148) — "
                "out-of-city matching may be incomplete",
                ooc_count,
            )
        logger.info("INTEGRITY: all checks passed")
    elif fatal_on_failure:
        raise RuntimeError(
            "Integrity check failed at startup — fix the issues above before deploying"
        )

    return ok


async def start_daily_integrity_sweep() -> None:
    """Long-running in-process daily sweep. Logs but does not crash on failure."""
    while True:
        try:
            await asyncio.sleep(_DAILY_INTERVAL)
            await run_integrity_check(fatal_on_failure=False)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Daily integrity sweep error: %s", exc)
