"""
Dashboard settings.

Values are declared on app.config.Settings (which forbids extra keys, so they
have to be), but they are read here rather than there so the dashboard's
configuration handling stays in one place.

Two sources, in order:
  1. os.environ — the process environment, which is what Railway sets and what
     tests monkeypatch.
  2. app.config.settings — populated from .env by pydantic-settings, which does
     NOT export into os.environ. Without this fallback, credentials written to
     .env would be invisible here and the dashboard would 503 despite being
     configured.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_STALE_HOURS = 24


def _str_setting(env_name: str, attr: str) -> str:
    raw = os.environ.get(env_name)
    if raw is not None and raw.strip():
        return raw.strip()

    from app.config import settings

    value: Optional[str] = getattr(settings, attr, None)
    return value.strip() if isinstance(value, str) else ""


def _int_setting(env_name: str, attr: str, default: int) -> int:
    raw = (os.environ.get(env_name) or "").strip()
    if raw:
        try:
            parsed = int(raw)
        except ValueError:
            return default
        return parsed if parsed > 0 else default

    from app.config import settings

    value = getattr(settings, attr, None)
    if isinstance(value, int) and value > 0:
        return value
    return default


@dataclass(frozen=True)
class DashboardSettings:
    user: str
    password: str
    stale_hours: int

    @property
    def auth_configured(self) -> bool:
        return bool(self.user and self.password)


def get_dashboard_settings() -> DashboardSettings:
    """
    Read fresh on every call rather than caching at import.

    Tests set these per-case, and a process that imports this module before the
    environment is fully populated should still pick them up.
    """
    return DashboardSettings(
        user=_str_setting("DASHBOARD_USER", "dashboard_user"),
        password=_str_setting("DASHBOARD_PASSWORD", "dashboard_password"),
        stale_hours=_int_setting(
            "DASHBOARD_STALE_HOURS", "dashboard_stale_hours", DEFAULT_STALE_HOURS
        ),
    )
