"""Offline tests for the three additions the SkillBrew portal needs.

The portal talks to this service from another origin through a shared axios
layer it does not own, and that layer makes two demands this API did not meet:
it toasts `response.data?.message` on 409/422/408 whatever the body says, and it
can post JSON or multipart but never a raw `audio/webm` body. So the control
plane grew a CORS switch, an error envelope beside `detail`, and a multipart
door onto the recording-chunk endpoint.

Every test here asserts the *additive* half of that: the status codes, the
`detail` values and the raw upload path are exactly what the existing console
already sees, and the new keys sit next to them. No network, no model call --
`build_app(":memory:")` with the repository overridden, the same way
`tests/test_recording.py` does it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.session import CandidateSessionAgent
from control_plane import api as api_module
from control_plane import main as main_module
from control_plane.database import init_db
from control_plane.main import build_app, cors_allowed_origins, install_error_envelope
from control_plane.repository import InterviewRepository
from tests.test_control_plane_candidates_api import FakeModel
from tests.test_session import FakeChatModel

_INTERVIEW = {
    "job_title": "Field Sales Executive",
    "jd": "Sell prepaid activations through channel partners.",
    "skills_required": ["territory management"],
    "job_location_type": "onsite",
    "experience_level": "mid",
    "company_type": "mnc",
}


@pytest.fixture
def repo(tmp_path) -> InterviewRepository:
    return InterviewRepository(init_db(":memory:"), recordings_dir=tmp_path)


@pytest.fixture
def client(repo):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_session_agent] = lambda: CandidateSessionAgent(
        FakeChatModel()
    )
    app.dependency_overrides[api_module.get_candidate_agent] = lambda: VirtualCandidateAgent(
        model=FakeModel("fake-1", 0.35)
    )
    with TestClient(app) as c:
        yield c


def _open_session(client, modality: str) -> str:
    """Create an interview, enroll a persona, open a session. No model provider."""
    interview = client.post("/api/v1/interviews", json=_INTERVIEW).json()
    client.post(f"/api/v1/interviews/{interview['id']}/candidates", json={})
    created = client.post(
        "/api/v1/sessions",
        json={
            "interview_id": interview["id"],
            "archetype": "cooperative_trap",
            "planned_minutes": 20,
            "modality": modality,
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


# ---------------------------------------------------------------------------
# The error envelope
# ---------------------------------------------------------------------------


def test_404_carries_the_envelope_beside_the_unchanged_detail(client):
    resp = client.get("/api/v1/interviews/no-such-interview")

    assert resp.status_code == 404
    body = resp.json()
    # `detail` is what the existing console reads, and it is byte-for-byte what
    # FastAPI sent before the handler existed.
    assert body["detail"] == "interview not found"
    assert body["status"] is False
    assert body["message"] == "interview not found"


def test_422_keeps_fastapis_error_list_and_summarises_it_in_message(client):
    resp = client.post("/api/v1/interviews", json={"job_title": "Field Sales Executive"})

    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body["detail"], list), "the console's 422 detail is still the pydantic list"
    assert body["detail"], "an empty list would mean the errors were lost"
    assert all("loc" in item and "msg" in item for item in body["detail"])
    assert body["status"] is False
    # One readable line, because the portal's axios layer toasts `message` on a
    # 422 unconditionally and cannot render the list.
    assert isinstance(body["message"], str) and body["message"]
    for item in body["detail"]:
        assert item["msg"] in body["message"]
        assert ".".join(str(part) for part in item["loc"]) in body["message"]


def test_409_carries_the_envelope(client):
    session_id = _open_session(client, "text")
    resp = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 0},
        content=b"not-voice",
        headers={"Content-Type": "audio/webm"},
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"] == "session modality is text, not voice"
    assert body["status"] is False
    assert body["message"] == body["detail"]


def test_a_404_from_no_such_route_is_enveloped_too(client):
    """The 404 Starlette raises for itself.

    It only carries the envelope because the handler is registered on
    starlette's `HTTPException` rather than on FastAPI's subclass.
    """
    resp = client.get("/api/v1/there-is-no-such-endpoint")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found", "status": False, "message": "Not Found"}


def test_a_non_string_detail_becomes_a_json_message_and_headers_survive():
    """A dict detail and a header-carrying exception.

    Neither shape is raised in this codebase today; the handler still owes
    FastAPI's behaviour for both, so they are asserted on a throwaway app.
    """
    app = FastAPI()
    install_error_envelope(app)

    @app.get("/structured")
    def structured() -> None:
        raise HTTPException(status_code=400, detail={"field": "seq", "problem": "out of order"})

    @app.get("/with-headers")
    def with_headers() -> None:
        raise HTTPException(
            status_code=401, detail="who are you", headers={"WWW-Authenticate": "Bearer"}
        )

    with TestClient(app) as client:
        structured_resp = client.get("/structured")
        assert structured_resp.status_code == 400
        body = structured_resp.json()
        assert body["detail"] == {"field": "seq", "problem": "out of order"}
        assert body["status"] is False
        assert body["message"] == '{"field": "seq", "problem": "out of order"}'

        header_resp = client.get("/with-headers")
        assert header_resp.status_code == 401
        assert header_resp.headers["www-authenticate"] == "Bearer"
        assert header_resp.json()["message"] == "who are you"


@pytest.mark.parametrize("code", [204, 304])
def test_a_status_code_that_forbids_a_body_gets_no_envelope(code: int):
    """204 and 304 carry no body, enveloped or otherwise.

    A body on either is a protocol error, and FastAPI's own handler suppresses
    it. The envelope must not be the thing that reintroduces one.
    """
    app = FastAPI()
    install_error_envelope(app)

    @app.get("/no-body")
    def no_body() -> None:
        raise HTTPException(status_code=code)

    with TestClient(app) as client:
        resp = client.get("/no-body")

    assert resp.status_code == code
    assert resp.content == b""


# ---------------------------------------------------------------------------
# Multipart recording chunks
# ---------------------------------------------------------------------------


def test_multipart_chunk_stores_what_the_raw_body_stores(client):
    chunks = [b"one-two-three", b"four-five-six", b"seven-eight"]

    raw_session = _open_session(client, "voice")
    for seq, chunk in enumerate(chunks):
        resp = client.post(
            f"/api/v1/sessions/{raw_session}/recording/chunks",
            params={"seq": seq},
            content=chunk,
            headers={"Content-Type": "audio/webm;codecs=opus"},
        )
        assert resp.status_code == 201, resp.text

    form_session = _open_session(client, "voice")
    for seq, chunk in enumerate(chunks):
        resp = client.post(
            f"/api/v1/sessions/{form_session}/recording/chunks",
            params={"seq": seq},
            files={"chunk": (f"chunk-{seq}.webm", chunk, "audio/webm;codecs=opus")},
        )
        assert resp.status_code == 201, resp.text

    raw_meta = client.get(f"/api/v1/sessions/{raw_session}").json()["recording"]
    form_meta = client.get(f"/api/v1/sessions/{form_session}").json()["recording"]
    assert form_meta["mime_type"] == raw_meta["mime_type"] == "audio/webm;codecs=opus"
    assert form_meta["byte_size"] == raw_meta["byte_size"] == sum(len(c) for c in chunks)
    assert form_meta["next_seq"] == raw_meta["next_seq"] == len(chunks)

    raw_audio = client.get(f"/api/v1/sessions/{raw_session}/recording")
    form_audio = client.get(f"/api/v1/sessions/{form_session}/recording")
    assert form_audio.content == raw_audio.content == b"".join(chunks)
    assert form_audio.headers["content-type"] == raw_audio.headers["content-type"]


def test_multipart_keeps_the_same_409_and_422_semantics(client):
    session_id = _open_session(client, "voice")

    skipped = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 1},
        files={"chunk": ("chunk-1.webm", b"skips-zero", "audio/webm")},
    )
    assert skipped.status_code == 409
    assert skipped.json()["status"] is False

    empty = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 0},
        files={"chunk": ("chunk-0.webm", b"", "audio/webm")},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"] == "empty chunk body"

    wrong_field = client.post(
        f"/api/v1/sessions/{session_id}/recording/chunks",
        params={"seq": 0},
        files={"audio": ("chunk-0.webm", b"bytes", "audio/webm")},
    )
    assert wrong_field.status_code == 422
    assert "chunk" in wrong_field.json()["message"]

    text_session = _open_session(client, "text")
    wrong_modality = client.post(
        f"/api/v1/sessions/{text_session}/recording/chunks",
        params={"seq": 0},
        files={"chunk": ("chunk-0.webm", b"not-voice", "audio/webm")},
    )
    assert wrong_modality.status_code == 409

    unknown = client.post(
        "/api/v1/sessions/no-such-session/recording/chunks",
        params={"seq": 0},
        files={"chunk": ("chunk-0.webm", b"bytes", "audio/webm")},
    )
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_allowed_origins_reads_a_trimmed_comma_separated_list(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    assert cors_allowed_origins() == []

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "   ")
    assert cors_allowed_origins() == []

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", " http://localhost:3002 ,https://portal.example ,")
    assert cors_allowed_origins() == ["http://localhost:3002", "https://portal.example"]


def test_a_named_origin_gets_a_preflight_and_credentials(monkeypatch, repo):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3002")
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo

    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/interviews",
            headers={
                "Origin": "http://localhost:3002",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3002"
        assert preflight.headers["access-control-allow-credentials"] == "true"

        # The credential header must ride on the real response too, or the
        # browser discards the body it just fetched with the org cookie.
        actual = client.get("/api/v1/interviews", headers={"Origin": "http://localhost:3002"})
        assert actual.status_code == 200
        assert actual.headers["access-control-allow-origin"] == "http://localhost:3002"
        assert actual.headers["access-control-allow-credentials"] == "true"


def test_an_unnamed_origin_gets_no_cors_headers(monkeypatch, repo):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3002")
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo

    with TestClient(app) as client:
        resp = client.get("/api/v1/interviews", headers={"Origin": "http://evil.example"})

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_with_the_variable_unset_no_cors_middleware_is_installed(monkeypatch, repo):
    # `build_app` calls `load_dotenv`, and a developer's own .env must not be
    # able to decide what "unset" means in this test.
    monkeypatch.setattr(main_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo

    with TestClient(app) as client:
        resp = client.get("/api/v1/interviews", headers={"Origin": "http://localhost:3002"})
        preflight = client.options(
            "/api/v1/interviews",
            headers={
                "Origin": "http://localhost:3002",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 200
    assert not [h for h in resp.headers if h.lower().startswith("access-control-")]
    assert not [h for h in preflight.headers if h.lower().startswith("access-control-")]
