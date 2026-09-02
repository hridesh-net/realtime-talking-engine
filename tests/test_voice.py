"""Offline tests for the voice session — compilation, credential minting, ingest.

No audio, no vendor call, no network. The realtime broker is faked, which is the
whole point of it being a port: everything this service decides about a voice
session is decided *before* the vendor is involved, so it is all testable here.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from candidate_agent.engine_contract import GEMINI_TTS_VOICES
from candidate_agent.voice import (
    IN_SESSION_STT,
    NOISE_REDUCTION,
    TRANSCRIBE_MODEL,
    build_gemini_live_session,
    build_realtime_session,
    build_voice_session,
    pick_voice,
)
from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from llm.base import ModelError, RealtimeBroker, RealtimeCredential
from llm.gemini_live import GEMINI_FEMALE_VOICES, GEMINI_LIVE_VOICES, GEMINI_MALE_VOICES
from tests.test_session import CONTRACT, _seed_candidate

VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage")


def _contract(**overrides: Any):
    """The shared contract with voice directives swapped in."""
    return CONTRACT.model_copy(update=overrides)


class FakeBroker(RealtimeBroker):
    """Records the session document it was handed and returns a dummy secret.

    Answers ``openai`` by default because the session compiler dispatches on the
    provider name — a broker claiming to be something nobody can compile for is
    its own (separately tested) error.
    """

    def __init__(self, fail: bool = False, provider: str = "openai") -> None:
        super().__init__("fake-realtime-1")
        self._fail = fail
        self._provider = provider
        self.session: dict[str, Any] | None = None
        self.ttl: int | None = None

    @property
    def provider(self) -> str:
        return self._provider

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


class FakeGeminiBroker(FakeBroker):
    """A broker that answers ``gemini``: WebSocket, no call URL, its own roster."""

    def __init__(self) -> None:
        super().__init__(provider="gemini")

    @property
    def voices(self) -> tuple[str, ...]:
        return GEMINI_LIVE_VOICES

    async def mint(self, *, session: dict[str, Any], ttl_seconds: int) -> RealtimeCredential:
        await super().mint(session=session, ttl_seconds=ttl_seconds)
        return RealtimeCredential(
            value="auth_tokens/fake",
            expires_at=1787421438,
            model=self.model_id,
            call_url="",
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


def test_the_opening_line_is_delivered_by_instruction_not_by_a_written_turn():
    """A spoken session has no turn 0 to write it into, so the model is told."""
    session = build_realtime_session(CONTRACT, voices=VOICES)
    instructions = session["instructions"]
    assert CONTRACT.opening_line in instructions
    assert "THE FIRST THING YOU SAY" in instructions
    # The contract prompt itself is still injected untouched, ahead of it.
    assert instructions.startswith(CONTRACT.system_prompt)


def test_a_contract_without_an_opening_line_gets_no_opening_block():
    """Hand-built contracts stay valid; the persona just greets as it would."""
    instructions = build_realtime_session(_contract(opening_line=""), voices=VOICES)["instructions"]
    assert "THE FIRST THING YOU SAY" not in instructions


def test_the_transcriber_is_injected_not_hardcoded():
    session = build_realtime_session(CONTRACT, voices=VOICES, transcribe_model="whisper-9")
    assert session["audio"]["input"]["transcription"]["model"] == "whisper-9"


def test_the_transcriber_is_told_which_words_to_expect():
    """The contract's skills are exactly the nouns a transcriber mangles."""
    session = build_realtime_session(CONTRACT, voices=VOICES)
    prompt = session["audio"]["input"]["transcription"]["prompt"]
    for skill in CONTRACT.knowledge_ceiling:
        assert skill in prompt
    # Composed in code from a sorted list, so it is the same string every time.
    assert (
        prompt
        == build_realtime_session(CONTRACT, voices=VOICES)["audio"]["input"]["transcription"][
            "prompt"
        ]
    )


def test_the_model_hears_a_denoised_mic():
    session = build_realtime_session(CONTRACT, voices=VOICES)
    assert session["audio"]["input"]["noise_reduction"] == {"type": NOISE_REDUCTION}


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
# Gemini Live — the same decisions, the other vendor's shape
# ---------------------------------------------------------------------------


def test_gemini_instructions_carry_the_contract_prompt_and_the_opening_line():
    session = build_gemini_live_session(CONTRACT, voices=GEMINI_LIVE_VOICES)
    instructions = session["system_instruction"]
    assert instructions.startswith(CONTRACT.system_prompt)
    assert CONTRACT.opening_line in instructions
    assert "live voice call" in instructions


def test_gemini_speaks_in_the_voice_the_persona_was_cast_with():
    """Stored at cast time, so the persona sounds the same everywhere."""
    session = build_gemini_live_session(
        _contract(tts_voice_id="Sulafat"), voices=GEMINI_LIVE_VOICES
    )
    assert session["voice"] == "Sulafat"


def test_gemini_falls_back_to_the_same_rule_when_no_voice_was_stored():
    session = build_gemini_live_session(_contract(tts_voice_id=""), voices=GEMINI_LIVE_VOICES)
    assert session["voice"] == pick_voice(CONTRACT.candidate_id, GEMINI_LIVE_VOICES)


def test_gemini_turn_detection_follows_pace_and_stays_conversational():
    """Same intent as `eagerness`, expressed as a silence timer."""
    silences = {}
    for pace in ("slow", "measured", "fast"):
        session = build_gemini_live_session(
            _contract(voice_directives={"pace": pace}), voices=GEMINI_LIVE_VOICES
        )
        vad = session["client_config"]["realtimeInputConfig"]["automaticActivityDetection"]
        silences[pace] = vad["silenceDurationMs"]
        assert 500 <= vad["silenceDurationMs"] <= 800
        assert vad["prefixPaddingMs"] > 0
    assert silences["fast"] < silences["measured"] < silences["slow"]


def test_gemini_transcribes_both_sides_and_can_survive_the_session_cap():
    config = build_gemini_live_session(CONTRACT, voices=GEMINI_LIVE_VOICES)["client_config"]
    assert config["responseModalities"] == ["AUDIO"]
    assert "inputAudioTranscription" in config, "the interviewer would go unrecorded"
    assert "outputAudioTranscription" in config, "the persona would go unrecorded"
    assert "sessionResumption" in config, "a 15-minute cap would end the interview"
    assert config["historyConfig"]["initialHistoryInClientContent"] is True
    assert config["realtimeInputConfig"]["activityHandling"] == "START_OF_ACTIVITY_INTERRUPTS", (
        "the human must always be able to cut the persona off"
    )


def test_the_client_config_never_carries_the_persona():
    """It is handed to the browser verbatim, so this is the whole no-leak rule."""
    serialized = repr(
        build_gemini_live_session(CONTRACT, voices=GEMINI_LIVE_VOICES)["client_config"]
    )
    assert CONTRACT.system_prompt not in serialized
    assert CONTRACT.opening_line not in serialized


def test_the_voice_roster_has_exactly_one_source_of_truth():
    """Cast time reads one tuple and session time the other; they are one object."""
    assert GEMINI_LIVE_VOICES is GEMINI_TTS_VOICES
    assert len(GEMINI_LIVE_VOICES) == 30


def test_the_gender_sets_partition_the_roster():
    """Every voice is classified, exactly once, and nothing is classified twice.

    The classification is a vendor fact (Google's Gemini-TTS voice table), and
    casting reads it to keep a persona's voice consistent with how it presents.
    A voice in neither set would be unreachable for a gendered persona; a voice
    in both would make the "matching" claim meaningless. A voice appended to
    the roster without being classified fails here — that is the point.
    """
    roster = set(GEMINI_LIVE_VOICES)
    assert roster == GEMINI_FEMALE_VOICES | GEMINI_MALE_VOICES
    assert not (GEMINI_FEMALE_VOICES & GEMINI_MALE_VOICES)
    assert len(GEMINI_FEMALE_VOICES) + len(GEMINI_MALE_VOICES) == len(GEMINI_LIVE_VOICES)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_the_dispatcher_compiles_the_shape_the_provider_speaks():
    gemini = build_voice_session(CONTRACT, provider="gemini", voices=GEMINI_LIVE_VOICES)
    openai = build_voice_session(CONTRACT, provider="openai", voices=VOICES)
    assert "client_config" in gemini and "audio" not in gemini
    assert "audio" in openai and "client_config" not in openai


def test_the_dispatcher_passes_the_configured_transcriber_through():
    session = build_voice_session(
        CONTRACT, provider="openai", voices=VOICES, transcribe_model="whisper-9"
    )
    assert session["audio"]["input"]["transcription"]["model"] == "whisper-9"


def test_an_unknown_provider_is_refused_rather_than_guessed_at():
    """Compiling one vendor's document for another's endpoint fails unreadably."""
    with pytest.raises(ValueError, match="carrier-pigeon"):
        build_voice_session(CONTRACT, provider="carrier-pigeon", voices=VOICES)


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
    assert body["provider"] == "openai"
    assert body["stt_source"] == TRANSCRIBE_MODEL
    assert body["noise_reduction"] == NOISE_REDUCTION
    # The browser gets a secret and a URL — never the prompt or the ceilings.
    serialized = res.text
    assert CONTRACT.system_prompt not in serialized
    assert CONTRACT.opening_line not in serialized
    assert "instructions" not in body
    assert body["client_config"] == {}

    assert broker.session is not None
    assert broker.session["instructions"].startswith(CONTRACT.system_prompt)
    assert broker.ttl == api_module.REALTIME_TTL_SECONDS


def test_minting_on_gemini_returns_the_connect_config_and_still_seals_the_persona(repo):
    app = build_app(":memory:")
    broker = FakeGeminiBroker()
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_realtime_broker] = lambda: broker
    with TestClient(app) as client:
        interview_id, _ = _seed_candidate(repo)
        session_id = _open_voice_session(client, interview_id)
        res = client.post(f"/api/v1/sessions/{session_id}/realtime")

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["provider"] == "gemini"
    assert body["voice"] in GEMINI_LIVE_VOICES
    # The SDK owns the endpoint, so there is nothing for the browser to POST to.
    assert body["call_url"] == ""
    assert body["stt_source"] == IN_SESSION_STT
    assert body["noise_reduction"] == ""
    # The browser must be able to connect, so it gets the connect parameters…
    assert body["client_config"]["responseModalities"] == ["AUDIO"]
    assert "sessionResumption" in body["client_config"]
    # …and nothing else. The persona went into the token, not into the response.
    assert CONTRACT.system_prompt not in res.text
    assert CONTRACT.opening_line not in res.text
    assert broker.session is not None
    assert broker.session["system_instruction"].startswith(CONTRACT.system_prompt)
    assert CONTRACT.opening_line in broker.session["system_instruction"]


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
    assert "GEMINI_API_KEY" in body["detail"]
    assert "OPENAI_API_KEY" in body["detail"]
