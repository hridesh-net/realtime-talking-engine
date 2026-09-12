"""The Go engine's write-back and the shared-secret gate on its routes.

POST /api/v1/sessions/{id}/ingest, plus the bearer-token check on it and on
GET /candidates/{id}/engine-contract.

Offline: an in-memory database, no model. The persona is the same fixture
``tests/test_session.py`` seeds, so the ingest attaches to a real candidate
row the way it will in production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from tests.test_session import _seed_candidate

SECRET = "engine-shared-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}
STARTED = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


@pytest.fixture
def repo():
    return InterviewRepository(init_db(":memory:"))


@pytest.fixture
def client(repo, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_SHARED_SECRET", SECRET)
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    with TestClient(app) as c:
        yield c


def _ingest(
    interview_id: str, candidate_id: str, session_id: str = "engine-sess-1", **over
) -> dict:
    body = {
        "session_id": session_id,
        "candidate_id": candidate_id,
        "interview_id": interview_id,
        "contract_fingerprint": "sha256:abc",
        "engine_version": "test-build",
        "started_at": STARTED.isoformat(),
        "ended_at": (STARTED + timedelta(minutes=12)).isoformat(),
        "end_reason": "interviewer_ended",
        "s3": {"recording": "", "transcript": "", "event_log": ""},
        "turns": [
            {
                "turn": 1,
                "speaker": "human",
                "start_ms": 0,
                "end_ms": 2100,
                "text": "Hi, tell me about yourself.",
            },
            {
                "turn": 1,
                "speaker": "persona",
                "start_ms": 2600,
                "end_ms": 9000,
                "text": "Hi, thanks for the time.",
            },
            {
                "turn": 2,
                "speaker": "human",
                "start_ms": 9500,
                "end_ms": 12000,
                "text": "How did you scale Redis?",
            },
            {
                "turn": 2,
                "speaker": "persona",
                "start_ms": 12400,
                "end_ms": 20000,
                "text": "Honestly, I only read about it.",
                "probed_skill": "Redis",
                "deferred": True,
                "fallback_used": True,
            },
            {
                "turn": 3,
                "speaker": "persona",
                "start_ms": 21000,
                "end_ms": 21000,
                "text": "",
                "barged_in": True,
            },
        ],
        "ceiling_flags": [],
        "unlock_flip": None,
        "suppressed_answers": ["Redis"],
        "metrics": {"turns": 5, "defer_rate": 0.5},
        "degradations": ["degraded:asr"],
    }
    body.update(over)
    return body


def test_the_engine_routes_refuse_without_the_shared_secret(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    assert client.get(f"/api/v1/candidates/{candidate_id}/engine-contract").status_code == 401
    assert (
        client.get(
            f"/api/v1/candidates/{candidate_id}/engine-contract",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    body = _ingest(interview_id, candidate_id)
    assert (
        client.post(f"/api/v1/sessions/{body['session_id']}/ingest", json=body).status_code == 401
    )


def test_an_unset_secret_refuses_rather_than_admits(repo, monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_SHARED_SECRET", raising=False)
    _, candidate_id = _seed_candidate(repo)
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    with TestClient(app) as c:
        r = c.get(f"/api/v1/candidates/{candidate_id}/engine-contract", headers=AUTH)
    assert r.status_code == 503
    assert "CONTROL_PLANE_SHARED_SECRET" in r.text


def test_the_engine_contract_is_served_to_the_engine(client, repo):
    _, candidate_id = _seed_candidate(repo)
    r = client.get(f"/api/v1/candidates/{candidate_id}/engine-contract", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["candidate_id"] == candidate_id
    assert client.get("/api/v1/candidates/nope/engine-contract", headers=AUTH).status_code == 404


def test_a_first_ingest_creates_the_voice_session_with_the_engines_transcript(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    body = _ingest(interview_id, candidate_id)

    r = client.post(f"/api/v1/sessions/{body['session_id']}/ingest", json=body, headers=AUTH)
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["session_id"] == "engine-sess-1"
    assert receipt["status"] == "completed"
    assert receipt["turns_stored"] == 4  # the empty barged-in turn is skipped
    assert receipt["duplicate"] is False

    session = repo.get_session("engine-sess-1")
    assert session is not None
    assert session.modality == "voice"
    assert session.status == "completed"
    assert session.candidate_id == candidate_id
    assert session.started_at == STARTED
    assert session.ended_at == STARTED + timedelta(minutes=12)
    assert [(t.index, t.speaker, t.elapsed_ms) for t in session.turns] == [
        (0, "manager", 0),
        (1, "candidate", 2600),
        (2, "manager", 9500),
        (3, "candidate", 12400),
    ]
    assert session.turns[1].at == STARTED + timedelta(milliseconds=2600)
    # The session is now visible where every other session is.
    listed = client.get(f"/api/v1/interviews/{interview_id}/sessions").json()
    assert [s["id"] for s in listed] == ["engine-sess-1"]


def test_a_repeated_ingest_is_idempotent_and_replaces_the_record(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    body = _ingest(interview_id, candidate_id)
    path = f"/api/v1/sessions/{body['session_id']}/ingest"
    assert client.post(path, json=body, headers=AUTH).status_code == 201

    body["turns"] = body["turns"][:2]
    body["end_reason"] = "abandoned"
    r = client.post(path, json=body, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["duplicate"] is True
    assert r.json()["turns_stored"] == 2

    session = repo.get_session("engine-sess-1")
    assert session is not None
    assert len(session.turns) == 2, "a retry must replace the transcript, never append to it"
    assert session.status == "abandoned"


def test_an_ingest_lands_on_the_session_the_portal_opened(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    opened = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        archetype="nervous_fresher",
        planned_minutes=60,
        opening_line="Hi, thanks for the time.",
        modality="voice",
    )
    assert opened.status == "live"
    body = _ingest(interview_id, candidate_id, session_id=opened.id)

    r = client.post(f"/api/v1/sessions/{opened.id}/ingest", json=body, headers=AUTH)
    assert r.status_code == 201, r.text
    session = repo.get_session(opened.id)
    assert session is not None
    assert session.status == "completed"
    assert session.planned_minutes == 60, "the portal's planned length is kept"
    assert len(session.turns) == 4
    assert client.get(f"/api/v1/interviews/{interview_id}/sessions").json()[0]["id"] == opened.id


def test_an_ingest_for_someone_elses_session_is_a_conflict(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    opened = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        archetype="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi.",
    )
    other = repo.create(
        __import__(
            "control_plane.schemas", fromlist=["InterviewCreateRequest"]
        ).InterviewCreateRequest(
            job_title="Other role",
            jd="Other JD.",
            skills_required=["x"],
            job_location_type="onsite",
            experience_level="mid",
            company_type="mnc",
        )
    )
    body = _ingest(other.id, candidate_id, session_id=opened.id)
    r = client.post(f"/api/v1/sessions/{opened.id}/ingest", json=body, headers=AUTH)
    assert r.status_code == 409


def test_an_ingest_is_validated_before_anything_is_written(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    body = _ingest(interview_id, candidate_id)
    # Path and body disagree.
    assert client.post("/api/v1/sessions/other/ingest", json=body, headers=AUTH).status_code == 422
    # Unknown persona.
    bad = _ingest(interview_id, "cand-unknown")
    assert (
        client.post(
            f"/api/v1/sessions/{bad['session_id']}/ingest", json=bad, headers=AUTH
        ).status_code
        == 404
    )
    # An end reason outside the enum.
    bad = _ingest(interview_id, candidate_id, end_reason="rage_quit")
    assert (
        client.post(
            f"/api/v1/sessions/{bad['session_id']}/ingest", json=bad, headers=AUTH
        ).status_code
        == 422
    )
    assert repo.get_session("engine-sess-1") is None
