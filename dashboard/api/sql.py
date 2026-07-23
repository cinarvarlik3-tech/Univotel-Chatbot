"""
Canonical SQL fragments for the dashboard.

Every endpoint composes these; none re-implements a rule. That is what stops a
conversation from reading 'failed' on the statistics page and 'in_progress' on the
conversations table. Spec §4 and §10.

All fragments are read-only. The dashboard never issues INSERT/UPDATE/DELETE.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# §4.2 — lead_name
# ---------------------------------------------------------------------------
# is_private = false matters: non-tag private notes are written with
# sender_type='contact' (chatwoot.py:757) and carry the *agent's* name.
LEAD_NAME_EXPR = """
COALESCE(
  (SELECT m.sender_name
     FROM messages m
    WHERE m.conversation_id = c.id
      AND m.sender_type = 'contact'
      AND m.is_private = false
      AND m.sender_name IS NOT NULL
      AND btrim(m.sender_name) <> ''
    ORDER BY COALESCE(m.sent_at, m.created_at) DESC
    LIMIT 1),
  NULLIF(btrim(COALESCE(c.contact_phone, '')), ''),
  'Conversation #' || c.chatwoot_conversation_id
)
"""

# True when lead_name fell through to phone/id — the UI renders those muted so a
# phone number is never mistaken for a name.
LEAD_NAME_IS_FALLBACK_EXPR = """
NOT EXISTS (
  SELECT 1 FROM messages m
   WHERE m.conversation_id = c.id
     AND m.sender_type = 'contact'
     AND m.is_private = false
     AND m.sender_name IS NOT NULL
     AND btrim(m.sender_name) <> ''
)
"""

# ---------------------------------------------------------------------------
# §4.7 — takeover_at
# ---------------------------------------------------------------------------
# sender_type='user' on an *outbound* message is written at exactly one place —
# chatwoot.py:731, the human-takeover branch. is_private excludes tag command
# notes, which chatwoot.py:671 also writes as sender_type='user'.
TAKEOVER_AT_EXPR = """
(SELECT MIN(COALESCE(m.sent_at, m.created_at))
   FROM messages m
  WHERE m.conversation_id = c.id
    AND m.message_type = 'outbound'
    AND m.sender_type = 'user'
    AND m.is_private = false)
"""

# ---------------------------------------------------------------------------
# §4.8 — escalated_at
# ---------------------------------------------------------------------------
FATAL_LOG_AT_EXPR = """
(SELECT MAX(l.created_at)
   FROM chatbot_logs l
  WHERE l.conversation_id = c.id
    AND l.log_level = 'fatal'
    AND l.is_success = false)
"""

ESCALATED_AT_EXPR = f"COALESCE({FATAL_LOG_AT_EXPR}, c.last_updated_at)"

# False when the fallback fired (RecEngine escalations write no log — spec G5), so
# the UI can mark the timestamp as approximate rather than presenting a loose
# bound as exact.
ESCALATED_AT_EXACT_EXPR = f"({FATAL_LOG_AT_EXPR}) IS NOT NULL"

# ---------------------------------------------------------------------------
# §4.1 — status
# ---------------------------------------------------------------------------
# $1 = stale_hours. Order is strict; first match wins.
#
# Precedence notes:
#  - completed / human_needed / stopped are terminal and beat the error branches.
#    A conversation that errored and *then* escalated is purple, not red: the
#    escalation is the outcome. Its error stays visible in its log rows.
#  - 'outbound_first' abstains need no branch — chatwoot.py sets stopped (:730)
#    before the abstain reason (:733), so they land on human_interruption, which
#    is correct: a human agent sent the first message.
#  - 'prior_history' abstains are the bot correctly declining a pre-existing
#    thread. They are not_run and are excluded from percentage denominators.
STATUS_EXPR = """
CASE
  WHEN c.flow_state = 'completed'    THEN 'success'
  WHEN c.flow_state = 'human_needed' THEN 'human_needed'
  WHEN c.flow_state = 'stopped'      THEN 'human_interruption'
  WHEN c.bot_enabled = false
       AND c.infogatherer_abstain_reason = 'backfill_failed' THEN 'failed'
  WHEN EXISTS (SELECT 1 FROM chatbot_logs l
                WHERE l.conversation_id = c.id
                  AND l.log_level IN ('error','fatal'))       THEN 'failed'
  WHEN c.flow_state IN ('new','awaiting_university',
                        'awaiting_university_clarification',
                        'awaiting_campus_clarification',
                        'awaiting_gender','recengine_running')
       AND COALESCE(c.last_message_at, c.created_at)
           < now() - make_interval(hours => $1)                THEN 'failed'
  WHEN c.bot_enabled = false
       AND c.infogatherer_abstain_reason = 'prior_history'     THEN 'not_run'
  ELSE 'in_progress'
END
"""

LAST_ACTIVITY_EXPR = "COALESCE(c.last_message_at, c.last_updated_at, c.created_at)"

# ---------------------------------------------------------------------------
# §4.4 — failure attribution inputs
# ---------------------------------------------------------------------------
# The most recent error/fatal log, exposed as three scalars so resolve_failure_reason()
# stays a pure function.
FAILURE_LOG_CTE = """
failure_log AS (
  SELECT DISTINCT ON (l.conversation_id)
         l.conversation_id,
         l.explanation    AS failure_log_explanation,
         l.internal_class AS failure_log_internal_class,
         l.status_code    AS failure_log_status_code,
         l.from_state     AS failure_log_from_state,
         l.created_at     AS failure_log_at
    FROM chatbot_logs l
   WHERE l.log_level IN ('error','fatal')
   ORDER BY l.conversation_id, l.created_at DESC
)
"""

# Latest RecEngine attempt, for the escalations that write no chatbot_logs row.
REC_ENGINE_CTE = """
rec_engine AS (
  SELECT DISTINCT ON (r.conversation_id)
         r.conversation_id,
         r.status         AS rec_engine_status,
         r.status_code    AS rec_engine_status_code,
         r.network_status AS rec_engine_network_status
    FROM rec_engine_logs r
   ORDER BY r.conversation_id, r.created_at DESC
)
"""

# ---------------------------------------------------------------------------
# Base CTE — every endpoint builds on this
# ---------------------------------------------------------------------------
# $1 = stale_hours.
BASE_CTE = f"""
WITH {FAILURE_LOG_CTE},
     {REC_ENGINE_CTE},
base AS (
  SELECT
    c.id,
    c.chatwoot_conversation_id,
    c.flow_state,
    c.contact_phone,
    c.labels,
    c.gender,
    c.university_id,
    c.ilgili_otel,
    c.bot_enabled,
    c.infogatherer_abstain_reason,
    c.reprompt_count,
    c.clarification_attempt,
    c.auto_run_count,
    c.manual_run_count,
    c.created_at,
    c.last_updated_at,
    c.last_message_at,
    {LEAD_NAME_EXPR}             AS lead_name,
    {LEAD_NAME_IS_FALLBACK_EXPR} AS lead_name_is_fallback,
    {TAKEOVER_AT_EXPR}           AS takeover_at,
    {ESCALATED_AT_EXPR}          AS escalated_at,
    {ESCALATED_AT_EXACT_EXPR}    AS escalated_at_exact,
    {STATUS_EXPR}                AS status,
    {LAST_ACTIVITY_EXPR}         AS last_activity_at,
    fl.failure_log_explanation,
    fl.failure_log_internal_class,
    fl.failure_log_status_code,
    fl.failure_log_from_state,
    fl.failure_log_at,
    re.rec_engine_status,
    re.rec_engine_status_code,
    re.rec_engine_network_status
  FROM conversations c
  LEFT JOIN failure_log fl ON fl.conversation_id = c.id
  LEFT JOIN rec_engine  re ON re.conversation_id = c.id
)
"""

# ---------------------------------------------------------------------------
# Conversation list (spec §5.2)
# ---------------------------------------------------------------------------
COUNTS_CTE = """
counted AS (
  SELECT b.*,
    (SELECT count(*) FROM messages m
      WHERE m.conversation_id = b.id AND m.is_private = false) AS message_count,
    (SELECT count(*) FROM chatbot_logs l
      WHERE l.conversation_id = b.id)                          AS log_count
  FROM base b
)
"""

SORT_COLUMNS: dict[str, str] = {
    "last_activity": "last_activity_at",
    "created": "created_at",
    "name": "lead_name",
    "cwid": "chatwoot_conversation_id",
}


def conversations_query(
    *,
    where_sql: str,
    sort: str,
    direction: str,
    limit_param: int,
    offset_param: int,
) -> str:
    """
    Assemble the conversation list query.

    sort/direction are looked up in SORT_COLUMNS and a two-value whitelist — they
    are identifiers and cannot be bound as parameters, so they must never come
    from user input unvalidated. Everything user-supplied travels through
    `where_sql` as $n placeholders.
    """
    sort_column = SORT_COLUMNS[sort]
    direction_sql = "ASC" if direction == "asc" else "DESC"
    return f"""
{BASE_CTE},
{COUNTS_CTE}
SELECT *, count(*) OVER () AS total_count
  FROM counted
 WHERE {where_sql}
 ORDER BY {sort_column} {direction_sql} NULLS LAST, chatwoot_conversation_id DESC
 LIMIT ${limit_param} OFFSET ${offset_param}
"""


CONVERSATION_DETAIL_QUERY = f"""
{BASE_CTE},
{COUNTS_CTE}
SELECT counted.*,
       u.name AS university_name
  FROM counted
  LEFT JOIN universities u ON u.id = counted.university_id
 WHERE counted.chatwoot_conversation_id = $2
"""

# ---------------------------------------------------------------------------
# Statistics (spec §5.8, §5.9)
# ---------------------------------------------------------------------------
STATUS_COUNTS_QUERY = f"""
{BASE_CTE}
SELECT status, count(*) AS n FROM base GROUP BY status
"""

# "Successful until interruption": interrupted with no error/fatal log written
# before the takeover. A NULL takeover_at cannot be cleanly attributed, so it is
# counted as dirty rather than silently inflating the clean number.
CLEAN_INTERRUPTION_QUERY = f"""
{BASE_CTE}
SELECT
  count(*) FILTER (
    WHERE b.takeover_at IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM chatbot_logs l
         WHERE l.conversation_id = b.id
           AND l.log_level IN ('error','fatal')
           AND l.created_at < b.takeover_at)
  ) AS clean_count,
  count(*) AS total_interrupted
FROM base b
WHERE b.status = 'human_interruption'
"""

# Rows feeding the three breakdowns — grouped in Python so origin_flow_state() and
# failure_signature() have exactly one implementation.
BREAKDOWN_ROWS_QUERY = f"""
{BASE_CTE}
SELECT b.id, b.status, b.flow_state,
       b.failure_log_explanation, b.failure_log_internal_class,
       b.failure_log_status_code, b.failure_log_from_state,
       b.rec_engine_status, b.rec_engine_status_code, b.rec_engine_network_status
  FROM base b
 WHERE b.status IN ('failed','human_needed')
"""

# ---------------------------------------------------------------------------
# Human-needed triggers (spec §5.10)
# ---------------------------------------------------------------------------
# The last inbound, non-private message at or before the escalation.
HUMAN_NEEDED_TRIGGERS_QUERY = f"""
{BASE_CTE}
SELECT b.id,
       b.chatwoot_conversation_id,
       b.lead_name,
       t.content,
       COALESCE(t.sent_at, t.created_at) AS sent_at
  FROM base b
  LEFT JOIN LATERAL (
    SELECT m.content, m.sent_at, m.created_at
      FROM messages m
     WHERE m.conversation_id = b.id
       AND m.message_type = 'inbound'
       AND m.is_private = false
       AND COALESCE(m.sent_at, m.created_at) <= b.escalated_at
     ORDER BY COALESCE(m.sent_at, m.created_at) DESC
     LIMIT 1
  ) t ON true
 WHERE b.status = 'human_needed'
"""

# ---------------------------------------------------------------------------
# Logs (spec §5.4, §5.7)
# ---------------------------------------------------------------------------
LOG_COLUMNS = """
  l.id, l.created_at, l.conversation_id, l.operation_layer, l.which_run,
  l.from_state, l.to_state, l.log_level, l.is_success, l.status_code,
  l.internal_class, l.network_status, l.database_status, l.explanation
"""

CONVERSATION_LOGS_QUERY = f"""
SELECT {LOG_COLUMNS}
  FROM chatbot_logs l
 WHERE l.conversation_id = $1
 ORDER BY l.created_at ASC
"""


def logs_query(*, where_sql: str, limit_param: int, offset_param: int) -> str:
    return f"""
SELECT {LOG_COLUMNS},
       c.chatwoot_conversation_id,
       count(*) OVER () AS total_count
  FROM chatbot_logs l
  LEFT JOIN conversations c ON c.id = l.conversation_id
 WHERE {where_sql}
 ORDER BY l.created_at DESC, l.id DESC
 LIMIT ${limit_param} OFFSET ${offset_param}
"""


LOG_DETAIL_QUERY = f"""
SELECT {LOG_COLUMNS}, c.chatwoot_conversation_id
  FROM chatbot_logs l
  LEFT JOIN conversations c ON c.id = l.conversation_id
 WHERE l.id = $1
"""

# Context around a log row. chatbot_logs.created_at and messages.created_at are
# both pipeline-persist clocks; messages.sent_at is Chatwoot's send clock and runs
# seconds earlier. Bracketing must use created_at or rows land on the wrong side.
LOG_CONTEXT_BEFORE_QUERY = """
SELECT m.id, m.chatwoot_message_id, m.content, m.message_type, m.sender_type,
       m.sender_name, m.is_private, m.sent_at, m.created_at
  FROM messages m
 WHERE m.conversation_id = $1 AND m.created_at <= $2
 ORDER BY m.created_at DESC
 LIMIT 3
"""

LOG_CONTEXT_AFTER_QUERY = """
SELECT m.id, m.chatwoot_message_id, m.content, m.message_type, m.sender_type,
       m.sender_name, m.is_private, m.sent_at, m.created_at
  FROM messages m
 WHERE m.conversation_id = $1 AND m.created_at > $2
 ORDER BY m.created_at ASC
 LIMIT 3
"""

# ---------------------------------------------------------------------------
# Transcript (spec §5.6)
# ---------------------------------------------------------------------------
# Displayed in send order; markers are positioned against created_at separately.
CONVERSATION_MESSAGES_QUERY = """
SELECT m.id, m.chatwoot_message_id, m.content, m.message_type, m.sender_type,
       m.sender_id, m.sender_name, m.is_private, m.sent_at, m.created_at
  FROM messages m
 WHERE m.conversation_id = $1
 ORDER BY COALESCE(m.sent_at, m.created_at) ASC, m.chatwoot_message_id ASC
"""

# The agent message that stopped the bot, for the human-interruption marker text.
TAKEOVER_MESSAGE_QUERY = """
SELECT m.id, m.sender_name, m.content, m.sent_at, m.created_at
  FROM messages m
 WHERE m.conversation_id = $1
   AND m.message_type = 'outbound'
   AND m.sender_type = 'user'
   AND m.is_private = false
 ORDER BY COALESCE(m.sent_at, m.created_at) ASC
 LIMIT 1
"""
