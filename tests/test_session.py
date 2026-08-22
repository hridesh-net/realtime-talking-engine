"""Offline tests for the live text session — agent, storage, and endpoints.

No model calls, no network, no file-backed database. The session agent is
exercised against a fake ChatModel that records exactly what it was handed, so
the guarantees that matter (system prompt verbatim, history in order) are
asserted on the real call arguments rather than on a mock's shape.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candidate_agent import engine_contract as ec
from candidate_agent.schema import (
    AnswerPolicy,
    AptitudeProfile,
    EngineContract,
    InterviewerScorecard,
    ScorecardItem,
    SkillKnowledge,
    SpeechProfile,
    VirtualCandidate,
)
from candidate_agent.session import SESSION_OPENER, CandidateSessionAgent
from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from control_plane.schemas import InterviewCreateRequest
from llm.base import ChatMessage, ChatModel, ModelError

CONTRACT = EngineContract(
    candidate_id="cand-1",
    interview_id="iv-1",
    system_prompt="You are Rhea Kulkarni, a job candidate.\nBACKGROUND\nField sales, 4 years.",
    opening_line="Hi, yeah — thanks for making the time.",
    voice_directives={"pace": "measured"},
    turn_policy={"target_sentences_per_answer": 3, "max_sentences": 6},
    knowledge_ceiling={"territory management": 5},
    unlock_condition="asked for a specific example",
    forbidden_behaviors=["Never break character"],
)


class FakeChatModel(ChatModel):
    """Records the last call and replies with a fixed line."""

    def __init__(self, reply: str = "Umm, yeah, so — I handled the north zone.") -> None:
        super().__init__("fake-chat-1", 0.8)
        self._reply = reply
        self.system: str | None = None
        self.messages: list[ChatMessage] = []

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_text(self, *, system: str, messages: list[ChatMessage]) -> str:
        self.system = system
        self.messages = list(messages)
        return self._reply


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


async def test_system_prompt_is_passed_verbatim():
    model = FakeChatModel()
    await CandidateSessionAgent(model).reply(
        CONTRACT, [{"speaker": "candidate", "text": CONTRACT.opening_line}]
    )
    assert model.system is not None
    assert model.system.startswith(CONTRACT.system_prompt), (
        "the compiled contract prompt must reach the model unedited"
    )
    assert "typed conversation" in model.system, "the text-mode preamble is missing"
    assert "never exceed 6" in model.system, "the turn policy did not reach the prompt"


async def test_history_is_ordered_and_roles_are_mapped():
    model = FakeChatModel()
    transcript = [
        {"speaker": "candidate", "text": "opening"},
        {"speaker": "manager", "text": "first question"},
        {"speaker": "candidate", "text": "first answer"},
        {"speaker": "manager", "text": "second question"},
    ]
    await CandidateSessionAgent(model).reply(CONTRACT, transcript)

    # The scene-setting turn is prepended because providers reject a history
    # that opens on the assistant; every real turn keeps its place after it.
    assert model.messages[0] == {"role": "user", "content": SESSION_OPENER}
    assert [m["role"] for m in model.messages[1:]] == [
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert [m["content"] for m in model.messages[1:]] == [t["text"] for t in transcript]


async def test_a_manager_opened_transcript_needs_no_scene_setting():
    model = FakeChatModel()
    await CandidateSessionAgent(model).reply(CONTRACT, [{"speaker": "manager", "text": "hello"}])
    assert model.messages == [{"role": "user", "content": "hello"}]


async def test_empty_transcript_is_rejected():
    with pytest.raises(ModelError):
        await CandidateSessionAgent(FakeChatModel()).reply(CONTRACT, [])


def test_agent_does_not_persist():
    """The agent holds a model and nothing else — no connection, no store."""
    agent = CandidateSessionAgent(FakeChatModel())
    assert set(vars(agent)) == {"_model"}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


@pytest.fixture
def repo() -> InterviewRepository:
    return InterviewRepository(init_db(":memory:"))


def _persona(interview_id: str) -> VirtualCandidate:
    """A cast persona built in code — the casting agent is not exercised here."""
    return VirtualCandidate(
        candidate_id="cand-1",
        interview_id=interview_id,
        archetype="nervous_fresher",
        archetype_label="Nervous but capable",
        catalog_version="v1.0",
        name="Rhea Kulkarni",
        headline="Field sales, 4 years, north zone",
        background="Four years selling prepaid activations through channel partners.",
        years_experience=4,
        verdict="borderline",
        verdict_rationale="Capable once settled; first ten minutes read badly.",
        speech_profile=SpeechProfile(
            pace="measured",
            verbosity="balanced",
            filler_frequency=7,
            hesitation_frequency=8,
            formality="neutral",
            interrupts_interviewer=False,
            tone="anxious but willing",
        ),
        aptitude=AptitudeProfile(
            smartness=7,
            dumbness=3,
            smartness_ratio=0.7,
            seriousness=7,
            effort=7,
            interest=8,
            honesty=8,
            preparedness=6,
            nervousness=8,
        ),
        knowledge_map=[
            SkillKnowledge(
                skill="territory management",
                level=5,
                stance="solid",
                breaking_point="asked to model a quarter of coverage",
            )
        ],
        answer_policy=AnswerPolicy(
            default_answer_depth="adequate",
            reveals_depth_when="asked for a specific example",
            on_unknown_question="says so",
            on_pressure="tightens up",
            on_silence="fills the gap",
        ),
        interviewer_scorecard=InterviewerScorecard(
            expected_verdict="borderline",
            interviewer_challenge="settle the candidate before judging them",
            must_discover=[
                ScorecardItem(
                    id="only",
                    signal="real ownership of the north zone",
                    weight=1.0,
                    how_to_surface="ask for one deal end to end",
                )
            ],
            interviewer_failure_modes=["reads nerves as incompetence"],
            pass_condition="surfaces the ownership signal",
        ),
        engine_contract=EngineContract(
            candidate_id="cand-1",
            interview_id=interview_id,
            system_prompt=CONTRACT.system_prompt,
            opening_line="Hi, yeah — thanks for making the time.",
            voice_directives=CONTRACT.voice_directives,
            turn_policy=CONTRACT.turn_policy,
            knowledge_ceiling=CONTRACT.knowledge_ceiling,
            unlock_condition=CONTRACT.unlock_condition,
            forbidden_behaviors=CONTRACT.forbidden_behaviors,
        ),
        fingerprint="f" * 8,
        seed_fingerprint="s" * 8,
        seed="seed",
    )


def _seed_candidate(repo: InterviewRepository) -> tuple[str, str]:
    """Create an interview and store a persona for it, without calling a model."""
    interview = repo.create(
        InterviewCreateRequest(
            job_title="Field Sales Executive",
            jd="Sell prepaid activations through channel partners.",
            skills_required=["territory management"],
            job_location_type="onsite",
            experience_level="mid",
            company_type="mnc",
        )
    )
    repo.save_candidate(_persona(interview.id), model_used="offline-fixture")
    return interview.id, "cand-1"


def test_session_opens_with_the_personas_opening_line(repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi, thanks for the time.",
    )
    assert session.status == "live"
    assert session.candidate_name == "Rhea Kulkarni"
    assert [(t.index, t.speaker, t.text) for t in session.turns] == [
        (0, "candidate", "Hi, thanks for the time.")
    ]
    assert session.turns[0].elapsed_ms == 0


def test_turns_are_indexed_and_stamped_in_order(repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi.",
    )
    repo.append_turn(session.id, "manager", "Tell me about your last role.")
    repo.append_turn(session.id, "candidate", "Umm, sure.")

    stored = repo.get_session(session.id)
    assert [t.index for t in stored.turns] == [0, 1, 2]
    assert [t.speaker for t in stored.turns] == ["candidate", "manager", "candidate"]
    assert all(t.elapsed_ms >= 0 for t in stored.turns)
    assert stored.turns[2].at >= stored.turns[1].at


def test_ending_a_session_is_idempotent_and_keeps_the_transcript(repo):
    interview_id, candidate_id = _seed_candidate(repo)
    session = repo.create_session(
        interview_id=interview_id,
        candidate_id=candidate_id,
        persona_key="nervous_fresher",
        planned_minutes=20,
        opening_line="Hi.",
    )
    ended = repo.end_session(session.id)
    assert ended.status == "completed"
    assert ended.ended_at is not None
    again = repo.end_session(session.id)
    assert again.status == "completed"
    assert again.ended_at == ended.ended_at, "re-ending must not move the clock"
    assert len(again.turns) == 1
    assert repo.end_session("no-such-session") is None


def test_appending_to_an_unknown_session_raises(repo):
    with pytest.raises(KeyError):
        repo.append_turn("no-such-session", "manager", "hello")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def client(repo):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_session_agent] = lambda: CandidateSessionAgent(
        FakeChatModel("Umm — I ran the north zone for about two years.")
    )
    with TestClient(app) as c:
        yield c


def test_full_session_round_trip(client, repo):
    interview_id, _ = _seed_candidate(repo)

    created = client.post(
        "/api/v1/sessions",
        json={
            "interview_id": interview_id,
            "archetype": "nervous_fresher",
            "planned_minutes": 20,
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    turn = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"text": "Walk me through your last role."},
    )
    assert turn.status_code == 201, turn.text
    assert turn.json()["speaker"] == "candidate"
    assert turn.json()["index"] == 2

    ended = client.post(f"/api/v1/sessions/{session_id}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "completed"

    # A finished session refuses further turns rather than silently reopening.
    assert (
        client.post(f"/api/v1/sessions/{session_id}/turns", json={"text": "one more"}).status_code
        == 409
    )

    fetched = client.get(f"/api/v1/sessions/{session_id}").json()
    assert [t["speaker"] for t in fetched["turns"]] == ["candidate", "manager", "candidate"]
    assert fetched["modality"] == "text"


def test_sessions_are_listed_for_their_interview(client, repo):
    """The detail screen's table: what has been run here, without transcripts."""
    interview_id, _ = _seed_candidate(repo)

    assert client.get(f"/api/v1/interviews/{interview_id}/sessions").json() == []
    # An unknown interview is answered with "nothing", not an error.
    assert client.get("/api/v1/interviews/nope/sessions").json() == []

    session_id = client.post(
        "/api/v1/sessions",
        json={"interview_id": interview_id, "archetype": "nervous_fresher"},
    ).json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/turns", json={"text": "Tell me about the role."})

    rows = client.get(f"/api/v1/interviews/{interview_id}/sessions").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == session_id
    assert row["persona_key"] == "nervous_fresher"
    assert row["status"] == "live"
    assert row["turn_count"] == 3  # opener + manager + reply
    assert "turns" not in row  # the summary must not carry the evidence


def _seed_custom_persona(repo: InterviewRepository) -> tuple[str, str]:
    """Compose, register, and store a dynamic persona.

    Same shape a real `custom_personas` enrollment produces, but with no
    model call, so this stays a pure offline test.
    """
    from candidate_agent import archetypes as archetype_catalog
    from candidate_agent import trait_dimensions as td
    from candidate_agent.engine_contract import build_engine_contract

    interview = repo.create(
        InterviewCreateRequest(
            job_title="Field Sales Executive",
            jd="Sell prepaid activations through channel partners.",
            skills_required=["territory management"],
            job_location_type="onsite",
            experience_level="mid",
            company_type="mnc",
        )
    )

    key = "dyn-test-session-key"
    td.compose_archetype(
        key=key,
        label="Custom session-test persona",
        verdict="borderline",
        competence="developing",
        conscientiousness="adequate",
        communication="guarded",
        emotional_stance="defensive",
        honesty="embellishing",
        bias_trap="career_gap",
    )
    # Composing does not register: the session has to work off the stored
    # candidate alone, which is the whole point of the lookup order in
    # `start_session`.
    assert key not in archetype_catalog.ARCHETYPES
    human_traits = td.compose_human_traits(
        affect="defensive",
        verbal_style="monosyllabic",
        language="hinglish_code_switcher",
        comprehension="frequent_clarifier",
        motivation="family_pressured",
        negotiation_stance="refuses_to_disclose_ctc",
        environment="spotty_home_network",
        seniority="junior",
        function="network",
        region="UP",
        gender_presentation="woman",
        age_band="25-34",
        notice_period="30_days",
        compliance_traps=["volunteers_protected_info"],
        protected_info_type="marital_status",
    )
    engine_contract = build_engine_contract(
        candidate_id="cand-custom-1",
        interview_id=interview.id,
        name="Kavita Patel",
        headline="Field sales, 2 years",
        background="Two years selling prepaid activations.",
        years_experience=2,
        speech=SpeechProfile(
            pace="measured",
            verbosity="terse",
            filler_frequency=3,
            hesitation_frequency=3,
            formality="casual",
            interrupts_interviewer=False,
            tone="guarded",
        ),
        aptitude=AptitudeProfile(
            smartness=5,
            dumbness=4,
            smartness_ratio=0.56,
            seriousness=6,
            effort=6,
            interest=6,
            honesty=5,
            preparedness=5,
            nervousness=5,
        ),
        knowledge_map=[
            SkillKnowledge(
                skill="territory management",
                level=4,
                stance="shallow",
                breaking_point="asked to model a quarter of coverage",
            )
        ],
        policy=AnswerPolicy(
            default_answer_depth="adequate",
            reveals_depth_when="asked for a specific example",
            on_unknown_question="admits the gap",
            on_pressure="gets clipped and guarded",
            on_silence="waits",
        ),
        opening_line="Hi.",
        human_traits=human_traits,
    )
    candidate = VirtualCandidate(
        candidate_id="cand-custom-1",
        interview_id=interview.id,
        archetype=key,
        archetype_label="Custom session-test persona",
        catalog_version=archetype_catalog.CATALOG_VERSION,
        name="Kavita Patel",
        headline="Field sales, 2 years",
        background="Two years selling prepaid activations.",
        years_experience=2,
        verdict="borderline",
        verdict_rationale="Developing, embellishes under pressure.",
        speech_profile=SpeechProfile(
            pace="measured",
            verbosity="terse",
            filler_frequency=3,
            hesitation_frequency=3,
            formality="casual",
            interrupts_interviewer=False,
            tone="guarded",
        ),
        aptitude=AptitudeProfile(
            smartness=5,
            dumbness=4,
            smartness_ratio=0.56,
            seriousness=6,
            effort=6,
            interest=6,
            honesty=5,
            preparedness=5,
            nervousness=5,
        ),
        knowledge_map=[
            SkillKnowledge(
                skill="territory management",
                level=4,
                stance="shallow",
                breaking_point="asked to model a quarter of coverage",
            )
        ],
        answer_policy=AnswerPolicy(
            default_answer_depth="adequate",
            reveals_depth_when="asked for a specific example",
            on_unknown_question="admits the gap",
            on_pressure="gets clipped and guarded",
            on_silence="waits",
        ),
        interviewer_scorecard=InterviewerScorecard(
            expected_verdict="borderline",
            interviewer_challenge="stay bias-free about the career gap",
            must_discover=[
                ScorecardItem(
                    id="only",
                    signal="bias-free handling of the volunteered career gap",
                    weight=1.0,
                    how_to_surface="watch the follow-up after the gap is mentioned",
                )
            ],
            interviewer_failure_modes=["asks about marital status instead of readiness"],
            pass_condition="surfaces the bias-free signal",
        ),
        engine_contract=engine_contract,
        human_traits=human_traits,
        fingerprint="f" * 8,
        seed_fingerprint="s" * 8,
        seed="seed",
    )
    repo.save_candidate(candidate, model_used="offline-fixture")
    return interview.id, key


def test_session_round_trip_with_a_custom_composed_persona(client, repo):
    """Confirm the wizard/Compose-tab custom-persona path works end to end.

    compose (trait_dimensions) -> register -> stored VirtualCandidate with
    human_traits -> start a session -> take a turn. Confirms the REALISM &
    COMPLIANCE LAYER reaches the live chat model's system prompt, not just
    the stored persona document.
    """
    interview_id, key = _seed_custom_persona(repo)

    # The client fixture's own override builds a fresh FakeChatModel per
    # call, so re-invoking it here would inspect an instance that was never
    # actually used. Override with one captured instance instead.
    captured = FakeChatModel("Umm — I ran the north zone for about two years.")
    client.app.dependency_overrides[api_module.get_session_agent] = lambda: CandidateSessionAgent(
        captured
    )

    created = client.post(
        "/api/v1/sessions",
        json={"interview_id": interview_id, "archetype": key, "planned_minutes": 20},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    turn = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"text": "Tell me about a gap I noticed in your resume."},
    )
    assert turn.status_code == 201, turn.text
    assert turn.json()["speaker"] == "candidate"

    assert captured.system is not None
    assert "HOW YOU COME ACROSS" in captured.system
    assert (
        # The persona is told "marital status", not the vocabulary key.
        ec.COMPLIANCE_TRAP_DIRECTIVES["volunteers_protected_info"].format(
            protected_info_type="marital status"
        )
        in captured.system
    )


def test_unknown_interview_and_archetype_are_rejected(client, repo):
    interview_id, _ = _seed_candidate(repo)
    assert (
        client.post(
            "/api/v1/sessions", json={"interview_id": "nope", "archetype": "nervous_fresher"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/sessions", json={"interview_id": interview_id, "archetype": "not_a_persona"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/sessions/nope").status_code == 404
