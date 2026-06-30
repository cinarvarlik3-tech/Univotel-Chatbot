import logging
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


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

    # TagAssigner — Gemini
    model_id: str = "gemini-2.5-flash-lite"
    gemini_api_key: Optional[str] = None

    # TagAssigner — batch webhook (Standard Webhooks symmetric secret, base64-encoded)
    gemini_webhook_secret: Optional[str] = None
    # JWKS URL for asymmetric (dynamic) webhook verification; fetched at first use
    gemini_webhook_jwks_url: str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"

    # TagAssigner — when False, idle-scan and nightly-batch auto-runs are disabled.
    # Manual triggers (private "tag" note or "tag" label in Chatwoot) still work.
    tagassigner_auto_runs: bool = True

    @field_validator("database_url")
    @classmethod
    def database_url_must_be_postgres(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    model_config = {"env_file": ".env", "case_sensitive": False}


settings = Settings()

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

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
