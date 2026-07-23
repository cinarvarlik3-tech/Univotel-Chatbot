-- 032_dashboard_indexes.sql
-- Indexes supporting the dashboard's per-conversation lookups (DASHBOARD_SPEC.md §11.2).
--
-- Purely additive: no column, constraint, or data changes. Safe to run at any
-- time, and safe to skip — the dashboard is correct without these, just slower
-- once the tables grow past a few thousand rows.
--
-- Note that messages.conversation_id had NO index before this migration, despite
-- being the join key for the running bot as well: has_automation_outbound(),
-- conversation_has_messages(), and get_messages_for_conversation() all filter on
-- it. This helps the pipeline, not only the dashboard.

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id);

-- Transcript ordering and the lead-name lookup both read newest-first per
-- conversation.
CREATE INDEX IF NOT EXISTS idx_messages_conversation_sent
    ON messages (conversation_id, sent_at DESC);

-- Per-conversation log lists and the failure-attribution DISTINCT ON.
CREATE INDEX IF NOT EXISTS idx_chatbot_logs_conversation_created
    ON chatbot_logs (conversation_id, created_at DESC);

-- Partial index: the status derivation asks "does this conversation have any
-- error/fatal log?" on every row of every listing.
CREATE INDEX IF NOT EXISTS idx_chatbot_logs_level
    ON chatbot_logs (log_level)
    WHERE log_level IN ('error', 'fatal');

CREATE INDEX IF NOT EXISTS idx_conversations_flow_state
    ON conversations (flow_state);

-- Default sort order for the conversations table.
CREATE INDEX IF NOT EXISTS idx_conversations_last_message_at
    ON conversations (last_message_at DESC);

-- Failure attribution joins the latest rec_engine_logs row per conversation.
CREATE INDEX IF NOT EXISTS idx_rec_engine_logs_conversation_created
    ON rec_engine_logs (conversation_id, created_at DESC);
