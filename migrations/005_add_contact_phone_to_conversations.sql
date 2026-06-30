-- 005_add_contact_phone_to_conversations.sql
-- Stores the contact's normalized (digits-only) phone number on the conversation row.
-- Required for TESTING_LIMITATIONS_MODE to filter background tasks (reprompt sweep, etc.)
-- against the same allowlist used at the webhook entry point.

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS contact_phone text;

-- Index speeds up the testing-mode filter in get_conversations_awaiting_reprompt.
CREATE INDEX IF NOT EXISTS idx_conversations_contact_phone ON conversations (contact_phone);
