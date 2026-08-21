"""Pydantic request/response schemas for the interview control-plane API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InterviewConfigInput(BaseModel):
    """Runtime configuration overrides."""

    duration_minutes: int = Field(60, gt=0, le=180)
    question_mode: str = Field("AI", pattern="^(AI|HYBRID|MANUAL)$")
    interview_mode: str = Field("STANDARD", pattern="^(STANDARD|DEEP)$")
    language: str = "en"


class InterviewCreateRequest(BaseModel):
    """POST /api/v1/interviews body.

    Creates an interview request/job spec. Candidate and interviewer are
    assigned later; this endpoint only captures the job definition.
    """

    job_title: str
    jd: str = Field(..., description="Job description / requirement text")
    skills_required: list[str] = Field(..., min_length=1)
    job_location_type: str = Field(..., pattern="^(remote|onsite|hybrid)$")
    experience_level: str = Field(..., pattern="^(junior|mid|senior)$")
    company_type: str = Field(..., pattern="^(startup|mnc)$")
    mode: str = Field("live_interview", pattern="^(live_interview|training_interviewer)$")
    config: InterviewConfigInput = Field(default_factory=InterviewConfigInput)
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PersonaAttribute(BaseModel):
    """One scored attribute of a training-mode persona."""

    name: str
    score: int
    variance: str


class CandidatePersona(BaseModel):
    """Seed-derived persona attached to a training-mode interview."""

    candidate_id: str
    name: str
    background: str
    attributes: list[PersonaAttribute]
    fingerprint: str


class InterviewResponse(BaseModel):
    """POST /api/v1/interviews response body."""

    id: str
    job_title: str
    jd: str
    skills_required: list[str]
    job_location_type: str
    experience_level: str
    company_type: str
    mode: str
    status: str
    config: InterviewConfigInput
    ai_persona: CandidatePersona | None = None
    scheduled_at: datetime | None = None
    created_at: datetime
    start_url: str
    metadata: dict[str, Any]


class CandidateEnrollRequest(BaseModel):
    """POST /api/v1/interviews/{id}/candidates body.

    Omit `archetypes` to enroll the two defaults: one candidate who should be
    selected and one who should be rejected.
    """

    archetypes: list[str] | None = Field(
        None,
        description="Archetype keys from GET /api/v1/candidate-archetypes. "
        "Defaults to ['strong_hire', 'clear_reject'].",
    )
    regenerate: bool = Field(
        False,
        description="Re-cast archetypes that are already enrolled instead of skipping them.",
    )
    seed_prefix: str | None = Field(
        None,
        description="Overrides the persona seed. Same prefix reproduces the same people.",
    )


class CandidateSummary(BaseModel):
    """Compact row for the enrollment list."""

    candidate_id: str
    interview_id: str
    archetype: str
    archetype_label: str
    name: str
    headline: str
    verdict: str
    smartness: int
    dumbness: int
    smartness_ratio: float
    seriousness: int
    interest: int
    effort: int
