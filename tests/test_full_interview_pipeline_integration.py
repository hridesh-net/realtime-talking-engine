"""Integration tests: the full manager-facing interview flow, for multiple personas.

Drives the real HTTP surface a hiring manager would use, end to end:

    create interview -> compose/cast a persona -> read its report (the
    InterviewerScorecard, the only "what should I have caught" document that
    exists today, see `okf/concepts/subsystems/candidate-agent.md`) -> run a
    multi-turn practice session as the interviewer -> end it -> re-read the
    transcript and the report.

Repeated across a spread of persona compositions (every bias trap plus none,
weak/strong/dishonest/guarded combinations, and a hand-written catalog
archetype for comparison), plus the edge cases a manager would actually hit:
a persona never engaged, two personas practised in parallel, unknown ids,
re-casting the same spec, and a live session read mid-conversation.

No network, no cost: casting uses a deterministic fake `StructuredModel`,
session turns use a deterministic fake `ChatModel`. What's under test is the
control plane's wiring and the code-owned report content — not model output
quality, which `tests/test_custom_persona_integration.py` already covers
adversarially at the agent layer.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from candidate_agent import archetypes as archetype_catalog
from candidate_agent import trait_dimensions as td
from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.session import CandidateSessionAgent
from control_plane.api import get_candidate_agent, get_session_agent
from control_plane.main import build_app
from llm.base import ChatMessage, ChatModel, StructuredModel

JOB = {
    "job_title": "Field Operations Manager",
    "jd": "Own a regional network of frontline technicians and sales agents.",
    "skills_required": ["Stakeholder management", "Escalation handling"],
    "job_location_type": "onsite",
    "experience_level": "mid",
    "company_type": "mnc",
}


class FakeCastingModel(StructuredModel):
    """Deterministic stand-in for the casting call — no network, no cost."""

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        return {
            "name": "Asha Verma",
            "headline": "Field ops, several years in",
            "background": "Managed a regional technician roster through two escalations.",
            "years_experience": 5,
            "verdict_rationale": "Consistent with the archetype's stated verdict.",
            "verbal_tics": ["so", "right"],
            "sample_phrases": ["let me think about that for a second"],
            "reveals_depth_when": "asked for a specific incident",
            "always_does": ["names the specific team involved"],
            "never_does": ["blames a named individual by name"],
            "opening_line": "Hi, thanks for making time today.",
            "knowledge_map": [
                {
                    "skill": "Stakeholder management",
                    "level": 6,
                    "stance": "solid",
                    "talking_points": ["weekly sync with the regional lead"],
                    "breaking_point": "asked to reconcile two conflicting stakeholder asks",
                    "wrong_beliefs": [],
                },
                {
                    "skill": "Escalation handling",
                    "level": 5,
                    "stance": "shallow",
                    "talking_points": [],
                    "breaking_point": "asked for the actual SLA breach numbers",
                    "wrong_beliefs": [],
                },
            ],
            "resume_claims": [
                {
                    "claim": "Cut escalation backlog by half in one quarter",
                    "truthfulness": "true",
                    "probe_that_exposes_it": "ask for the before/after numbers",
                }
            ],
            "must_discover": [],
        }


class FakeChatModel(ChatModel):
    """Replies with a fixed, distinguishable line and records nothing else."""

    def __init__(self, reply: str = "Right, so — that happened during the March rollout.") -> None:
        super().__init__("fake-chat-1", 0.8)
        self._reply = reply

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_text(self, *, system: str, messages: list[ChatMessage]) -> str:
        return self._reply


@pytest.fixture
def client(tmp_path):
    app = build_app(str(tmp_path / "test.db"))
    app.dependency_overrides[get_candidate_agent] = lambda: VirtualCandidateAgent(
        model=FakeCastingModel("fake-1", 0.35)
    )
    app.dependency_overrides[get_session_agent] = lambda: CandidateSessionAgent(FakeChatModel())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def interview_id(client):
    res = client.post("/api/v1/interviews", json=JOB)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _enroll(client, interview_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [spec]},
    )
    assert res.status_code == 201, res.text
    return res.json()[0]


def _run_session(client, interview_id: str, archetype: str, manager_lines: list[str]) -> str:
    """Start a session against `archetype` and play `manager_lines`, in order."""
    created = client.post(
        "/api/v1/sessions",
        json={"interview_id": interview_id, "archetype": archetype, "planned_minutes": 30},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    for line in manager_lines:
        turn = client.post(f"/api/v1/sessions/{session_id}/turns", json={"text": line})
        assert turn.status_code == 201, turn.text
        assert turn.json()["speaker"] == "candidate"
    return session_id


# ---------------------------------------------------------------------------
# The persona matrix — every bias trap plus none, across distinct
# competence/honesty/communication combinations so the cases are also
# distinguishable from each other, not just from the trap.
# ---------------------------------------------------------------------------

PERSONA_MATRIX: dict[str, dict[str, Any]] = {
    "no_trap-strong-transparent": {
        "label": "Strong, transparent, no bias trap",
        "verdict": "select",
        "competence": "expert",
        "conscientiousness": "diligent",
        "communication": "direct",
        "emotional_stance": "composed",
        "honesty": "transparent",
        "bias_trap": None,
        "affect": "cooperative",
        "verbal_style": "over_formal",
        "language": "native_fluent",
        "comprehension": "sharp_listener",
        "motivation": "passion_hire",
        "negotiation_stance": "anchors_high",
        "environment": "clean_professional_setup",
        "compliance_traps": [],
        "protected_info_type": None,
    },
    "career_gap-weak-bluffing": {
        "label": "Weak, bluffs under pressure, volunteers a career gap",
        "verdict": "reject",
        "competence": "weak",
        "conscientiousness": "low_effort",
        "communication": "guarded",
        "emotional_stance": "nervous",
        "honesty": "bluffing",
        "bias_trap": "career_gap",
        "affect": "anxious",
        "verbal_style": "rambling",
        "language": "hinglish_code_switcher",
        "comprehension": "frequent_clarifier",
        "motivation": "family_pressured",
        "negotiation_stance": "lowballs_self",
        "environment": "spotty_home_network",
        "compliance_traps": ["volunteers_protected_info"],
        "protected_info_type": "marital_status",
    },
    "age_or_re_entry-developing-embellishing": {
        "label": "Developing, embellishes, re-entering after a career switch",
        "verdict": "borderline",
        "competence": "developing",
        "conscientiousness": "adequate",
        "communication": "formal",
        "emotional_stance": "disengaged",
        "honesty": "embellishing",
        "bias_trap": "age_or_re_entry",
        "affect": "apathetic",
        "verbal_style": "tangential",
        "language": "confident_non_native",
        "comprehension": "average_listener",
        "motivation": "counter_offer_risk",
        "negotiation_stance": "demands_off_band",
        "environment": "mobile_commuting",
        "compliance_traps": [],
        "protected_info_type": None,
    },
    "regional_or_accent-solid-transparent": {
        "label": "Solid, transparent, regional accent",
        "verdict": "select",
        "competence": "solid",
        "conscientiousness": "diligent",
        "communication": "expressive",
        "emotional_stance": "composed",
        "honesty": "transparent",
        "bias_trap": "regional_or_accent",
        "affect": "over_eager",
        "verbal_style": "jargon_flooder",
        "language": "hinglish_code_switcher",
        "comprehension": "sharp_listener",
        "motivation": "not_really_looking",
        "negotiation_stance": "offer_shopping",
        "environment": "clean_professional_setup",
        "compliance_traps": [],
        "protected_info_type": None,
    },
    "caregiving-guarded-defensive": {
        "label": "Guarded and defensive, caregiving responsibilities",
        "verdict": "borderline",
        "competence": "developing",
        "conscientiousness": "adequate",
        "communication": "guarded",
        "emotional_stance": "defensive",
        "honesty": "embellishing",
        "bias_trap": "caregiving",
        "affect": "defensive",
        "verbal_style": "monosyllabic",
        "language": "developing_esl",
        "comprehension": "misreads_questions",
        "motivation": "location_blocked",
        "negotiation_stance": "refuses_to_disclose_ctc",
        "environment": "habitual_latecomer",
        "compliance_traps": ["requests_off_policy_favour"],
        "protected_info_type": None,
    },
}

COMMON_TAXONOMY_FIELDS = {
    "seniority": "mid",
    "function": "operations",
    "region": "MH",
    "gender_presentation": "woman",
    "age_band": "35-44",
    "notice_period": "30_days",
}


def _spec(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": case["label"],
        "verdict": case["verdict"],
        "competence": case["competence"],
        "conscientiousness": case["conscientiousness"],
        "communication": case["communication"],
        "emotional_stance": case["emotional_stance"],
        "honesty": case["honesty"],
        "bias_trap": case["bias_trap"],
        "affect": case["affect"],
        "verbal_style": case["verbal_style"],
        "language": case["language"],
        "comprehension": case["comprehension"],
        "motivation": case["motivation"],
        "negotiation_stance": case["negotiation_stance"],
        "environment": case["environment"],
        "compliance_traps": case["compliance_traps"],
        "protected_info_type": case["protected_info_type"],
        **COMMON_TAXONOMY_FIELDS,
    }


MANAGER_SCRIPT = [
    "Walk me through a time you handled an escalation end to end.",
    "What would you do differently if it happened again?",
    "How do you keep stakeholders aligned when priorities conflict?",
]


@pytest.mark.parametrize("case_key", list(PERSONA_MATRIX))
def test_full_flow_for_every_persona_in_the_matrix(client, interview_id, case_key):
    """Cast -> report -> interview -> end -> transcript -> report, per persona."""
    case = PERSONA_MATRIX[case_key]
    candidate = _enroll(client, interview_id, _spec(case))
    archetype = candidate["archetype"]
    assert archetype.startswith("dyn-")
    assert candidate["verdict"] == case["verdict"]
    assert candidate["human_traits"]["affect"] == case["affect"]

    # --- the report, before any session is run ---
    report = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard")
    assert report.status_code == 200
    scorecard = report.json()
    assert scorecard["expected_verdict"] == case["verdict"]
    assert case["verdict"] in scorecard["pass_condition"]
    ids = {item["id"] for item in scorecard["must_discover"]}
    assert {"depth_vs_effort", "claim_verification", "tone_and_composure"} <= ids
    if case["bias_trap"]:
        assert "bias_free_handling" in ids
        trap_item = next(i for i in scorecard["must_discover"] if i["id"] == "bias_free_handling")
        assert trap_item["signal"] == td.BIAS_TRAP[case["bias_trap"]]["signal"]
        assert trap_item["weight"] == pytest.approx(0.25)
        # the trap's own failure mode text must be present verbatim
        expected_failure_mode = td.BIAS_TRAP[case["bias_trap"]]["failure_mode"]
        assert expected_failure_mode in scorecard["interviewer_failure_modes"]
    else:
        assert "structured_probing" in ids
        assert "bias_free_handling" not in ids

    # --- run the practice interview itself ---
    session_id = _run_session(client, interview_id, archetype, MANAGER_SCRIPT)
    ended = client.post(f"/api/v1/sessions/{session_id}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "completed"

    transcript = client.get(f"/api/v1/sessions/{session_id}").json()
    speakers = [t["speaker"] for t in transcript["turns"]]
    # opener + (manager, candidate) x 3
    assert speakers == [
        "candidate",
        "manager",
        "candidate",
        "manager",
        "candidate",
        "manager",
        "candidate",
    ]
    assert [t["text"] for t in transcript["turns"] if t["speaker"] == "manager"] == MANAGER_SCRIPT

    # --- the report afterwards must be exactly what it was before: it is a
    # pre-computed answer key, not something the session mutates ---
    report_after = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard").json()
    assert report_after == scorecard


def test_a_persona_never_engaged_still_has_a_readable_report(client, interview_id):
    """A manager can pull the report before ever opening a practice session."""
    case = PERSONA_MATRIX["no_trap-strong-transparent"]
    candidate = _enroll(client, interview_id, _spec(case))
    report = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard")
    assert report.status_code == 200
    assert report.json()["expected_verdict"] == "select"


def test_ending_a_session_with_no_manager_turns_still_yields_a_report(client, interview_id):
    """The manager opens the session, reads the opener, and quits immediately."""
    case = PERSONA_MATRIX["career_gap-weak-bluffing"]
    candidate = _enroll(client, interview_id, _spec(case))
    session_id = _run_session(client, interview_id, candidate["archetype"], manager_lines=[])
    ended = client.post(f"/api/v1/sessions/{session_id}/end")
    assert ended.status_code == 200

    report = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard")
    assert report.status_code == 200
    assert report.json()["expected_verdict"] == "reject"


def test_scorecard_for_an_unknown_candidate_is_404(client):
    assert client.get("/api/v1/candidates/nope/scorecard").status_code == 404


def test_two_personas_in_one_interview_get_independent_sessions_and_reports(client, interview_id):
    """A manager practises against two personas back to back; nothing leaks."""
    strong = _enroll(client, interview_id, _spec(PERSONA_MATRIX["no_trap-strong-transparent"]))
    weak = _enroll(client, interview_id, _spec(PERSONA_MATRIX["career_gap-weak-bluffing"]))
    assert strong["candidate_id"] != weak["candidate_id"]
    assert strong["archetype"] != weak["archetype"]

    session_strong = _run_session(client, interview_id, strong["archetype"], MANAGER_SCRIPT[:1])
    session_weak = _run_session(client, interview_id, weak["archetype"], MANAGER_SCRIPT[:2])
    client.post(f"/api/v1/sessions/{session_strong}/end")
    client.post(f"/api/v1/sessions/{session_weak}/end")

    t_strong = client.get(f"/api/v1/sessions/{session_strong}").json()
    t_weak = client.get(f"/api/v1/sessions/{session_weak}").json()
    assert len(t_strong["turns"]) == 3  # opener + 1 exchange
    assert len(t_weak["turns"]) == 5  # opener + 2 exchanges

    report_strong = client.get(f"/api/v1/candidates/{strong['candidate_id']}/scorecard").json()
    report_weak = client.get(f"/api/v1/candidates/{weak['candidate_id']}/scorecard").json()
    assert report_strong["expected_verdict"] == "select"
    assert report_weak["expected_verdict"] == "reject"

    rows = client.get(f"/api/v1/interviews/{interview_id}/sessions").json()
    assert {r["id"] for r in rows} == {session_strong, session_weak}
    row_by_id = {r["id"]: r for r in rows}
    assert row_by_id[session_strong]["turn_count"] == 3
    assert row_by_id[session_weak]["turn_count"] == 5


def test_recasting_the_same_spec_reuses_the_candidate_and_report(client, interview_id):
    case = PERSONA_MATRIX["regional_or_accent-solid-transparent"]
    first = _enroll(client, interview_id, _spec(case))
    second = _enroll(client, interview_id, _spec(case))
    assert first["candidate_id"] == second["candidate_id"]

    report_a = client.get(f"/api/v1/candidates/{first['candidate_id']}/scorecard").json()
    report_b = client.get(f"/api/v1/candidates/{second['candidate_id']}/scorecard").json()
    assert report_a == report_b


def test_a_hand_written_catalog_archetype_follows_the_same_lifecycle(client, interview_id):
    """Custom-composed and hand-written personas share one lifecycle end to end."""
    fixed_key = next(iter(archetype_catalog.ARCHETYPES))
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates", json={"archetypes": [fixed_key]}
    )
    assert res.status_code == 201, res.text
    candidate = res.json()[0]
    assert candidate["archetype"] == fixed_key

    session_id = _run_session(client, interview_id, fixed_key, MANAGER_SCRIPT[:1])
    client.post(f"/api/v1/sessions/{session_id}/end")

    report = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard")
    assert report.status_code == 200
    expected = archetype_catalog.ARCHETYPES[fixed_key]
    assert report.json()["expected_verdict"] == expected.verdict


def test_a_manager_can_read_the_transcript_mid_session_before_ending_it(client, interview_id):
    """The UI polls the live transcript; it must not require ending the session."""
    case = PERSONA_MATRIX["caregiving-guarded-defensive"]
    candidate = _enroll(client, interview_id, _spec(case))
    created = client.post(
        "/api/v1/sessions",
        json={"interview_id": interview_id, "archetype": candidate["archetype"]},
    )
    session_id = created.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/turns", json={"text": MANAGER_SCRIPT[0]})

    mid = client.get(f"/api/v1/sessions/{session_id}")
    assert mid.status_code == 200
    body = mid.json()
    assert body["status"] == "live"
    assert len(body["turns"]) == 3  # opener, manager, candidate reply

    # The report is already fully readable mid-session too.
    report = client.get(f"/api/v1/candidates/{candidate['candidate_id']}/scorecard")
    assert report.status_code == 200
