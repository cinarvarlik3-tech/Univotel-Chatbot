"""
HTTP Basic auth for the dashboard (spec §3.5).

Fail-closed: with DASHBOARD_USER / DASHBOARD_PASSWORD unset, every dashboard route
returns 503. The dashboard serves lead phone numbers and full chat transcripts, so
"unconfigured" must never mean "open", including in local development.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from dashboard.api.config import get_dashboard_settings

logger = logging.getLogger(__name__)

# auto_error=False so a missing header produces our 401-with-challenge rather than
# FastAPI's bare 403, which browsers will not prompt on.
_basic = HTTPBasic(auto_error=False, realm="Univotel Dashboard")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid dashboard credentials",
    headers={"WWW-Authenticate": 'Basic realm="Univotel Dashboard"'},
)


def require_dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    settings = get_dashboard_settings()

    if not settings.auth_configured:
        logger.error(
            "DASHBOARD: DASHBOARD_USER/DASHBOARD_PASSWORD not set — refusing to serve"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Dashboard auth not configured. Set DASHBOARD_USER and "
                "DASHBOARD_PASSWORD."
            ),
        )

    if credentials is None:
        raise _UNAUTHORIZED

    # Compare both fields unconditionally: short-circuiting on a username mismatch
    # would leak which half was wrong through response timing.
    user_ok = hmac.compare_digest(credentials.username, settings.user)
    password_ok = hmac.compare_digest(credentials.password, settings.password)
    if not (user_ok and password_ok):
        raise _UNAUTHORIZED

    return credentials.username
