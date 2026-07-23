"""
Shared fixtures for the dashboard API tests.

The app is imported once with the DB pool stubbed out — app.main's lifespan opens
a real connection pool, so these tests drive the ASGI app directly without
triggering startup.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import pytest

TEST_USER = "dash-test-user"
TEST_PASSWORD = "dash-test-password"


@pytest.fixture
def auth_header() -> dict[str, str]:
    token = base64.b64encode(f"{TEST_USER}:{TEST_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def dashboard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHBOARD_USER", TEST_USER)
    monkeypatch.setenv("DASHBOARD_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("DASHBOARD_STALE_HOURS", "24")


@pytest.fixture
def no_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Genuinely unconfigured — both layers cleared.

    Clearing only os.environ is not enough: settings falls back to app.config,
    which pydantic-settings populates from the developer's real .env.
    """
    from app.config import settings

    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setattr(settings, "dashboard_user", None, raising=False)
    monkeypatch.setattr(settings, "dashboard_password", None, raising=False)


class FakeRecord(dict):
    """asyncpg.Record stand-in: dict access plus .keys(), which the row builders use."""

    def keys(self):  # noqa: D102
        return super().keys()


class FakePool:
    """
    Records every statement and replays canned results.

    Queued as a list of results consumed in call order, so a test asserts the
    sequence the endpoint actually issues.
    """

    def __init__(self) -> None:
        self.fetch_results: list[list[FakeRecord]] = []
        self.fetchrow_results: list[FakeRecord | None] = []
        self.fetchval_results: list[Any] = []
        self.statements: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.statements.append(query)
        return self.fetch_results.pop(0) if self.fetch_results else []

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.statements.append(query)
        return self.fetchrow_results.pop(0) if self.fetchrow_results else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.statements.append(query)
        return self.fetchval_results.pop(0) if self.fetchval_results else None


@pytest.fixture
def fake_pool(monkeypatch: pytest.MonkeyPatch) -> FakePool:
    pool = FakePool()
    monkeypatch.setattr("dashboard.api.queries.get_pool", lambda: pool)
    # notes.py imports get_pool into its own namespace (the dashboard's only
    # write path); patch it too so note lookups hit the fake pool.
    monkeypatch.setattr("dashboard.api.notes.get_pool", lambda: pool)
    return pool


@pytest.fixture(scope="session")
def app():
    """
    app.main imported with config satisfied.

    Settings requires a set of env vars at import time; filling them here keeps the
    import from raising without touching the developer's real .env.
    """
    os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
    os.environ.setdefault("CHATWOOT_BASE_URL", "https://example.invalid")
    os.environ.setdefault("CHATWOOT_API_TOKEN", "test")
    os.environ.setdefault("CHATWOOT_ACCOUNT_ID", "1")
    os.environ.setdefault("CHATWOOT_WEBHOOK_SECRET", "test")
    os.environ.setdefault("CHATWOOT_BOT_AGENT_ID", "9")
    os.environ.setdefault("INTERNAL_SHARED_SECRET", "test")

    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    # Context-manager form would run the lifespan and open a real pool.
    return TestClient(app)
