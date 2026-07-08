from __future__ import annotations
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Hotel(BaseModel):
    id: uuid.UUID
    name: str
    gender_scope: Optional[str] = None
    priority_score: Optional[int] = None
    is_visible: bool = True


class University(BaseModel):
    id: uuid.UUID
    name: str
    university_short_name: Optional[str] = None


class OutOfCityUniversity(BaseModel):
    id: uuid.UUID
    name: str
    short_name: Optional[str] = None
    city: str


class UniversityAlias(BaseModel):
    id: uuid.UUID
    alias: str
    university_id: Optional[uuid.UUID] = None
    parent_university_id: Optional[uuid.UUID] = None


class Conversation(BaseModel):
    id: uuid.UUID
    chatwoot_conversation_id: int
    flow_state: str
    university_id: Optional[uuid.UUID] = None
    gender: Optional[str] = None
    contact_phone: Optional[str] = None
    reprompt_count: int = 0
    last_reprompt_sent_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    messages_since_last_run: int = 0
    auto_run_count: int = 0
    manual_run_count: int = 0
    labels: list[str] = []
    # Parent-university escalation — set while awaiting campus clarification
    pending_parent_university_id: Optional[uuid.UUID] = None
    clarification_attempt: int = 0
    # Chatwoot custom-attribute columns
    ilgili_otel: Optional[str] = None
    tasinma_tarihi: Optional[date] = None
    kayip_nedeni: Optional[str] = None
    oda_tiipi: Optional[str] = None
    butce: Optional[str] = None
    ilgili_otel_set_at: Optional[datetime] = None
    ilgili_otel_set_by: Optional[str] = None
    university_set_at: Optional[datetime] = None
    university_set_by: Optional[str] = None
    gender_set_at: Optional[datetime] = None
    gender_set_by: Optional[str] = None
    oda_tiipi_set_at: Optional[datetime] = None
    oda_tiipi_set_by: Optional[str] = None
    info_check_fingerprint: Optional[str] = None
    info_check_added_at: Optional[datetime] = None
    info_check_suppressed_fingerprint: Optional[str] = None
    # Divergence recovery (spec 019)
    bot_enabled: bool = True
    last_divergence_intent: Optional[str] = None
    divergence_repeat_count: int = 0


class DivergenceAction(str, Enum):
    ACTIVATE_FLOW = "activate_flow"
    ANSWER_AND_REANCHOR = "answer_and_reanchor"
    IGNORE = "ignore"
    ESCALATE = "escalate"


class DivergenceRoutingRow(BaseModel):
    intent: str
    flow_state: str
    action: str
    canned_response_id: Optional[uuid.UUID] = None
    canned_response_alt_id: Optional[uuid.UUID] = None


class RoutingDecision(BaseModel):
    action: DivergenceAction
    canned_response_id: Optional[uuid.UUID] = None
    canned_response_alt_id: Optional[uuid.UUID] = None


class Message(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    chatwoot_message_id: int
    content: Optional[str] = None
    message_type: Optional[str] = None
    sender_type: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    is_private: bool = False
    created_at: Optional[datetime] = None


class CannedResponse(BaseModel):
    id: uuid.UUID
    short_code: str
    content: str


class ResponseSchema(BaseModel):
    id: uuid.UUID
    hotel_id: uuid.UUID
    response_id: uuid.UUID
    sending_order: int


class RecEngineLog(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    idempotency_key: uuid.UUID
    status: str
    hotel_rec: Optional[uuid.UUID] = None


class ChatbotLog(BaseModel):
    conversation_id: Optional[uuid.UUID] = None
    operation_layer: Optional[str] = None
    which_run: Optional[str] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    log_level: str = "info"
    is_success: Optional[bool] = None
    status_code: Optional[str] = None
    internal_class: Optional[str] = None
    network_status: Optional[str] = None
    database_status: Optional[str] = None
    explanation: Optional[str] = None


class HotelChatwootLabelMap(BaseModel):
    hotel_id: uuid.UUID
    chatwoot_list_value: str


class UniversityChatwootLabelMap(BaseModel):
    university_id: uuid.UUID
    chatwoot_list_value: str


class ParentUniversity(BaseModel):
    id: uuid.UUID
    name: str
    question: str


class UniversityParentMap(BaseModel):
    university_id: uuid.UUID
    parent_university_id: uuid.UUID
    campus_label: str


class TagAssignerRun(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    trigger_type: Optional[str] = None
    status: str
    gemini_result: Optional[dict] = None
    batch_job_name: Optional[str] = None
    batch_webhook_id: Optional[str] = None


class TagAssignerLog(BaseModel):
    log_id: Optional[uuid.UUID] = None
    run_id: Optional[uuid.UUID] = None
    conversation_id: Optional[uuid.UUID] = None
    request_type: Optional[str] = None
    request_from: Optional[str] = None
    request_to: Optional[str] = None
    is_success: Optional[bool] = None
    status_code: Optional[str] = None
    fail_reason: Optional[str] = None


class TagAssignerQueueItem(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    enqueued_at: Optional[datetime] = None
    status: str
    run_id: Optional[uuid.UUID] = None
    trigger_type: Optional[str] = None
