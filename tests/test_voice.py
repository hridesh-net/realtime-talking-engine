"""Offline tests for the voice session — compilation, credential minting, ingest.

No audio, no vendor call, no network. The realtime broker is faked, which is the
whole point of it being a port: everything this service decides about a voice
session is decided *before* the vendor is involved, so it is all testable here.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from candidate_agent.voice import TRANSCRIBE_MODEL, build_realtime_session, pick_voice
from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from llm.base import ModelError, RealtimeBroker, RealtimeCredential
from tests.test_session import CONTRACT, _seed_candidate

VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage")


def _contract(**overrides: Any):
    """The shared contract with voice directives swapped in."""
    return CONTRACT.model_copy(update=overrides)


class FakeBroker(RealtimeBroker):
    """Records the session document it was handed and returns a dummy secret."""

    def __init__(self, fail: bool = False) -> None:
        super().__init__("fake-realtime-1")
        self._fail = fail
        self.session: dict[str, Any] | None = None
        self.ttl: int | None = None

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def voices(self) -> tuple[str, ...]:
        return VOICES

    async def mint(self, *, session: dict[str, Any], ttl_seconds: int) -> RealtimeCredential:
        if self._fail:
            raise ModelError("vendor said no")
        self.session = session
        self.ttl = ttl_seconds
        return RealtimeCredential(
            value="ek_fake_secret",
            expires_at=1787421438,
            model=self.model_id,
            call_url="https://example.invalid/calls",
        )


# ---------------------------------------------------------------------------
# Deterministic compilation
# ---------------------------------------------------------------------------


def test_voice_is_stable_for_a_persona_and_spread_across_personas():
    assert pick_voice("vc-abc123", VOICES) == pick_voice("vc-abc123", VOICES)
    chosen = {pick_voice(f"vc-{i:06d}", VOICES) for i in range(60)}
    assert len(chosen) > 1, "voice assignment collapsed onto one voice"
    assert chosen <= set(VOICES)


def test_no_voices_available_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError):
        pick_voice("vc-abc123", ())


def test_instructions_carry_the_contract_prompt_verbatim():
    session = build_realtime_session(CONTRACT, voices=VOICES)
    instructions = session["instructions"]
    assert instructions.startswith(CONTRACT.system_prompt)
    assert "live voice call" in instructions
    assert "never exceed 6" in instructions, "turn policy did not reach the spoken prompt"
    # The persona must not be talked out of character by the interviewer.
    # Matched on a fragment that does not straddle the preamble's line wrap.
    assert "a persona, or a simulation" in instructions


def test_pace_drives_speed_and_eagerness():
    slow = build_realtime_session(_contract(voice_directives={"pace": "slow"}), voices=VOICES)
    fast = build_realtime_session(_contract(voice_directives={"pace": "fast"}), voices=VOICES)
    assert slow["audio"]["output"]["speed"] < 1.0 < fast["audio"]["output"]["speed"]
    assert slow["audio"]["input"]["turn_detection"]["eagerness"] == "low"
    assert fast["audio"]["input"]["turn_detection"]["eagerness"] == "high"


def test_an_interrupting_persona_overrides_pace():
    session = build_realtime_session(
        _contract(voice_directives={"pace": "slow", "may_interrupt": True}), voices=VOICES
    )
    assert session["audio"]["input"]["turn_detection"]["eagerness"] == "high"


def test_the_human_can_always_interrupt_and_is_always_transcribed():
    """Two properties no persona may switch off."""
    for directives in ({"pace": "slow"}, {"pace": "fast", "may_interrupt": True}):
        session = build_realtime_session(_contract(voice_directives=directives), voices=VOICES)
        assert session["audio"]["input"]["turn_detection"]["interrupt_response"] is True
        assert session["audio"]["input"]["transcription"]["model"] == TRANSCRIBE_MODEL


def test_unknown_pace_falls_back_rather_than_raising():
    session = build_realtime_session(_contract(voice_directives={"pace": "brisk"}), voices=VOICES)
    assert session["audio"]["output"]["speed"] == 1.0
    assert session["audio"]["input"]["turn_detection"]["eagerness"] == "medium"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


@pytest.fixture
def repo() -> InterviewRepository:
    return InterviewRepository(init_db(":memory:"))


def test_a_voice_session_does_not_prewrite_the_opening_line(repo):
    """The persona *says* it. Writing it here too would duplicate turn 0."""
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi, thanks for the time.",
        modality="voice",
    )
    assert session.modality == "voice"
    assert session.turns == []
    assert session.opening_line == "Hi, thanks for the time."


def test_a_text_session_still_prewrites_it(repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi.",
    )
    assert [t.speaker for t in session.turns] == ["candidate"]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def client(repo, broker):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_realtime_broker] = lambda: broker
    with TestClient(app) as c:
        yield c


def _open_voice_session(client, interview_id: str) -> str:
    res = client.post(
        "/api/v1/sessions",
        json={
            "interview_id": interview_id,
            "archetype": "nervous_fresher",
            "modality": "voice",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_minting_seals_the_persona_and_never_leaks_it(client, repo, broker):
    interview_id, _ = _seed_candidate(repo)
    session_id = _open_voice_session(client, interview_id)

    res = client.post(f"/api/v1/sessions/{session_id}/realtime")
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["client_secret"] == "ek_fake_secret"
    assert body["voice"] in VOICES
    assert body["call_url"].startswith("https://")
    # The browser gets a secret and a URL — never the prompt or the ceilings.
    serialized = res.text
    assert CONTRACT.system_prompt not in serialized
    assert "instructions" not in body

    assert broker.session is not None
    assert broker.session["instructions"].startswith(CONTRACT.system_prompt)
    assert broker.ttl == api_module.REALTIME_TTL_SECONDS


def test_transcript_records_without_generating_a_reply(client, repo):
    interview_id, _ = _seed_candidate(repo)
    session_id = _open_voice_session(client, interview_id)

    first = client.post(
        f"/api/v1/sessions/{session_id}/transcript",
        json={"speaker": "candidate", "text": "Hi, thanks for having me."},
    )
    assert first.status_code == 201
    assert first.json()["index"] == 0

    second = client.post(
        f"/api/v1/sessions/{session_id}/transcript",
        json={"speaker": "manager", "text": "Tell me about your last role."},
    )
    assert second.json()["index"] == 1

    stored = client.get(f"/api/v1/sessions/{session_id}").json()
    assert [t["speaker"] for t in stored["turns"]] == ["candidate", "manager"]
    assert stored["modality"] == "voice"


def test_a_client_supplied_speaker_must_be_a_real_speaker(client, repo):
    interview_id, _ = _seed_candidate(repo)
    session_id = _open_voice_session(client, interview_id)
    res = client.post(
        f"/api/v1/sessions/{session_id}/transcript",
        json={"speaker": "narrator", "text": "hello"},
    )
    assert res.status_code == 422


def test_a_finished_session_refuses_both_minting_and_transcript(client, repo):
    interview_id, _ = _seed_candidate(repo)
    session_id = _open_voice_session(client, interview_id)
    client.post(f"/api/v1/sessions/{session_id}/end")

    assert client.post(f"/api/v1/sessions/{session_id}/realtime").status_code == 409
    assert (
        client.post(
            f"/api/v1/sessions/{session_id}/transcript",
            json={"speaker": "manager", "text": "late"},
        ).status_code
        == 409
    )


def test_unknown_session_is_404(client):
    assert client.post("/api/v1/sessions/nope/realtime").status_code == 404
    assert (
        client.post(
            "/api/v1/sessions/nope/transcript", json={"speaker": "manager", "text": "hi"}
        ).status_code
        == 404
    )


def test_a_deleted_persona_stops_the_call_but_keeps_the_session(client, repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session_id = _open_voice_session(client, interview_id)
    repo.delete_candidate(candidate_id)

    assert client.post(f"/api/v1/sessions/{session_id}/realtime").status_code == 410
    assert client.get(f"/api/v1/sessions/{session_id}").status_code == 200


def test_a_vendor_failure_is_reported_as_a_gateway_error(repo):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_realtime_broker] = lambda: FakeBroker(fail=True)
    with TestClient(app) as client:
        interview_id, _ = _seed_candidate(repo)
        session_id = _open_voice_session(client, interview_id)
        res = client.post(f"/api/v1/sessions/{session_id}/realtime")
    assert res.status_code == 502
    assert "vendor said no" in res.json()["detail"]


def test_voice_capability_is_an_answer_not_an_error(client, monkeypatch):
    monkeypatch.setattr(api_module, "realtime_providers_available", lambda: [])
    body = client.get("/api/v1/voice-capability").json()
    assert body["available"] is False
    assert body["providers"] == []
    assert "OPENAI_API_KEY" in body["detail"]
