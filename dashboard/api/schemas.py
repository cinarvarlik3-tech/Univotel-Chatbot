"""Pydantic response models for the dashboard API (spec §5)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

ReasonSource = Literal["log", "rec_engine", "inferred", "stale", "unknown"]
BubbleKind = Literal["inbound", "bot", "human", "private"]
MarkerKind = Literal["failure", "human_needed", "human_interruption"]
NoteType = Literal["log", "conversation"]


class Meta(BaseModel):
    stale_hours: int
    flow_states: list[str]
    statuses: list[str]
    log_levels: list[str]
    operation_layers: list[str]
    which_runs: list[str]
    server_time: str


class ConversationRow(BaseModel):
    id: str
    chatwoot_conversation_id: int
    lead_name: str
    lead_name_is_fallback: bool
    flow_state: str
    status: str
    origin_flow_state: str
    failure_reason: Optional[str] = None
    reason_source: ReasonSource = "unknown"
    failure_signature: Optional[str] = None
    message_count: int
    log_count: int
    has_unresolved_note: bool = False
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    takeover_at: Optional[str] = None
    escalated_at: Optional[str] = None
    escalated_at_exact: bool = True


class ConversationList(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[ConversationRow]


class ConversationDetail(ConversationRow):
    university_id: Optional[str] = None
    university_name: Optional[str] = None
    gender: Optional[str] = None
    ilgili_otel: Optional[str] = None
    labels: list[str] = []
    contact_phone: Optional[str] = None
    bot_enabled: bool = True
    infogatherer_abstain_reason: Optional[str] = None
    reprompt_count: int = 0
    clarification_attempt: int = 0
    auto_run_count: int = 0
    manual_run_count: int = 0


class ConversationRef(BaseModel):
    """Minimal conversation identity carried alongside panel payloads."""
    id: str
    chatwoot_conversation_id: int
    lead_name: str
    status: str
    flow_state: str


class Note(BaseModel):
    id: str
    conversation_id: str
    chatwoot_conversation_id: int
    note_type: NoteType
    body: str
    resolved: bool = False
    author: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    resolved_at: Optional[str] = None


class NoteList(BaseModel):
    conversation: ConversationRef
    rows: list[Note]


class NoteCreate(BaseModel):
    note_type: NoteType
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Note body cannot be blank")
        return cleaned


class NoteUpdate(BaseModel):
    resolved: bool


class LogRow(BaseModel):
    id: str
    derived: bool = False
    created_at: Optional[str] = None
    conversation_id: Optional[str] = None
    chatwoot_conversation_id: Optional[int] = None
    lead_name: Optional[str] = None
    operation_layer: Optional[str] = None
    which_run: Optional[str] = None
    operation_label: str
    log_level: Optional[str] = None
    is_success: Optional[bool] = None
    log_status: str
    status_code: Optional[str] = None
    internal_class: Optional[str] = None
    signature: Optional[str] = None
    signature_label: Optional[str] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    network_status: Optional[str] = None
    database_status: Optional[str] = None
    explanation: Optional[str] = None


class ConversationLogs(BaseModel):
    conversation: ConversationRef
    rows: list[LogRow]


class LogList(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[LogRow]


class MessageRow(BaseModel):
    id: str
    chatwoot_message_id: Optional[int] = None
    direction: Optional[str] = None
    bubble: BubbleKind
    sender_type: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    content: Optional[str] = None
    is_private: bool = False
    sent_at: Optional[str] = None
    created_at: Optional[str] = None


class FlowMarker(BaseModel):
    kind: MarkerKind
    at: Optional[str] = None
    after_message_id: Optional[str] = None
    label: str
    detail: Optional[str] = None
    log_id: Optional[str] = None


class ConversationMessages(BaseModel):
    conversation: ConversationRef
    messages: list[MessageRow]
    markers: list[FlowMarker]


class LogPayload(BaseModel):
    """
    Phase 1 always reports available=false — chatbot_logs has no payload columns
    (spec G3). The note is rendered in place of an empty JSON block so the absence
    is explained rather than looking like a bug. Spec §12.2 flips this.
    """
    available: bool = False
    note: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    source: Optional[str] = None
    target: Optional[str] = None


class LogContext(BaseModel):
    preceding_messages: list[MessageRow] = []
    following_messages: list[MessageRow] = []


class LogDetail(BaseModel):
    log: LogRow
    conversation: Optional[ConversationRef] = None
    context: LogContext
    payload: LogPayload
    raw: dict[str, Any]


class StatsSummary(BaseModel):
    stale_hours: int
    total_conversations: int
    denominator: int
    counts: dict[str, int]
    percentages: dict[str, Optional[float]]
    clean_interruption_count: int
    dirty_interruption_count: int


class Slice(BaseModel):
    key: str
    label: str
    count: int
    pct: float
    members: Optional[list[dict[str, Any]]] = None


class Breakdown(BaseModel):
    total: int
    slices: list[Slice]


class Breakdowns(BaseModel):
    failures_by_flow_state: Breakdown
    failures_by_signature: Breakdown
    human_needed_by_flow_state: Breakdown


class TriggerConversation(BaseModel):
    chatwoot_conversation_id: int
    lead_name: str
    sent_at: Optional[str] = None


class TriggerRow(BaseModel):
    normalized: str
    display_text: str
    count: int
    conversations: list[TriggerConversation]


class TriggerList(BaseModel):
    total_human_needed: int
    with_trigger: int
    rows: list[TriggerRow]
