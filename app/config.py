import logging
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator


class Settings(BaseSettings):
    database_url: str
    chatwoot_base_url: str
    chatwoot_api_token: str
    chatwoot_account_id: int
    chatwoot_webhook_secret: str
    chatwoot_bot_agent_id: int
    internal_shared_secret: str
    log_level: str = "info"
    testing_limitations_mode: bool = False
    integrity_check_bypass: bool = False

    # Live testing (Spec 022): bounded real-traffic ingestion; mutually exclusive with testing_limitations_mode.
    live_testing_mode: bool = False
    live_testing_limit: Optional[int] = None

    # When true, suppress all lead-facing messages via send_with_retry (labels/attributes/private notes still write).
    outbound_block: bool = False

    # Live trace dashboard (/diagnostics) — structured events + JSONL for live-test debugging.
    live_trace_enabled: bool = False
    live_trace_jsonl_path: Optional[str] = "logs/live_trace.jsonl"

    # LLM — provider keys (all stored; per-task provider selects which is used)
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # LLM — default model per provider
    model_id: str = "gemini-2.5-flash-lite"  # legacy alias for GEMINI_MODEL_ID
    gemini_model_id: Optional[str] = None
    openai_model_id: str = "gpt-5.4-nano"
    anthropic_model_id: str = "claude-haiku-4-5"

    # LLM — per-task provider selection
    tagassigner_provider: str = "gemini"
    divergence_provider: str = "gemini"

    # LLM — optional per-task model overrides (blank = use <PROVIDER>_MODEL_ID)
    tagassigner_model_id: Optional[str] = None
    divergence_model_id: Optional[str] = None

    # LLM — shared tuning
    llm_temperature: float = 0.0
    llm_reasoning_effort: Optional[str] = None
    llm_max_output_tokens: Optional[int] = None

    # TagAssigner — batch webhook (Standard Webhooks symmetric secret, base64-encoded)
    gemini_webhook_secret: Optional[str] = None
    # JWKS URL for asymmetric (dynamic) webhook verification; fetched at first use
    gemini_webhook_jwks_url: str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"

    # TagAssigner — when False, idle-scan and nightly-batch auto-runs are disabled.
    # Manual triggers (private "tag" note or "tag" label in Chatwoot) still work.
    tagassigner_auto_runs: bool = True

    # Inbound message debounce (Spec 020 Part E). 0 = disabled (process immediately).
    debounce_window_seconds: int = 3

    # Univotel CRM Postgres (read-only import for tag importConvo testing).
    crm_database_url: Optional[str] = None

    @field_validator("database_url")
    @classmethod
    def database_url_must_be_postgres(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    @field_validator("crm_database_url")
    @classmethod
    def crm_database_url_must_be_postgres(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        if not str(v).startswith("postgresql"):
            raise ValueError("CRM_DATABASE_URL must be a PostgreSQL connection string")
        return str(v).strip()

    @field_validator("tagassigner_model_id", "divergence_model_id", "llm_reasoning_effort", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("llm_max_output_tokens", mode="before")
    @classmethod
    def empty_int_to_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def sync_gemini_model_id(self) -> "Settings":
        """MODEL_ID (legacy) populates GEMINI_MODEL_ID when unset."""
        if self.gemini_model_id is None:
            object.__setattr__(self, "gemini_model_id", self.model_id)
        return self

    model_config = {"env_file": ".env", "case_sensitive": False}


settings = Settings()


def validate_config(
    live_testing_mode: bool,
    testing_limitations_mode: bool,
    live_testing_limit: Optional[int],
) -> None:
    """
    Boot-time config rules (Spec 022 Part A). Raises RuntimeError on misconfiguration.
    """
    if live_testing_mode and testing_limitations_mode:
        logger = logging.getLogger(__name__)
        logger.fatal(
            "LIVE_TESTING_MODE and TESTING_LIMITATIONS_MODE cannot both be enabled"
        )
        raise RuntimeError(
            "LIVE_TESTING_MODE and TESTING_LIMITATIONS_MODE cannot both be enabled"
        )
    if live_testing_mode and live_testing_limit is None:
        logger = logging.getLogger(__name__)
        logger.fatal("LIVE_TESTING_MODE is on but LIVE_TESTING_LIMIT is not set")
        raise RuntimeError("LIVE_TESTING_MODE is on but LIVE_TESTING_LIMIT is not set")


# Digits-only phone numbers permitted when testing_limitations_mode = True.
# Single source of truth — imported by both the webhook handler and the DB query layer.
TESTING_PHONE_ALLOWLIST: frozenset[str] = frozenset([
    "905551839644",
    "905445545244",
])

# Chatwoot custom-attribute keys sent to Gemini as read-only context.
# Driven from config so an attribute cleanup is a one-line change here, not a code change.
# Keys must match the actual Chatwoot attribute identifiers exactly.
TAGASSIGNER_ATTRIBUTE_KEYS: list[str] = [
    "ilgili_otel",
    "tasinma_tarihi",
    "kayip_nedeni",
    "oda_tiipi",   # keep the exact Chatwoot key (double-i) — verify against live Chatwoot
    "butce",
]

# Bot-writable custom attributes (Gemini proposes; Router merges — spec 018).
TAGASSIGNER_BOT_WRITABLE_ATTRIBUTES: list[str] = [
    "university",
    "ogrenci_cinsiyet",
    "oda_tiipi",
]

# Chatwoot oda_tiipi list values (live Chatwoot, confirmed 2026-07-06).
TAGASSIGNER_ROOM_TYPE_VALUES: list[str] = [
    "Tek Kişilik",
    "Çift Kişilik",
    "Yurt Tipi",
    "Fark Etmez",
    "Üç Kişilik",
    "Dört Kişilik",
    "Beş Kişilik",
    "1+1",
    "2+1",
    "3+1",
]

INFO_CHECK_TTL_HOURS: int = 48

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
