"""
Guard on the one edit to existing code (DASHBOARD_SPEC.md §13.4).

mount_dashboard() registers a catch-all. If it ever shadows a bot route, webhooks
start returning HTML instead of processing messages — silently. These tests fail
loudly instead.
"""
from __future__ import annotations

import pytest

from dashboard.api.static import RESERVED_PREFIXES, _is_reserved


def _route_paths(app) -> set[str]:
    return {getattr(route, "path", None) for route in app.routes}


def test_existing_routes_still_registered(app):
    paths = _route_paths(app)
    for expected in (
        "/health",
        "/diagnostics",
        "/diagnostics/flow",
        "/diagnostics/api/stats",
        "/diagnostics/api/events",
        "/diagnostics/api/stream",
        "/webhooks/chatwoot",
        "/internal/recengine/start",
        "/internal/infogatherer/callback",
    ):
        assert expected in paths, f"{expected} disappeared after mount_dashboard()"


def test_catch_all_is_registered_last(app):
    """Anything after the catch-all would be unreachable."""
    catch_all_index = None
    for index, route in enumerate(app.routes):
        if getattr(route, "path", None) == "/{full_path:path}":
            catch_all_index = index
    assert catch_all_index is not None, "SPA catch-all not registered"

    trailing = [
        getattr(route, "path", None)
        for route in app.routes[catch_all_index + 1 :]
        if getattr(route, "path", None)
    ]
    assert trailing == [], f"routes registered after the catch-all: {trailing}"


def test_health_still_answers_json(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_diagnostics_still_serves_its_own_html(client):
    """/diagnostics must not be replaced by the SPA shell."""
    response = client.get("/diagnostics")
    assert response.status_code == 200
    assert "Univotel Live Trace" in response.text
    assert "diagnostics/api/stream" in response.text


def test_diagnostics_flow_preserved(client):
    response = client.get("/diagnostics/flow")
    assert response.status_code == 200
    assert "Pipeline trace by conversation" in response.text


def test_unknown_reserved_path_404s_rather_than_serving_spa(client, dashboard_env, auth_header):
    """A future /webhooks route must 404, not receive index.html."""
    response = client.get("/webhooks/does-not-exist", headers=auth_header)
    assert response.status_code == 404
    assert "<!DOCTYPE html" not in response.text


@pytest.mark.parametrize("path", [
    "/webhooks", "/webhooks/chatwoot", "/internal/x", "/health",
    "/diagnostics", "/diagnostics/flow", "/api/dashboard/meta", "/openapi.json",
])
def test_is_reserved_covers_bot_surface(path):
    assert _is_reserved(path) is True


@pytest.mark.parametrize("path", [
    "/infogatherer", "/infogatherer/conversations", "/infogatherer/statistics",
    "/infogatherer/logs", "/", "/anything-else",
])
def test_is_reserved_allows_spa_routes(path):
    assert _is_reserved(path) is False


def test_reserved_prefix_does_not_match_by_substring():
    """'/healthcheck' is not '/health' — prefix matching must be segment-aware."""
    assert _is_reserved("/healthcheck") is False
    assert _is_reserved("/internal-notes") is False


def test_reserved_prefixes_cover_every_non_dashboard_route(app):
    """
    Every non-dashboard route the app registers must sit behind a reserved prefix,
    or the catch-all could answer for it after a future refactor.
    """
    dashboard_owned = {"/", "/favicon.ico", "/{full_path:path}"}
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or path in dashboard_owned or path.startswith("/assets"):
            continue
        assert _is_reserved(path), f"{path} is not covered by RESERVED_PREFIXES"


def test_root_redirects_to_infogatherer(client, dashboard_env, auth_header):
    response = client.get("/", headers=auth_header, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/infogatherer"
