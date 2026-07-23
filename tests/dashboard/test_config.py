"""
Regression tests for dashboard configuration loading.

The bug these pin down: app.config.Settings sets extra='forbid', and
pydantic-settings validates the entire .env file — so adding the documented
DASHBOARD_* keys to .env raised ValidationError at import time and took the
whole app down, webhooks included.

The second half: pydantic-settings loads .env into the Settings object but does
NOT export into os.environ, so reading only os.environ made credentials written
to .env invisible and the dashboard 503'd while looking configured.
"""
from __future__ import annotations

import pytest

from dashboard.api.config import DEFAULT_STALE_HOURS, get_dashboard_settings


def test_settings_accepts_dashboard_keys_from_env_file(tmp_path, monkeypatch):
    """A .env containing DASHBOARD_* must not break Settings construction."""
    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://u:p@h:5432/d\n"
        "CHATWOOT_BASE_URL=https://example.invalid\n"
        "CHATWOOT_API_TOKEN=t\n"
        "CHATWOOT_ACCOUNT_ID=1\n"
        "CHATWOOT_WEBHOOK_SECRET=s\n"
        "CHATWOOT_BOT_AGENT_ID=9\n"
        "INTERNAL_SHARED_SECRET=i\n"
        "DASHBOARD_USER=someone\n"
        "DASHBOARD_PASSWORD=secret\n"
        "DASHBOARD_STALE_HOURS=48\n"
    )
    # Environment vars would shadow the file; clear them so the file is the source.
    for name in ("DASHBOARD_USER", "DASHBOARD_PASSWORD", "DASHBOARD_STALE_HOURS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=str(env_file))

    assert settings.dashboard_user == "someone"
    assert settings.dashboard_password == "secret"
    assert settings.dashboard_stale_hours == 48


def test_settings_still_rejects_genuinely_unknown_keys(tmp_path):
    """extra='forbid' stays in force — it catches typo'd config."""
    from pydantic import ValidationError

    from app.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://u:p@h:5432/d\n"
        "CHATWOOT_BASE_URL=https://example.invalid\n"
        "CHATWOOT_API_TOKEN=t\n"
        "CHATWOOT_ACCOUNT_ID=1\n"
        "CHATWOOT_WEBHOOK_SECRET=s\n"
        "CHATWOOT_BOT_AGENT_ID=9\n"
        "INTERNAL_SHARED_SECRET=i\n"
        "DASHBOARD_USR=typo\n"
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=str(env_file))


def test_dashboard_settings_read_from_env_vars(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "env-user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "env-pass")
    monkeypatch.setenv("DASHBOARD_STALE_HOURS", "12")

    resolved = get_dashboard_settings()
    assert resolved.user == "env-user"
    assert resolved.password == "env-pass"
    assert resolved.stale_hours == 12
    assert resolved.auth_configured is True


def test_dashboard_settings_fall_back_to_dotenv_values(monkeypatch):
    """
    Credentials present only in .env (so only on the Settings object) must be
    found — this is the path that made a configured dashboard return 503.
    """
    from app.config import settings

    for name in ("DASHBOARD_USER", "DASHBOARD_PASSWORD", "DASHBOARD_STALE_HOURS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "dashboard_user", "dotenv-user", raising=False)
    monkeypatch.setattr(settings, "dashboard_password", "dotenv-pass", raising=False)
    monkeypatch.setattr(settings, "dashboard_stale_hours", 36, raising=False)

    resolved = get_dashboard_settings()
    assert resolved.user == "dotenv-user"
    assert resolved.password == "dotenv-pass"
    assert resolved.stale_hours == 36


def test_env_var_wins_over_dotenv(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_user", "dotenv-user", raising=False)
    monkeypatch.setenv("DASHBOARD_USER", "env-user")
    assert get_dashboard_settings().user == "env-user"


def test_unconfigured_when_both_layers_empty(monkeypatch):
    from app.config import settings

    for name in ("DASHBOARD_USER", "DASHBOARD_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "dashboard_user", None, raising=False)
    monkeypatch.setattr(settings, "dashboard_password", None, raising=False)

    assert get_dashboard_settings().auth_configured is False


def test_blank_values_count_as_unconfigured(monkeypatch):
    """An empty string must fail closed, not authenticate everyone."""
    from app.config import settings

    monkeypatch.setenv("DASHBOARD_USER", "   ")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setattr(settings, "dashboard_user", None, raising=False)
    monkeypatch.setattr(settings, "dashboard_password", None, raising=False)

    assert get_dashboard_settings().auth_configured is False


@pytest.mark.parametrize("value", ["not-a-number", "0", "-5", ""])
def test_invalid_stale_hours_falls_back_to_default(monkeypatch, value):
    from app.config import settings

    monkeypatch.setenv("DASHBOARD_STALE_HOURS", value)
    monkeypatch.setattr(settings, "dashboard_stale_hours", DEFAULT_STALE_HOURS, raising=False)
    assert get_dashboard_settings().stale_hours == DEFAULT_STALE_HOURS
