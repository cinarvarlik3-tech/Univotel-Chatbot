import base64
import hashlib
import hmac
import logging
import time
from fastapi import Request, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


async def verify_chatwoot_hmac(request: Request) -> None:
    """
    Recomputes the Chatwoot HMAC-SHA256 signature and compares with the header.
    Raises HTTP 401 and logs fatal on any mismatch or missing header.
    Must be called before the request body is parsed for any other purpose.
    """
    signature_header = request.headers.get("X-Chatwoot-Signature", "")
    if not signature_header:
        logger.fatal("CHATWOOT_HMAC: missing X-Chatwoot-Signature header — request dropped")
        raise HTTPException(status_code=401, detail="Missing signature")

    timestamp = request.headers.get("X-Chatwoot-Timestamp", "")
    body = await request.body()

    signed_payload = timestamp.encode() + b"." + body
    digest = hmac.new(
        settings.chatwoot_webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    expected = f"sha256={digest}"

    if not hmac.compare_digest(expected, signature_header):
        logger.fatal("CHATWOOT_HMAC: signature mismatch — request dropped")
        raise HTTPException(status_code=401, detail="Invalid signature")


def verify_internal_secret(header_value: str | None) -> None:
    """
    Verifies the X-Internal-Secret header for InfoGatherer <-> RecEngine calls.
    Raises HTTP 401 and logs fatal on any mismatch or missing value.
    """
    if not header_value:
        logger.fatal("INTERNAL_SECRET: missing X-Internal-Secret header — request dropped")
        raise HTTPException(status_code=401, detail="Missing internal secret")

    if not hmac.compare_digest(
        settings.internal_shared_secret.encode(),
        header_value.encode(),
    ):
        logger.fatal("INTERNAL_SECRET: secret mismatch — request dropped")
        raise HTTPException(status_code=401, detail="Invalid internal secret")


async def verify_standard_webhook(request: Request) -> str:
    """
    Verify an inbound Standard Webhooks payload (Gemini batch results).

    Implements the Standard Webhooks spec (svix-compatible):
    - Required headers: webhook-id, webhook-timestamp, webhook-signature
    - Signed content: "{webhook-id}.{webhook-timestamp}.{raw-body}"
    - Signature format: "v1,<base64(HMAC-SHA256(content, key))>" (space-separated for rotation)
    - Replay protection: reject payloads with timestamp > 5 minutes old

    Returns the webhook-id for deduplication by the caller.
    Raises HTTP 401 and logs fatal on any failure.

    Note: this implements symmetric (v1) verification. Dynamic Gemini webhooks use
    asymmetric JWKS (v1a) — that path is wired in batch_client.py Phase 6.
    """
    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not all([webhook_id, webhook_timestamp, webhook_signature]):
        logger.fatal(
            "STANDARD_WEBHOOK: missing required headers (id=%r ts=%r sig=%r) — dropped",
            bool(webhook_id), bool(webhook_timestamp), bool(webhook_signature),
        )
        raise HTTPException(status_code=401, detail="Missing webhook headers")

    try:
        ts = int(webhook_timestamp)
        age_seconds = time.time() - ts
        if abs(age_seconds) > 300:
            logger.fatal(
                "STANDARD_WEBHOOK: timestamp age %ds exceeds 5 min — replay rejected",
                int(age_seconds),
            )
            raise HTTPException(status_code=401, detail="Webhook timestamp too old")
    except ValueError:
        logger.fatal("STANDARD_WEBHOOK: non-integer timestamp header — dropped")
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp")

    if not settings.gemini_webhook_secret:
        logger.fatal("STANDARD_WEBHOOK: GEMINI_WEBHOOK_SECRET not configured — request dropped")
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    body = await request.body()
    signed_content = f"{webhook_id}.{webhook_timestamp}.".encode() + body

    try:
        key_bytes = base64.b64decode(settings.gemini_webhook_secret)
    except Exception:
        logger.fatal("STANDARD_WEBHOOK: GEMINI_WEBHOOK_SECRET is not valid base64 — dropped")
        raise HTTPException(status_code=401, detail="Invalid webhook secret format")

    computed = base64.b64encode(
        hmac.new(key_bytes, signed_content, hashlib.sha256).digest()
    ).decode()

    for entry in webhook_signature.split(" "):
        if not entry.startswith("v1,"):
            continue
        if hmac.compare_digest(entry[3:], computed):
            return webhook_id

    logger.fatal("STANDARD_WEBHOOK: no valid v1 signature matched — request dropped")
    raise HTTPException(status_code=401, detail="Invalid webhook signature")
