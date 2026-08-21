"""Pydantic request/response schemas for the interview control-plane API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

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
    skills_required: List[str] = Field(..., min_length=1)
    job_location_type: str = Field(..., pattern="^(remote|onsite|hybrid)$")
    experience_level: str = Field(..., pattern="^(junior|mid|senior)$")
    company_type: str = Field(..., pattern="^(startup|mnc)$")
    mode: str = Field("live_interview", pattern="^(live_interview|training_interviewer)$")
    config: InterviewConfigInput = Field(default_factory=InterviewConfigInput)
    scheduled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PersonaAttribute(BaseModel):
    name: str
    score: int
    variance: str


class CandidatePersona(BaseModel):
    candidate_id: str
    name: str
    background: str
    attributes: List[PersonaAttribute]
    fingerprint: str


class InterviewResponse(BaseModel):
    """POST /api/v1/interviews response body."""

    id: str
    job_title: str
    jd: str
    skills_required: List[str]
    job_location_type: str
    experience_level: str
    company_type: str
    mode: str
    status: str
    config: InterviewConfigInput
    ai_persona: Optional[CandidatePersona] = None
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    start_url: str
    metadata: Dict[str, Any]
