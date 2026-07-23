/** Response shapes from dashboard/api/schemas.py (DASHBOARD_SPEC.md §5). */

export type Status =
  | 'success'
  | 'failed'
  | 'in_progress'
  | 'human_needed'
  | 'human_interruption'
  | 'not_run';

export type ReasonSource = 'log' | 'rec_engine' | 'inferred' | 'stale' | 'unknown';
export type BubbleKind = 'inbound' | 'bot' | 'human' | 'private';
export type MarkerKind = 'failure' | 'human_needed' | 'human_interruption';

export interface Meta {
  stale_hours: number;
  flow_states: string[];
  statuses: Status[];
  log_levels: string[];
  operation_layers: string[];
  which_runs: string[];
  server_time: string;
}

export interface ConversationRow {
  id: string;
  chatwoot_conversation_id: number;
  lead_name: string;
  lead_name_is_fallback: boolean;
  flow_state: string;
  status: Status;
  origin_flow_state: string;
  failure_reason: string | null;
  reason_source: ReasonSource;
  failure_signature: string | null;
  message_count: number;
  log_count: number;
  created_at: string | null;
  last_activity_at: string | null;
  takeover_at: string | null;
  escalated_at: string | null;
  escalated_at_exact: boolean;
}

export interface ConversationDetail extends ConversationRow {
  university_id: string | null;
  university_name: string | null;
  gender: string | null;
  ilgili_otel: string | null;
  labels: string[];
  contact_phone: string | null;
  bot_enabled: boolean;
  infogatherer_abstain_reason: string | null;
  reprompt_count: number;
  clarification_attempt: number;
  auto_run_count: number;
  manual_run_count: number;
}

export interface ConversationList {
  total: number;
  limit: number;
  offset: number;
  rows: ConversationRow[];
}

export interface ConversationRef {
  id: string;
  chatwoot_conversation_id: number;
  lead_name: string;
  status: Status;
  flow_state: string;
}

export interface LogRow {
  id: string;
  derived: boolean;
  created_at: string | null;
  conversation_id: string | null;
  chatwoot_conversation_id: number | null;
  lead_name: string | null;
  operation_layer: string | null;
  which_run: string | null;
  operation_label: string;
  log_level: string | null;
  is_success: boolean | null;
  log_status: Status;
  status_code: string | null;
  internal_class: string | null;
  signature: string | null;
  signature_label: string | null;
  from_state: string | null;
  to_state: string | null;
  network_status: string | null;
  database_status: string | null;
  explanation: string | null;
}

export interface ConversationLogs {
  conversation: ConversationRef;
  rows: LogRow[];
}

export interface LogList {
  total: number;
  limit: number;
  offset: number;
  rows: LogRow[];
}

export interface MessageRow {
  id: string;
  chatwoot_message_id: number | null;
  direction: string | null;
  bubble: BubbleKind;
  sender_type: string | null;
  sender_id: string | null;
  sender_name: string | null;
  content: string | null;
  is_private: boolean;
  sent_at: string | null;
  created_at: string | null;
}

export interface FlowMarker {
  kind: MarkerKind;
  at: string | null;
  after_message_id: string | null;
  label: string;
  detail: string | null;
  log_id: string | null;
}

export interface ConversationMessages {
  conversation: ConversationRef;
  messages: MessageRow[];
  markers: FlowMarker[];
}

export interface LogPayload {
  available: boolean;
  note: string | null;
  input: unknown;
  output: unknown;
  source: string | null;
  target: string | null;
}

export interface LogDetail {
  log: LogRow;
  conversation: ConversationRef | null;
  context: {
    preceding_messages: MessageRow[];
    following_messages: MessageRow[];
  };
  payload: LogPayload;
  raw: Record<string, unknown>;
}

export interface StatsSummary {
  stale_hours: number;
  total_conversations: number;
  denominator: number;
  counts: Record<Status, number>;
  percentages: {
    failed: number | null;
    human_needed: number | null;
    success: number | null;
    clean_interruption: number | null;
    in_progress: number | null;
  };
  clean_interruption_count: number;
  dirty_interruption_count: number;
}

export interface Slice {
  key: string;
  label: string;
  count: number;
  pct: number;
  members?: { key: string; label: string; count: number }[];
}

export interface Breakdown {
  total: number;
  slices: Slice[];
}

export interface Breakdowns {
  failures_by_flow_state: Breakdown;
  failures_by_signature: Breakdown;
  human_needed_by_flow_state: Breakdown;
}

export interface TriggerRow {
  normalized: string;
  display_text: string;
  count: number;
  conversations: {
    chatwoot_conversation_id: number;
    lead_name: string;
    sent_at: string | null;
  }[];
}

export interface TriggerList {
  total_human_needed: number;
  with_trigger: number;
  rows: TriggerRow[];
}

export interface ConversationFilters {
  status?: Status[];
  flow_state?: string[];
  q?: string;
  from?: string;
  to?: string;
  sort?: 'last_activity' | 'created' | 'name' | 'cwid';
  dir?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export interface LogFilters {
  conversation?: number;
  log_level?: string[];
  is_success?: boolean;
  operation_layer?: string;
  which_run?: string;
  q?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}
