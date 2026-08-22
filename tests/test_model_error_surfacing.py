"""A provider failure (rate limit, quota, outage) must surface as a clean 502.

Found live: composing a custom persona against the real Gemini free-tier quota
(20 requests/day) produced a raw, unhandled 500 with a stack trace — the three
endpoints that call an LLM to cast a persona or generate an expectation never
caught `ModelError`, unlike the realtime-voice mint endpoint two hundred lines
away, which already has this exact pattern ("A mint failure is the vendor's
answer, not a bug in this service"). These tests lock in the fix.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candidate_agent.agent import VirtualCandidateAgent
from control_plane.api import get_candidate_agent, get_expectation_agent
from control_plane.main import build_app
from expectation_agent.agent import InterviewExpectationAgent
from llm.base import ModelError, StructuredModel

JOB = {
    "job_title": "Network Technician",
    "jd": "Install and maintain fiber networks.",
    "skills_required": ["Fiber splicing"],
    "job_location_type": "onsite",
    "experience_level": "junior",
    "company_type": "mnc",
}


class FailingModel(StructuredModel):
    """Stands in for a provider that is rate-limited, quota-exhausted, or down."""

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        raise ModelError("429 RESOURCE_EXHAUSTED: quota exceeded, retry in 27s")


@pytest.fixture
def client(tmp_path):
    app = build_app(str(tmp_path / "test.db"))
    app.dependency_overrides[get_candidate_agent] = lambda: VirtualCandidateAgent(
        model=FailingModel("fake-1", 0.35)
    )
    app.dependency_overrides[get_expectation_agent] = lambda: InterviewExpectationAgent(
        model=FailingModel("fake-1", 0.2)
    )
    return TestClient(app)


@pytest.fixture
def interview_id(client):
    res = client.post("/api/v1/interviews", json=JOB)
    assert res.status_code == 201
    return res.json()["id"]


def test_enrolling_a_candidate_surfaces_a_provider_failure_as_502(client, interview_id):
    res = client.post(f"/api/v1/interviews/{interview_id}/candidates")
    assert res.status_code == 502, res.text
    assert "RESOURCE_EXHAUSTED" in res.json()["detail"]


def test_enrolling_a_custom_persona_surfaces_a_provider_failure_as_502(client, interview_id):
    spec = {
        "label": "Provider-failure check",
        "verdict": "borderline",
        "competence": "developing",
        "conscientiousness": "adequate",
        "communication": "guarded",
        "emotional_stance": "defensive",
        "honesty": "embellishing",
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
    }
    res = client.post(
        f"/api/v1/interviews/{interview_id}/candidates", json={"custom_personas": [spec]}
    )
    assert res.status_code == 502, res.text
    assert "RESOURCE_EXHAUSTED" in res.json()["detail"]


def test_starting_a_session_surfaces_a_provider_failure_as_502(client, interview_id):
    res = client.post(
        "/api/v1/sessions",
        json={"interview_id": interview_id, "archetype": "cooperative_trap"},
    )
    assert res.status_code == 502, res.text
    assert "RESOURCE_EXHAUSTED" in res.json()["detail"]


def test_generating_the_expectation_document_surfaces_a_provider_failure_as_502(
    client, interview_id
):
    res = client.post(f"/api/v1/interviews/{interview_id}/expectation")
    assert res.status_code == 502, res.text
    assert "RESOURCE_EXHAUSTED" in res.json()["detail"]
