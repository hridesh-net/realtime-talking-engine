"""Offline tests for session recordings — storage, sequencing, and endpoints.

No audio codec, no network, no file-backed database. Every test writes to
`tmp_path` via `InterviewRepository(conn, recordings_dir=tmp_path)`, the same
way `RECORDINGS_DIR` points the real service at disk.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candidate_agent.session import CandidateSessionAgent
from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from tests.test_session import FakeChatModel, _seed_candidate

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> InterviewRepository:
    return InterviewRepository(init_db(":memory:"), recordings_dir=tmp_path)


def _voice_session(repo: InterviewRepository) -> str:
    """Open a voice session and return its id, without a model call."""
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi, thanks for the time.",
        modality="voice",
    )
    return session.id


def test_first_chunk_creates_the_recording_and_bytes_land_on_disk(repo, tmp_path):
    session_id = _voice_session(repo)
    meta = repo.append_recording_chunk(session_id, 0, "audio/webm", b"first-bytes")

    assert meta.session_id == session_id
    assert meta.status == "recording"
    assert meta.producer == "browser"
    assert meta.mime_type == "audio/webm"
    assert meta.byte_size == len(b"first-bytes")
    assert meta.next_seq == 1

    on_disk = tmp_path / f"{session_id}.webm"
    assert on_disk.read_bytes() == b"first-bytes"


def test_chunks_append_in_order_and_byte_size_accumulates(repo, tmp_path):
    session_id = _voice_session(repo)
    chunks = [b"alpha-chunk", b"bravo-chunk-longer", b"charlie"]
    for seq, chunk in enumerate(chunks):
        meta = repo.append_recording_chunk(session_id, seq, "audio/webm", chunk)

    assert meta.next_seq == 3
    assert meta.byte_size == sum(len(c) for c in chunks)
    on_disk = tmp_path / f"{session_id}.webm"
    assert on_disk.read_bytes() == b"".join(chunks)


def test_out_of_order_seq_raises(repo):
    session_id = _voice_session(repo)
    repo.append_recording_chunk(session_id, 0, "audio/webm", b"first")
    with pytest.raises(ValueError):
        repo.append_recording_chunk(session_id, 2, "audio/webm", b"skipped-one")


def test_finalize_is_idempotent_and_marks_complete(repo):
    session_id = _voice_session(repo)
    repo.append_recording_chunk(session_id, 0, "audio/webm", b"first")

    finalized = repo.finalize_recording(session_id)
    assert finalized.status == "complete"

    again = repo.finalize_recording(session_id)
    assert again.status == "complete"
    assert again.updated_at == finalized.updated_at, "re-finalizing must not move the clock"

    assert repo.finalize_recording("no-such-session") is None


def test_chunk_after_finalize_raises(repo):
    session_id = _voice_session(repo)
    repo.append_recording_chunk(session_id, 0, "audio/webm", b"first")
    repo.finalize_recording(session_id)
    with pytest.raises(ValueError):
        repo.append_recording_chunk(session_id, 1, "audio/webm", b"too-late")


def test_get_session_carries_recording_meta_and_list_flags_it(repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi.",
        modality="voice",
    )

    before = repo.get_session(session.id)
    assert before.recording is None
    rows_before = repo.list_sessions(interview_id)
    assert rows_before[0].has_recording is False

    repo.append_recording_chunk(session.id, 0, "audio/webm", b"bytes")

    after = repo.get_session(session.id)
    assert after.recording is not None
    assert after.recording.session_id == session.id
    assert after.recording.status == "recording"

    rows_after = repo.list_sessions(interview_id)
    assert rows_after[0].has_recording is True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def client(repo):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_session_agent] = lambda: CandidateSessionAgent(
        FakeChatModel()
    )
    with TestClient(app) as c:
        yield c


def _open_voice_session(client) -> tuple[str, str]:
    """Create an interview + persona through the repo, then open a voice session via the API."""
    interview = client.post(
        "/api/v1/interviews",
        json={
            "job_title": "Field Sales Executive",
            "jd": "Sell prepaid activations through channel partners.",
            "skills_required": ["territory management"],
            "job_location_type": "onsite",
            "experience_level": "mid",
            "company_type": "mnc",
        },
    ).json()
    client.post(f"/api/v1/interviews/{interview['id']}/candidates", json={})
    created = client.post(
        "/api/v1/sessions",
        json={
            "interview_id": interview["id"],
            "archetype": "cooperative_trap",
            "planned_minutes": 20,
            "modality": "voice",
        },
    )
    assert created.status_code == 201, created.text
    return interview["id"], created.json()["id"]


def test_voice_recording_round_trip(client):
    _, session_id = _open_voice_session(client)
    chunks = [b"one-two-three", b"four-five-six", b"seven-eight"]

    for seq, chunk in enumerate(chunks):
        resp = client.post(
            f"/api/v1/sessions/{session_id}/recording/chunks",
            params={"seq": seq},
            content=chunk,
            headers={"Content-Type": "audio/webm;codecs=opus"},
        )
        assert resp.status_code == 201, resp.text

    finalized = client.post(f"/api/v1/sessions/{session_id}/recording/finalize")
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "complete"

    fetched = client.get(f"/api/v1/sessions/{session_id}/recording")
    assert fetched.status_code == 200
    assert fetched.content == b"".join(chunks)
    assert fetched.headers["content-type"] == "audio/webm;codecs=opus"


def test_wrong_seq_is_409(client):
    _, session_id = _open_voice_session(client)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 1},
        content=b"skips-zero",
        headers={"Content-Type": "audio/webm"},
    )
    assert resp.status_code == 409


def test_text_session_rejects_chunks_with_409(client):
    interview = client.post(
        "/api/v1/interviews",
        json={
            "job_title": "Field Sales Executive",
            "jd": "Sell prepaid activations through channel partners.",
            "skills_required": ["territory management"],
            "job_location_type": "onsite",
            "experience_level": "mid",
            "company_type": "mnc",
        },
    ).json()
    client.post(f"/api/v1/interviews/{interview['id']}/candidates", json={})
    created = client.post(
        "/api/v1/sessions",
        json={
            "interview_id": interview["id"],
            "archetype": "cooperative_trap",
            "planned_minutes": 20,
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    resp = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 0},
        content=b"not-voice",
        headers={"Content-Type": "audio/webm"},
    )
    assert resp.status_code == 409


def test_unknown_session_is_404(client):
    resp = client.post(
        "/api/v1/sessions/no-such-session/recording/chunks",
        params={"seq": 0},
        content=b"bytes",
        headers={"Content-Type": "audio/webm"},
    )
    assert resp.status_code == 404
    assert client.post("/api/v1/sessions/no-such-session/recording/finalize").status_code == 404
    assert client.get("/api/v1/sessions/no-such-session/recording").status_code == 404


def test_missing_recording_is_404(client):
    _, session_id = _open_voice_session(client)
    resp = client.get(f"/api/v1/sessions/{session_id}/recording")
    assert resp.status_code == 404


def test_empty_chunk_is_422(client):
    _, session_id = _open_voice_session(client)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 0},
        content=b"",
        headers={"Content-Type": "audio/webm"},
    )
    assert resp.status_code == 422
