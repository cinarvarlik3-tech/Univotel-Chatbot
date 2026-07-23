-- 033_dashboard_notes.sql
-- Per-lead notes taken from the dashboard (DASHBOARD_SPEC.md — Notes addition).
--
-- This is the ONLY table the dashboard writes to. Everything else in the dashboard
-- is read-only against the bot's own tables; notes are dashboard-owned annotations
-- and never touch conversations / messages / Chatwoot.
--
-- Two note types, both scoped to a conversation (a "lead"):
--   'log'          — shown in the conversation's Logs panel, rendered as a log entry.
--   'conversation' — shown in the conversation's transcript, rendered like a
--                    Chatwoot private note.
--
-- A note can be resolved and unresolved any number of times; an unresolved note of
-- either type puts a yellow dot on the conversation's table row.

CREATE TABLE IF NOT EXISTS dashboard_notes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    note_type       text NOT NULL CHECK (note_type IN ('log', 'conversation')),
    body            text NOT NULL CHECK (btrim(body) <> ''),
    resolved        boolean NOT NULL DEFAULT false,
    author          text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz
);

-- Per-conversation note lists, ordered oldest-first for the timeline.
CREATE INDEX IF NOT EXISTS idx_dashboard_notes_conversation_created
    ON dashboard_notes (conversation_id, created_at);

-- The yellow-dot lookup asks "does this conversation have any unresolved note?"
-- for every row of the conversations table.
CREATE INDEX IF NOT EXISTS idx_dashboard_notes_unresolved
    ON dashboard_notes (conversation_id)
    WHERE resolved = false;
