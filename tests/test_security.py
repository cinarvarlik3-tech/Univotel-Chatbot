"""Unit tests for the security layer (app/security.py)."""
import hashlib
import hmac
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# verify_internal_secret
# ---------------------------------------------------------------------------

def test_internal_secret_valid():
    with patch("app.security.settings") as mock_settings:
        mock_settings.internal_shared_secret = "correct_secret"
        from app.security import verify_internal_secret
        verify_internal_secret("correct_secret")  # must not raise


def test_internal_secret_wrong():
    with patch("app.security.settings") as mock_settings:
        mock_settings.internal_shared_secret = "correct_secret"
        from app.security import verify_internal_secret
        with pytest.raises(HTTPException) as exc:
            verify_internal_secret("wrong_secret")
        assert exc.value.status_code == 401


def test_internal_secret_missing():
    with patch("app.security.settings") as mock_settings:
        mock_settings.internal_shared_secret = "correct_secret"
        from app.security import verify_internal_secret
        with pytest.raises(HTTPException) as exc:
            verify_internal_secret(None)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# verify_chatwoot_hmac (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chatwoot_hmac_valid():
    secret = "test_secret"
    body = b'{"event":"message_created"}'
    timestamp = "1700000000"
    signed_payload = timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    mock_request = AsyncMock()
    mock_request.headers = {
        "X-Chatwoot-Timestamp": timestamp,
        "X-Chatwoot-Signature": f"sha256={digest}",
    }
    mock_request.body = AsyncMock(return_value=body)

    with patch("app.security.settings") as mock_settings:
        mock_settings.chatwoot_webhook_secret = secret
        from app.security import verify_chatwoot_hmac
        await verify_chatwoot_hmac(mock_request)  # must not raise


@pytest.mark.asyncio
async def test_chatwoot_hmac_invalid():
    secret = "test_secret"
    body = b'{"event":"message_created"}'
    timestamp = "1700000000"

    mock_request = AsyncMock()
    mock_request.headers = {
        "X-Chatwoot-Timestamp": timestamp,
        "X-Chatwoot-Signature": "sha256=bad_sig",
    }
    mock_request.body = AsyncMock(return_value=body)

    with patch("app.security.settings") as mock_settings:
        mock_settings.chatwoot_webhook_secret = secret
        from app.security import verify_chatwoot_hmac
        with pytest.raises(HTTPException) as exc:
            await verify_chatwoot_hmac(mock_request)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_chatwoot_hmac_missing_header():
    mock_request = AsyncMock()
    mock_request.headers = {}
    mock_request.body = AsyncMock(return_value=b"body")

    with patch("app.security.settings") as mock_settings:
        mock_settings.chatwoot_webhook_secret = "secret"
        from app.security import verify_chatwoot_hmac
        with pytest.raises(HTTPException) as exc:
            await verify_chatwoot_hmac(mock_request)
        assert exc.value.status_code == 401
