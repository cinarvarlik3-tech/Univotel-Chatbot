-- 001_create_core_tables.sql
-- Creates all new tables required by the Univotel Chatbot (V0).
-- Requires hotels, universities, hotel_accessible_universities to exist first.
-- On production Supabase those are already present.
-- On a fresh DB run 000_create_base_tables.sql first.

CREATE TABLE IF NOT EXISTS university_aliases (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id uuid REFERENCES universities(id) NOT NULL,
    alias       text UNIQUE NOT NULL,
    created_at  timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canned_responses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz DEFAULT now(),
    last_updated_at timestamptz DEFAULT now(),
    short_code      text UNIQUE NOT NULL,
    content         text NOT NULL
);

CREATE TABLE IF NOT EXISTS chatbot_logs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       timestamptz DEFAULT now(),
    conversation_id  uuid,
    operation_layer  text CHECK (operation_layer IN ('infoGatherer','recEngine','tagAssigner','fallBack')),
    which_run        text CHECK (which_run IN ('contextRun','outputRun')),
    from_state       text,
    to_state         text,
    log_level        text CHECK (log_level IN ('info','warn','error','fatal')),
    is_success       boolean,
    status_code      text,
    internal_class   text,
    network_status   text CHECK (network_status IN ('success','timeout','econnrefused','enotfound','econnreset','ssl_err')),
    database_status  text CHECK (database_status IN ('success','db_conn_fail','db_dup_key','db_lock_timeout','disk_full','out_of_memory')),
    explanation      text
);

CREATE TABLE IF NOT EXISTS conversations (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chatwoot_conversation_id int4 UNIQUE NOT NULL,
    created_at               timestamptz DEFAULT now(),
    last_updated_at          timestamptz DEFAULT now(),
    last_processed_at        timestamptz,
    last_processed_log_id    uuid REFERENCES chatbot_logs(id),
    flow_state               text NOT NULL DEFAULT 'new'
        CHECK (flow_state IN (
            'new','awaiting_university','awaiting_university_clarification',
            'awaiting_gender','recengine_running','completed',
            'human_needed','stopped'
        )),
    labels                   text[] DEFAULT '{}',
    university_id            uuid REFERENCES universities(id),
    gender                   text CHECK (gender IN ('male','female')),
    custom_attributes        jsonb DEFAULT '{}',
    messages_since_last_run  int4 DEFAULT 0,
    time_since_last_run      interval,
    daily_run_count          int4 DEFAULT 0,
    reprompt_count           int4 DEFAULT 0,
    last_reprompt_sent_at    timestamptz
);

-- Add FK now that conversations exists
ALTER TABLE chatbot_logs
    ADD CONSTRAINT chatbot_logs_conversation_id_fkey
    FOREIGN KEY (conversation_id) REFERENCES conversations(id);

CREATE TABLE IF NOT EXISTS messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     uuid REFERENCES conversations(id) NOT NULL,
    created_at          timestamptz DEFAULT now(),
    last_processed_at   timestamptz,
    log_id              uuid REFERENCES chatbot_logs(id),
    chatwoot_message_id int4 UNIQUE NOT NULL,
    content             text,
    message_type        text CHECK (message_type IN ('inbound','outbound')),
    sender_type         text CHECK (sender_type IN ('user','contact','infoGatherer','fallBack')),
    sender_id           text,
    sender_name         text,
    is_private          boolean DEFAULT false
);

CREATE TABLE IF NOT EXISTS rec_engine_logs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       timestamptz DEFAULT now(),
    conversation_id  uuid REFERENCES conversations(id) NOT NULL,
    idempotency_key  uuid UNIQUE NOT NULL,
    status           text NOT NULL CHECK (status IN ('processing','success','failed')),
    hotel_rec        uuid REFERENCES hotels(id),
    status_code      text,
    network_status   text,
    database_status  text
);

CREATE TABLE IF NOT EXISTS response_schemas (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hotel_id     uuid REFERENCES hotels(id) NOT NULL,
    response_id  uuid REFERENCES canned_responses(id) NOT NULL,
    sending_order int4 NOT NULL,
    UNIQUE (hotel_id, sending_order)
);
