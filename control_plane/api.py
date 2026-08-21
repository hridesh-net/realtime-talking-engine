"""FastAPI routes for interview creation and management."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from control_plane.database import init_db
from control_plane.repository import InterviewRepository
from control_plane.schemas import InterviewCreateRequest, InterviewResponse
from expectation_agent.agent import InterviewExpectationAgent
from expectation_agent.schema import InterviewExpectation


def get_repo() -> InterviewRepository:
    # In production this should be a connection-pool dependency.
    return InterviewRepository(init_db())


def get_expectation_agent() -> InterviewExpectationAgent:
    return InterviewExpectationAgent()


router = APIRouter(prefix="/api/v1", tags=["interviews"])


@router.post("/interviews", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
def create_interview(req: InterviewCreateRequest, repo: InterviewRepository = Depends(get_repo)):
    return repo.create(req)


@router.get("/interviews/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: str, repo: InterviewRepository = Depends(get_repo)):
    interview = repo.get(interview_id)
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")
    return interview


@router.get("/interviews", response_model=List[InterviewResponse])
def list_interviews(status: str | None = None, repo: InterviewRepository = Depends(get_repo)):
    return repo.list(status=status)


@router.post(
    "/interviews/{interview_id}/expectation",
    response_model=InterviewExpectation,
    status_code=status.HTTP_201_CREATED,
)
async def generate_expectation(
    interview_id: str,
    repo: InterviewRepository = Depends(get_repo),
    agent: InterviewExpectationAgent = Depends(get_expectation_agent),
):
    """Generate and persist the interviewer expectation document."""
    interview = repo.get(interview_id)
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")

    expectation = await agent.generate(
        interview_id=interview.id,
        job_title=interview.job_title,
        jd=interview.jd,
        skills_required=interview.skills_required,
        job_location_type=interview.job_location_type,
        experience_level=interview.experience_level,
        company_type=interview.company_type,
        duration_minutes=interview.config.duration_minutes,
        mode=interview.mode,
        has_resume=False,  # resume is attached later when candidate is assigned
    )
    repo.save_expectation(expectation, model_used=agent.model)
    return expectation


@router.get("/interviews/{interview_id}/expectation", response_model=InterviewExpectation)
def get_expectation(interview_id: str, repo: InterviewRepository = Depends(get_repo)):
    expectation = repo.get_expectation(interview_id)
    if not expectation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expectation not found")
    return expectation
