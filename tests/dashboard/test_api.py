"""
Dashboard API tests (DASHBOARD_SPEC.md §13.3).

The DB is stubbed via the fake_pool fixture — these cover auth, validation,
response shaping, and the invariants that must hold between endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.dashboard.conftest import FakeRecord

NOW = datetime(2026, 7, 22, 21, 57, tzinfo=timezone.utc)
CONV_UUID = uuid.UUID("f2a1baa2-5bf1-47b6-9378-8d8f51972535")
LOG_UUID = uuid.UUID("0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f")


def conversation_record(**overrides) -> FakeRecord:
    base = {
        "id": CONV_UUID,
        "chatwoot_conversation_id": 1708,
        "flow_state": "completed",
        "contact_phone": "905528582923",
        "labels": [],
        "gender": "female",
        "university_id": None,
        "ilgili_otel": None,
        "bot_enabled": True,
        "infogatherer_abstain_reason": None,
        "reprompt_count": 0,
        "clarification_attempt": 0,
        "auto_run_count": 0,
        "manual_run_count": 0,
        "created_at": NOW,
        "last_updated_at": NOW,
        "last_message_at": NOW,
        "lead_name": "Cansu Deniz",
        "lead_name_is_fallback": False,
        "takeover_at": None,
        "escalated_at": NOW,
        "escalated_at_exact": True,
        "status": "success",
        "last_activity_at": NOW,
        "failure_log_explanation": None,
        "failure_log_internal_class": None,
        "failure_log_status_code": None,
        "failure_log_from_state": None,
        "failure_log_at": None,
        "rec_engine_status": None,
        "rec_engine_status_code": None,
        "rec_engine_network_status": None,
        "message_count": 12,
        "log_count": 2,
        "total_count": 1,
        "university_name": None,
    }
    base.update(overrides)
    return FakeRecord(base)


def log_record(**overrides) -> FakeRecord:
    base = {
        "id": LOG_UUID,
        "created_at": NOW,
        "conversation_id": CONV_UUID,
        "chatwoot_conversation_id": 1708,
        "operation_layer": "infoGatherer",
        "which_run": "contextRun",
        "from_state": None,
        "to_state": None,
        "log_level": "fatal",
        "is_success": False,
        "status_code": None,
        "internal_class": None,
        "network_status": None,
        "database_status": None,
        "explanation": "Post-completion message did not name a specific hotel — deferred to human",
        "total_count": 1,
    }
    base.update(overrides)
    return FakeRecord(base)


# ---------------------------------------------------------------------------
# Auth (spec §3.5)
# ---------------------------------------------------------------------------

def test_api_401_without_credentials(client, dashboard_env):
    response = client.get("/api/dashboard/meta")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_api_401_with_wrong_password(client, dashboard_env):
    response = client.get("/api/dashboard/meta", auth=("dash-test-user", "nope"))
    assert response.status_code == 401


def test_api_401_with_wrong_username(client, dashboard_env):
    response = client.get("/api/dashboard/meta", auth=("nobody", "dash-test-password"))
    assert response.status_code == 401


def test_api_503_when_auth_not_configured(client, no_auth_env, auth_header):
    """Fail closed — unconfigured must never mean open. Lead PII is behind here."""
    response = client.get("/api/dashboard/meta", headers=auth_header)
    assert response.status_code == 503
    assert "DASHBOARD_USER" in response.json()["detail"]


def test_spa_also_requires_auth(client, no_auth_env):
    """The HTML shell is gated too, not just the JSON API."""
    response = client.get("/infogatherer")
    assert response.status_code == 503


def test_meta_ok_with_valid_credentials(client, dashboard_env, auth_header):
    response = client.get("/api/dashboard/meta", headers=auth_header)
    assert response.status_code == 200
    body = response.json()
    assert body["stale_hours"] == 24
    assert "human_interruption" in body["statuses"]
    assert "not_run" in body["statuses"]
    assert body["server_time"].endswith("Z")


def test_stale_hours_read_from_env(client, dashboard_env, auth_header, monkeypatch):
    monkeypatch.setenv("DASHBOARD_STALE_HOURS", "48")
    response = client.get("/api/dashboard/meta", headers=auth_header)
    assert response.json()["stale_hours"] == 48


def test_invalid_stale_hours_falls_back_to_default(client, dashboard_env, auth_header, monkeypatch):
    monkeypatch.setenv("DASHBOARD_STALE_HOURS", "not-a-number")
    assert client.get("/api/dashboard/meta", headers=auth_header).json()["stale_hours"] == 24


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

def test_conversations_list_shape(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[conversation_record()]]
    response = client.get("/api/dashboard/infogatherer/conversations", headers=auth_header)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["chatwoot_conversation_id"] == 1708
    assert row["lead_name"] == "Cansu Deniz"
    assert row["status"] == "success"
    assert row["created_at"].endswith("Z")


def test_conversations_empty_returns_zero_not_error(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[]]
    body = client.get("/api/dashboard/infogatherer/conversations", headers=auth_header).json()
    assert body == {"total": 0, "limit": 50, "offset": 0, "rows": []}


def test_conversations_rejects_unknown_sort(client, dashboard_env, auth_header, fake_pool):
    """Sort is interpolated into SQL, so an unknown value must never reach the query."""
    response = client.get(
        "/api/dashboard/infogatherer/conversations?sort=id;DROP TABLE conversations",
        headers=auth_header,
    )
    assert response.status_code == 400
    assert fake_pool.statements == []


def test_conversations_rejects_unknown_direction(client, dashboard_env, auth_header, fake_pool):
    response = client.get(
        "/api/dashboard/infogatherer/conversations?dir=sideways", headers=auth_header
    )
    assert response.status_code == 400
    assert fake_pool.statements == []


def test_conversations_rejects_unknown_status(client, dashboard_env, auth_header, fake_pool):
    response = client.get(
        "/api/dashboard/infogatherer/conversations?status=exploded", headers=auth_header
    )
    assert response.status_code == 400


def test_conversations_accepts_every_valid_status(client, dashboard_env, auth_header, fake_pool):
    from dashboard.api import derive

    query = "&".join(f"status={s}" for s in derive.ALL_STATUSES)
    fake_pool.fetch_results = [[]]
    response = client.get(
        f"/api/dashboard/infogatherer/conversations?{query}", headers=auth_header
    )
    assert response.status_code == 200


def test_conversations_search_binds_as_parameter(client, dashboard_env, auth_header, fake_pool):
    """Free text must travel as $n, never be interpolated."""
    fake_pool.fetch_results = [[]]
    client.get(
        "/api/dashboard/infogatherer/conversations?q='%20OR%201=1--", headers=auth_header
    )
    assert "OR 1=1" not in fake_pool.statements[0]
    assert "ILIKE $" in fake_pool.statements[0]


def test_conversations_limit_capped(client, dashboard_env, auth_header):
    response = client.get(
        "/api/dashboard/infogatherer/conversations?limit=9999", headers=auth_header
    )
    assert response.status_code == 422


def test_conversation_detail_404(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [None]
    response = client.get("/api/dashboard/infogatherer/conversations/9999", headers=auth_header)
    assert response.status_code == 404


def test_conversation_detail_includes_extra_fields(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [conversation_record(university_name="Istinye")]
    body = client.get(
        "/api/dashboard/infogatherer/conversations/1708", headers=auth_header
    ).json()
    assert body["university_name"] == "Istinye"
    assert body["contact_phone"] == "905528582923"
    assert body["bot_enabled"] is True


def test_bad_date_rejected(client, dashboard_env, auth_header):
    response = client.get(
        "/api/dashboard/infogatherer/conversations?from=not-a-date", headers=auth_header
    )
    assert response.status_code == 400
    assert "Invalid date" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def test_logs_list_shape(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[log_record()]]
    body = client.get("/api/dashboard/infogatherer/logs", headers=auth_header).json()
    row = body["rows"][0]
    assert row["operation_label"] == "infoGatherer · contextRun"
    assert row["log_status"] == "human_needed"  # fatal → escalation
    assert row["signature"] == "post_completion_no_hotel"
    assert row["derived"] is False


def test_log_row_error_level_is_red(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[log_record(log_level="error", explanation="boom")]]
    body = client.get("/api/dashboard/infogatherer/logs", headers=auth_header).json()
    assert body["rows"][0]["log_status"] == "failed"


def test_log_detail_404_on_garbage_id(client, dashboard_env, auth_header, fake_pool):
    response = client.get("/api/dashboard/infogatherer/logs/not-a-uuid", headers=auth_header)
    assert response.status_code == 404


def test_log_detail_payload_unavailable_with_note(client, dashboard_env, auth_header, fake_pool):
    """Phase 1 has no payload columns — the absence must be explained, not blank."""
    fake_pool.fetchrow_results = [log_record(), conversation_record()]
    fake_pool.fetch_results = [[], []]
    body = client.get(
        f"/api/dashboard/infogatherer/logs/{LOG_UUID}", headers=auth_header
    ).json()
    assert body["payload"]["available"] is False
    assert "not captured" in body["payload"]["note"]
    assert body["raw"]["explanation"].startswith("Post-completion")


def test_logs_rejects_unknown_level(client, dashboard_env, auth_header):
    response = client.get(
        "/api/dashboard/infogatherer/logs?log_level=catastrophic", headers=auth_header
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_summary_excludes_not_run_from_denominator(client, dashboard_env, auth_header, fake_pool):
    """The headline percentages are of runs the bot actually engaged with."""
    fake_pool.fetch_results = [[
        FakeRecord({"status": "success", "n": 1}),
        FakeRecord({"status": "failed", "n": 2}),
        FakeRecord({"status": "human_needed", "n": 1}),
        FakeRecord({"status": "human_interruption", "n": 14}),
        FakeRecord({"status": "in_progress", "n": 1}),
        FakeRecord({"status": "not_run", "n": 6}),
    ]]
    fake_pool.fetchrow_results = [
        FakeRecord({"clean_count": 13, "total_interrupted": 14})
    ]
    body = client.get(
        "/api/dashboard/infogatherer/stats/summary", headers=auth_header
    ).json()

    assert body["total_conversations"] == 25
    assert body["denominator"] == 19  # 25 - 6 not_run
    assert body["counts"]["not_run"] == 6
    assert body["clean_interruption_count"] == 13
    assert body["dirty_interruption_count"] == 1
    assert body["percentages"]["success"] == pytest.approx(5.3, abs=0.1)


def test_summary_percentages_null_when_no_runs(client, dashboard_env, auth_header, fake_pool):
    """An em-dash beats a fabricated 0.0%."""
    fake_pool.fetch_results = [[FakeRecord({"status": "not_run", "n": 3})]]
    fake_pool.fetchrow_results = [FakeRecord({"clean_count": 0, "total_interrupted": 0})]
    body = client.get(
        "/api/dashboard/infogatherer/stats/summary", headers=auth_header
    ).json()
    assert body["denominator"] == 0
    assert body["percentages"]["failed"] is None


def test_summary_counts_reconcile_with_total(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[
        FakeRecord({"status": "success", "n": 3}),
        FakeRecord({"status": "not_run", "n": 2}),
    ]]
    fake_pool.fetchrow_results = [FakeRecord({"clean_count": 0, "total_interrupted": 0})]
    body = client.get(
        "/api/dashboard/infogatherer/stats/summary", headers=auth_header
    ).json()
    assert sum(body["counts"].values()) == body["total_conversations"]
    assert body["denominator"] == body["total_conversations"] - body["counts"]["not_run"]


def test_breakdowns_use_origin_state_not_human_needed(client, dashboard_env, auth_header, fake_pool):
    """
    Grouping human_needed rows on raw flow_state would yield one useless slice
    labelled 'human_needed'. It must key on the reconstructed origin.
    """
    fake_pool.fetch_results = [[
        FakeRecord({
            "id": CONV_UUID, "status": "human_needed", "flow_state": "human_needed",
            "failure_log_explanation": "Gender set but university missing after gender slot reply",
            "failure_log_internal_class": None, "failure_log_status_code": None,
            "failure_log_from_state": None, "rec_engine_status": None,
            "rec_engine_status_code": None, "rec_engine_network_status": None,
        }),
    ]]
    body = client.get(
        "/api/dashboard/infogatherer/stats/breakdowns", headers=auth_header
    ).json()
    slices = body["human_needed_by_flow_state"]["slices"]
    assert slices[0]["key"] == "awaiting_gender"
    assert body["human_needed_by_flow_state"]["total"] == 1


def test_breakdowns_stalled_failure_keeps_its_live_state(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[
        FakeRecord({
            "id": CONV_UUID, "status": "failed", "flow_state": "awaiting_university",
            "failure_log_explanation": None, "failure_log_internal_class": None,
            "failure_log_status_code": None, "failure_log_from_state": None,
            "rec_engine_status": None, "rec_engine_status_code": None,
            "rec_engine_network_status": None,
        }),
    ]]
    body = client.get(
        "/api/dashboard/infogatherer/stats/breakdowns", headers=auth_header
    ).json()
    assert body["failures_by_flow_state"]["slices"][0]["key"] == "awaiting_university"
    assert body["failures_by_signature"]["slices"][0]["key"] == "stalled"


def test_breakdowns_empty_returns_zero_totals(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[]]
    body = client.get(
        "/api/dashboard/infogatherer/stats/breakdowns", headers=auth_header
    ).json()
    assert body["failures_by_flow_state"] == {"total": 0, "slices": []}


# ---------------------------------------------------------------------------
# Human-needed triggers
# ---------------------------------------------------------------------------

def test_triggers_group_case_variants(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 1, "lead_name": "A",
                    "content": "Tamam cok saolun", "sent_at": NOW}),
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 2, "lead_name": "B",
                    "content": "TAMAM COK SAOLUN", "sent_at": NOW}),
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 3, "lead_name": "C",
                    "content": "başka bir mesaj", "sent_at": NOW}),
    ]]
    body = client.get(
        "/api/dashboard/infogatherer/stats/human-needed-triggers", headers=auth_header
    ).json()
    assert body["total_human_needed"] == 3
    assert body["rows"][0]["count"] == 2
    assert len(body["rows"][0]["conversations"]) == 2


def test_triggers_report_escalations_without_a_message(client, dashboard_env, auth_header, fake_pool):
    """Escalations with no preceding inbound are counted, never silently dropped."""
    fake_pool.fetch_results = [[
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 1, "lead_name": "A",
                    "content": "merhaba", "sent_at": NOW}),
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 2, "lead_name": "B",
                    "content": None, "sent_at": None}),
    ]]
    body = client.get(
        "/api/dashboard/infogatherer/stats/human-needed-triggers", headers=auth_header
    ).json()
    assert body["total_human_needed"] == 2
    assert body["with_trigger"] == 1


def test_triggers_ranked_descending(client, dashboard_env, auth_header, fake_pool):
    rows = [
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": i, "lead_name": "x",
                    "content": "rare", "sent_at": NOW})
        for i in range(1)
    ] + [
        FakeRecord({"id": CONV_UUID, "chatwoot_conversation_id": 100 + i, "lead_name": "y",
                    "content": "common", "sent_at": NOW})
        for i in range(3)
    ]
    fake_pool.fetch_results = [rows]
    body = client.get(
        "/api/dashboard/infogatherer/stats/human-needed-triggers", headers=auth_header
    ).json()
    counts = [r["count"] for r in body["rows"]]
    assert counts == sorted(counts, reverse=True)
    assert body["rows"][0]["display_text"] == "common"
