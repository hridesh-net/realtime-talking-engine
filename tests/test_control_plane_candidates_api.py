"""Offline API tests for candidate enrollment, including custom_personas.

Uses a fake StructuredModel (no network, no cost) and a throwaway SQLite file
per test via `build_app`. Covers the path that manual smoke-testing checked
during development: GET /trait-dimensions, composing a custom persona through
POST .../candidates, idempotent re-submission, and 422 on a bad preset.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from candidate_agent import archetypes as archetype_catalog
from candidate_agent import engine_contract as ec
from candidate_agent.agent import VirtualCandidateAgent
from control_plane.api import get_candidate_agent
from control_plane.main import build_app
from llm.base import StructuredModel

JOB = {
    "job_title": "Network Technician",
    "jd": "Install and maintain fiber networks.",
    "skills_required": ["Fiber splicing"],
    "job_location_type": "onsite",
    "experience_level": "junior",
    "company_type": "mnc",
}

VALID_CUSTOM_PERSONA: dict[str, Any] = {
    "label": "Custom guarded network tech",
    "verdict": "borderline",
    "competence": "developing",
    "conscientiousness": "adequate",
    "communication": "guarded",
    "emotional_stance": "defensive",
    "honesty": "embellishing",
    "bias_trap": "regional_or_accent",
    "affect": "defensive",
    "verbal_style": "monosyllabic",
    "language": "hinglish_code_switcher",
    "comprehension": "frequent_clarifier",
    "motivation": "family_pressured",
    "negotiation_stance": "refuses_to_disclose_ctc",
    "environment": "spotty_home_network",
    "seniority": "junior",
    "function": "network",
    "region": "UP",
    "gender_presentation": "woman",
    "age_band": "25-34",
    "notice_period": "30_days",
    "compliance_traps": ["volunteers_protected_info"],
    "protected_info_type": "marital_status",
}


class FakeModel(StructuredModel):
    """Deterministic stand-in for the candidate agent's model call."""

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        return {
            "name": "Test Person",
            "headline": "A candidate",
            "background": "bg",
            "years_experience": 4,
            "verdict_rationale": "rationale",
            "verbal_tics": ["uh"],
            "sample_phrases": ["well, yeah"],
            "reveals_depth_when": "pushed",
            "always_does": ["nods"],
            "never_does": ["brags"],
            "opening_line": "Hi there.",
            "knowledge_map": [
                {
                    "skill": "Fiber splicing",
                    "level": 5,
                    "stance": "solid",
                    "talking_points": [],
                    "breaking_point": "deep theory",
                    "wrong_beliefs": [],
                }
            ],
            "resume_claims": [
                {
                    "claim": "Did X",
                    "truthfulness": "true",
                    "probe_that_exposes_it": "ask for detail",
                }
            ],
            "must_discover": [],
        }


@pytest.fixture
def client(tmp_path):
    app = build_app(str(tmp_path / "test.db"))
    app.dependency_overrides[get_candidate_agent] = lambda: VirtualCandidateAgent(
        model=FakeModel("fake-1", 0.35)
    )
    return TestClient(app)


@pytest.fixture
def interview_id(client):
    res = client.post("/api/v1/interviews", json=JOB)
    assert res.status_code == 201
    return res.json()["id"]


def test_trait_dimensions_endpoint_lists_every_dimension(client):
    res = client.get("/api/v1/trait-dimensions")
    assert res.status_code == 200
    body = res.json()
    for key in ("affect", "verbal_style", "language", "comprehension", "environment"):
        assert key in body and len(body[key]) > 0


def test_enroll_custom_persona_end_to_end(client, interview_id):
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [VALID_CUSTOM_PERSONA]},
    )
    assert res.status_code == 201
    (candidate,) = res.json()

    assert candidate["archetype"].startswith("dyn-")
    assert candidate["verdict"] == "borderline"
    assert candidate["human_traits"] is not None
    assert candidate["human_traits"]["affect"] == "defensive"
    assert "HOW YOU COME ACROSS" in candidate["engine_contract"]["system_prompt"]
    # The compliance trap must actually reach the compiled prompt, not just the schema.
    prompt = candidate["engine_contract"]["system_prompt"]
    assert (
        ec.COMPLIANCE_TRAP_DIRECTIVES["volunteers_protected_info"].format(
            protected_info_type="marital_status"
        )
        in prompt
    )


def test_resubmitting_the_same_spec_reuses_the_candidate(client, interview_id):
    first = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [VALID_CUSTOM_PERSONA]},
    ).json()[0]
    second = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [VALID_CUSTOM_PERSONA]},
    ).json()[0]
    assert first["candidate_id"] == second["candidate_id"]


def test_custom_persona_with_unknown_preset_returns_422(client, interview_id):
    bad = dict(VALID_CUSTOM_PERSONA, competence="not-a-real-preset")
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [bad]},
    )
    assert res.status_code == 422


def test_custom_persona_missing_protected_info_type_returns_422(client, interview_id):
    bad = dict(VALID_CUSTOM_PERSONA, protected_info_type=None)
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [bad]},
    )
    assert res.status_code == 422


def test_custom_persona_with_no_compliance_trap_and_empty_protected_info_type_succeeds(
    client, interview_id
):
    """Regression test for the UI's actual default form state.

    No compliance trap checked, protected_info_type left at "". Must
    succeed, not 422.
    """
    spec = dict(VALID_CUSTOM_PERSONA, compliance_traps=[], protected_info_type="")
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [spec]},
    )
    assert res.status_code == 201, res.text


def test_archetypes_and_custom_personas_can_be_mixed_in_one_call(client, interview_id):
    fixed_key = next(iter(archetype_catalog.ARCHETYPES))
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"archetypes": [fixed_key], "custom_personas": [VALID_CUSTOM_PERSONA]},
    )
    assert res.status_code == 201
    assert len(res.json()) == 2


def test_no_body_still_enrolls_the_two_defaults(client, interview_id):
    res = client.post(f"/api/v1/interviews/{interview_id}/candidates")
    assert res.status_code == 201
    keys = {c["archetype"] for c in res.json()}
    assert keys == set(archetype_catalog.default_keys())


def test_a_custom_persona_survives_a_process_restart(tmp_path):
    """Regression: composed personas used to die on the next deploy.

    The archetype lived only in the process-wide `ARCHETYPES` dict, and
    `POST /sessions` checked that dict before looking in the database — so an
    enrolled persona stayed visible in the candidate list while every attempt
    to start a session against it returned 422 "unknown archetype".
    """
    db = str(tmp_path / "restart.db")

    def fresh_client():
        app = build_app(db)
        app.dependency_overrides[get_candidate_agent] = lambda: VirtualCandidateAgent(
            model=FakeModel("fake-1", 0.35)
        )
        return TestClient(app)

    first = fresh_client()
    interview_id = first.post("/api/v1/interviews", json=JOB).json()["id"]
    enrolled = first.post(
        f"/api/v1/interviews/{interview_id}/candidates",
        json={"custom_personas": [VALID_CUSTOM_PERSONA]},
    )
    assert enrolled.status_code == 201
    key = enrolled.json()[0]["archetype"]
    assert key.startswith("dyn-")

    # Composing must not have grown the catalog, in this process or any other.
    assert key not in archetype_catalog.ARCHETYPES
    assert key not in {
        a["key"] for a in first.get("/api/v1/candidate-archetypes").json()["archetypes"]
    }

    # A second process: same database, empty in-memory catalog.
    second = fresh_client()
    assert [
        c["archetype"] for c in second.get(f"/api/v1/interviews/{interview_id}/candidates").json()
    ] == [key]

    started = second.post("/api/v1/sessions", json={"interview_id": interview_id, "archetype": key})
    assert started.status_code == 201, started.text

    # A key that was never enrolled is still rejected.
    missing = second.post(
        "/api/v1/sessions", json={"interview_id": interview_id, "archetype": "dyn-000000000000"}
    )
    assert missing.status_code == 422
