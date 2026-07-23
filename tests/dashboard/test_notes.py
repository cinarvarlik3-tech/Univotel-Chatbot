"""
Dashboard notes API tests (DASHBOARD_SPEC.md notes addition).

The notes endpoints are the dashboard's only write path. These cover create,
list, the resolve/unresolve toggle, validation, 404s, and the yellow-dot flag on
the conversations list — including that it degrades to false when the notes table
is absent. DB is stubbed via the fake_pool fixture.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg

from tests.dashboard.conftest import FakeRecord
from tests.dashboard.test_api import conversation_record

NOW = datetime(2026, 7, 22, 21, 57, tzinfo=timezone.utc)
CONV_UUID = uuid.UUID("f2a1baa2-5bf1-47b6-9378-8d8f51972535")
NOTE_UUID = uuid.UUID("1b2c3d4e-5f60-4a1b-8c2d-3e4f5a6b7c8d")


def note_record(**overrides) -> FakeRecord:
    base = {
        "id": NOTE_UUID,
        "conversation_id": CONV_UUID,
        "chatwoot_conversation_id": 1708,
        "note_type": "conversation",
        "body": "Follow up with this lead tomorrow.",
        "resolved": False,
        "author": "dash-test-user",
        "created_at": NOW,
        "updated_at": NOW,
        "resolved_at": None,
    }
    base.update(overrides)
    return FakeRecord(base)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_conversation_note(client, dashboard_env, auth_header, fake_pool):
    # resolve_conversation_uuid → fetchrow; create_note → fetchrow (RETURNING).
    fake_pool.fetchrow_results = [FakeRecord({"id": CONV_UUID}), note_record()]
    response = client.post(
        "/api/dashboard/infogatherer/conversations/1708/notes",
        headers=auth_header,
        json={"note_type": "conversation", "body": "Follow up with this lead tomorrow."},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(NOTE_UUID)
    assert body["note_type"] == "conversation"
    assert body["resolved"] is False
    assert body["chatwoot_conversation_id"] == 1708
    # The authenticated user is recorded as the author.
    assert body["author"] == "dash-test-user"


def test_create_log_note(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [
        FakeRecord({"id": CONV_UUID}),
        note_record(note_type="log", body="Manually verified escalation."),
    ]
    response = client.post(
        "/api/dashboard/infogatherer/conversations/1708/notes",
        headers=auth_header,
        json={"note_type": "log", "body": "Manually verified escalation."},
    )
    assert response.status_code == 201
    assert response.json()["note_type"] == "log"


def test_create_note_unknown_conversation_404(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [None]  # resolve_conversation_uuid finds nothing
    response = client.post(
        "/api/dashboard/infogatherer/conversations/9999/notes",
        headers=auth_header,
        json={"note_type": "log", "body": "x"},
    )
    assert response.status_code == 404


def test_create_note_blank_body_rejected(client, dashboard_env, auth_header, fake_pool):
    response = client.post(
        "/api/dashboard/infogatherer/conversations/1708/notes",
        headers=auth_header,
        json={"note_type": "log", "body": "   "},
    )
    assert response.status_code == 422
    # Never reached the database.
    assert fake_pool.statements == []


def test_create_note_bad_type_rejected(client, dashboard_env, auth_header, fake_pool):
    response = client.post(
        "/api/dashboard/infogatherer/conversations/1708/notes",
        headers=auth_header,
        json={"note_type": "sticky", "body": "hi"},
    )
    assert response.status_code == 422
    assert fake_pool.statements == []


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_notes(client, dashboard_env, auth_header, fake_pool):
    # get_conversation: fetchrow (detail) + fetch (unresolved ids); then list_notes: fetch.
    fake_pool.fetchrow_results = [conversation_record()]
    fake_pool.fetch_results = [[], [note_record(), note_record(note_type="log")]]
    body = client.get(
        "/api/dashboard/infogatherer/conversations/1708/notes", headers=auth_header
    ).json()
    assert body["conversation"]["chatwoot_conversation_id"] == 1708
    assert len(body["rows"]) == 2


def test_list_notes_unknown_conversation_404(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [None]
    response = client.get(
        "/api/dashboard/infogatherer/conversations/9999/notes", headers=auth_header
    )
    assert response.status_code == 404


def test_list_notes_bad_type_filter_rejected(client, dashboard_env, auth_header, fake_pool):
    response = client.get(
        "/api/dashboard/infogatherer/conversations/1708/notes?type=sticky",
        headers=auth_header,
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Resolve / unresolve
# ---------------------------------------------------------------------------

def test_resolve_note(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [note_record(resolved=True, resolved_at=NOW)]
    body = client.patch(
        f"/api/dashboard/infogatherer/notes/{NOTE_UUID}",
        headers=auth_header,
        json={"resolved": True},
    ).json()
    assert body["resolved"] is True
    assert body["resolved_at"] is not None


def test_unresolve_note(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [note_record(resolved=False, resolved_at=None)]
    body = client.patch(
        f"/api/dashboard/infogatherer/notes/{NOTE_UUID}",
        headers=auth_header,
        json={"resolved": False},
    ).json()
    assert body["resolved"] is False
    assert body["resolved_at"] is None


def test_resolve_unknown_note_404(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetchrow_results = [None]
    response = client.patch(
        f"/api/dashboard/infogatherer/notes/{NOTE_UUID}",
        headers=auth_header,
        json={"resolved": True},
    )
    assert response.status_code == 404


def test_resolve_garbage_note_id_404(client, dashboard_env, auth_header, fake_pool):
    response = client.patch(
        "/api/dashboard/infogatherer/notes/not-a-uuid",
        headers=auth_header,
        json={"resolved": True},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Yellow dot on the conversations list
# ---------------------------------------------------------------------------

def test_conversation_row_flags_unresolved_note(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [
        [conversation_record()],
        [FakeRecord({"conversation_id": CONV_UUID})],  # unresolved-note lookup
    ]
    body = client.get(
        "/api/dashboard/infogatherer/conversations", headers=auth_header
    ).json()
    assert body["rows"][0]["has_unresolved_note"] is True


def test_conversation_row_no_note_no_dot(client, dashboard_env, auth_header, fake_pool):
    fake_pool.fetch_results = [[conversation_record()], []]
    body = client.get(
        "/api/dashboard/infogatherer/conversations", headers=auth_header
    ).json()
    assert body["rows"][0]["has_unresolved_note"] is False


def test_unresolved_flag_survives_missing_table(client, dashboard_env, auth_header, fake_pool):
    """Before migration 033, the dot lookup must degrade to false, not 500."""
    calls = {"n": 0}

    async def selective_fetch(query: str, *args):
        calls["n"] += 1
        if calls["n"] == 1:
            return [conversation_record()]
        raise asyncpg.UndefinedTableError("relation dashboard_notes does not exist")

    fake_pool.fetch = selective_fetch  # type: ignore[method-assign]
    body = client.get(
        "/api/dashboard/infogatherer/conversations", headers=auth_header
    ).json()
    assert body["rows"][0]["has_unresolved_note"] is False
