"""
STATUS_EXPR branch coverage against a real Postgres (DASHBOARD_SPEC.md §13.2).

Marked integration — excluded from the default run. Execute with:
    pytest -m integration tests/dashboard/test_status_sql.py

Each case inserts a conversation inside a transaction that is always rolled back,
so the live table is never modified. The precedence cases are the point: the order
of the CASE arms is the whole classification, and a reordering would silently move
conversations between the red and purple cards.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from dashboard.api import sql

pytestmark = pytest.mark.integration

STALE_HOURS = 24
NOW = datetime.now(tz=timezone.utc)
FRESH = NOW - timedelta(hours=1)
STALE = NOW - timedelta(hours=STALE_HOURS + 1)

STATUS_ONLY_QUERY = f"""
{sql.BASE_CTE}
SELECT status FROM base WHERE id = $2
"""


@pytest.fixture
async def conn():
    import asyncpg
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    connection = await asyncpg.connect(database_url)
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        # Roll back unconditionally — this suite must never leave rows behind.
        await transaction.rollback()
        await connection.close()


async def insert_conversation(conn, **overrides) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    values = {
        "id": conversation_id,
        "chatwoot_conversation_id": -abs(hash(conversation_id)) % 1_000_000,
        "flow_state": "new",
        "bot_enabled": True,
        "infogatherer_abstain_reason": None,
        "created_at": FRESH,
        "last_updated_at": FRESH,
        "last_message_at": FRESH,
    }
    values.update(overrides)
    await conn.execute(
        """
        INSERT INTO conversations
            (id, chatwoot_conversation_id, flow_state, bot_enabled,
             infogatherer_abstain_reason, created_at, last_updated_at, last_message_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        *values.values(),
    )
    return conversation_id


async def insert_log(conn, conversation_id: uuid.UUID, *, log_level: str, is_success=False):
    await conn.execute(
        """
        INSERT INTO chatbot_logs
            (conversation_id, operation_layer, which_run, log_level, is_success, explanation)
        VALUES ($1,'infoGatherer','contextRun',$2,$3,'test')
        """,
        conversation_id,
        log_level,
        is_success,
    )


async def status_of(conn, conversation_id: uuid.UUID) -> str:
    return await conn.fetchval(STATUS_ONLY_QUERY, STALE_HOURS, conversation_id)


# ---------------------------------------------------------------------------
# The five terminal mappings
# ---------------------------------------------------------------------------

async def test_completed_is_success(conn):
    cid = await insert_conversation(conn, flow_state="completed")
    assert await status_of(conn, cid) == "success"


async def test_human_needed_is_purple(conn):
    cid = await insert_conversation(conn, flow_state="human_needed")
    assert await status_of(conn, cid) == "human_needed"


async def test_stopped_is_human_interruption(conn):
    cid = await insert_conversation(conn, flow_state="stopped")
    assert await status_of(conn, cid) == "human_interruption"


async def test_fresh_mid_flow_is_in_progress(conn):
    cid = await insert_conversation(conn, flow_state="awaiting_gender", last_message_at=FRESH)
    assert await status_of(conn, cid) == "in_progress"


async def test_error_log_makes_it_failed(conn):
    cid = await insert_conversation(conn, flow_state="awaiting_gender")
    await insert_log(conn, cid, log_level="error")
    assert await status_of(conn, cid) == "failed"


async def test_backfill_failed_abstain_is_failed(conn):
    cid = await insert_conversation(
        conn, bot_enabled=False, infogatherer_abstain_reason="backfill_failed"
    )
    assert await status_of(conn, cid) == "failed"


async def test_prior_history_abstain_is_not_run(conn):
    cid = await insert_conversation(
        conn, bot_enabled=False, infogatherer_abstain_reason="prior_history"
    )
    assert await status_of(conn, cid) == "not_run"


# ---------------------------------------------------------------------------
# Precedence — the cases a CASE-arm reordering would break
# ---------------------------------------------------------------------------

async def test_errored_then_escalated_reads_human_needed_not_failed(conn):
    """
    The escalation is the outcome that matters; the error stays visible in the
    conversation's log rows. Swapping these arms would move rows to the red card.
    """
    cid = await insert_conversation(conn, flow_state="human_needed")
    await insert_log(conn, cid, log_level="fatal")
    assert await status_of(conn, cid) == "human_needed"


async def test_outbound_first_abstain_reads_as_interruption(conn):
    """
    chatwoot.py sets stopped (:730) before the abstain reason (:733). A human agent
    sent the first message, so blue is correct and no extra branch is needed.
    """
    cid = await insert_conversation(
        conn,
        flow_state="stopped",
        bot_enabled=False,
        infogatherer_abstain_reason="outbound_first",
    )
    assert await status_of(conn, cid) == "human_interruption"


async def test_completed_with_an_error_log_still_reads_success(conn):
    cid = await insert_conversation(conn, flow_state="completed")
    await insert_log(conn, cid, log_level="error")
    assert await status_of(conn, cid) == "success"


async def test_prior_history_abstain_with_error_log_is_failed(conn):
    """A technical error outranks the abstain classification."""
    cid = await insert_conversation(
        conn, bot_enabled=False, infogatherer_abstain_reason="prior_history"
    )
    await insert_log(conn, cid, log_level="error")
    assert await status_of(conn, cid) == "failed"


# ---------------------------------------------------------------------------
# The stale boundary
# ---------------------------------------------------------------------------

async def test_stale_mid_flow_is_failed(conn):
    cid = await insert_conversation(
        conn, flow_state="awaiting_university", last_message_at=STALE
    )
    assert await status_of(conn, cid) == "failed"


async def test_just_inside_the_window_is_still_in_progress(conn):
    cid = await insert_conversation(
        conn,
        flow_state="awaiting_university",
        last_message_at=NOW - timedelta(hours=STALE_HOURS - 1),
    )
    assert await status_of(conn, cid) == "in_progress"


async def test_stale_uses_created_at_when_no_messages(conn):
    cid = await insert_conversation(
        conn, flow_state="new", created_at=STALE, last_message_at=None
    )
    assert await status_of(conn, cid) == "failed"


async def test_completed_never_goes_stale(conn):
    cid = await insert_conversation(
        conn, flow_state="completed", last_message_at=STALE
    )
    assert await status_of(conn, cid) == "success"


async def test_stopped_never_goes_stale(conn):
    cid = await insert_conversation(conn, flow_state="stopped", last_message_at=STALE)
    assert await status_of(conn, cid) == "human_interruption"


async def test_informational_log_does_not_cause_failure(conn):
    """abstain_prior_history rows are log_level='info' — they must not turn a row red."""
    cid = await insert_conversation(conn, flow_state="awaiting_gender")
    await insert_log(conn, cid, log_level="info")
    assert await status_of(conn, cid) == "in_progress"


# ---------------------------------------------------------------------------
# Every SQL fragment must parse and run
# ---------------------------------------------------------------------------

async def test_all_stats_queries_execute(conn):
    """Catches a syntax error in a fragment the unit tests never execute."""
    await conn.fetch(sql.STATUS_COUNTS_QUERY, STALE_HOURS)
    await conn.fetchrow(sql.CLEAN_INTERRUPTION_QUERY, STALE_HOURS)
    await conn.fetch(sql.BREAKDOWN_ROWS_QUERY, STALE_HOURS)
    await conn.fetch(sql.HUMAN_NEEDED_TRIGGERS_QUERY, STALE_HOURS)


async def test_conversation_list_query_executes(conn):
    query = sql.conversations_query(
        where_sql="TRUE", sort="last_activity", direction="desc",
        limit_param=2, offset_param=3,
    )
    await conn.fetch(query, STALE_HOURS, 5, 0)


async def test_every_sort_column_executes(conn):
    for sort_key in sql.SORT_COLUMNS:
        query = sql.conversations_query(
            where_sql="TRUE", sort=sort_key, direction="asc",
            limit_param=2, offset_param=3,
        )
        await conn.fetch(query, STALE_HOURS, 1, 0)


async def test_lead_name_prefers_contact_over_agent_private_note(conn):
    """
    Private notes are stored with sender_type='contact' and carry the agent's name
    (chatwoot.py:757). They must not become the lead's name.
    """
    cid = await insert_conversation(conn, flow_state="new")
    await conn.execute(
        """
        INSERT INTO messages
            (conversation_id, chatwoot_message_id, content, message_type,
             sender_type, sender_name, is_private, sent_at)
        VALUES
            ($1, $2, 'hi',   'inbound', 'contact', 'Real Lead',  false, now() - interval '2 min'),
            ($1, $3, 'note', 'inbound', 'contact', 'Agent Name', true,  now() - interval '1 min')
        """,
        cid,
        -abs(hash(cid)) % 1_000_000,
        -abs(hash(str(cid) + "b")) % 1_000_000,
    )
    name = await conn.fetchval(
        f"{sql.BASE_CTE} SELECT lead_name FROM base WHERE id = $2", STALE_HOURS, cid
    )
    assert name == "Real Lead"
