"""FastAPI routes for interview creation and management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from candidate_agent import archetypes as archetype_catalog
from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.schema import EngineContract, InterviewerScorecard, VirtualCandidate
from control_plane.database import init_db
from control_plane.ports import (
    CandidateStore,
    EnrollmentStore,
    ExpectationStore,
    ExpectationWorkflowStore,
    InterviewStore,
)
from control_plane.repository import InterviewRepository
from control_plane.schemas import (
    CandidateEnrollRequest,
    InterviewCreateRequest,
    InterviewResponse,
)
from expectation_agent.agent import InterviewExpectationAgent
from expectation_agent.schema import InterviewExpectation


def get_repo() -> InterviewRepository:
    """Build the storage adapter that satisfies every port."""
    # In production this should be a connection-pool dependency.
    return InterviewRepository(init_db())


def get_expectation_agent() -> InterviewExpectationAgent:
    """Build the expectation agent from environment configuration."""
    return InterviewExpectationAgent()


router = APIRouter(prefix="/api/v1", tags=["interviews"])


@router.post("/interviews", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
def create_interview(
    req: InterviewCreateRequest, repo: InterviewStore = Depends(get_repo)
) -> InterviewResponse:
    """Create an interview from a job spec."""
    return repo.create(req)


@router.get("/interviews/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: str, repo: InterviewStore = Depends(get_repo)) -> InterviewResponse:
    """Fetch one interview."""
    interview = repo.get(interview_id)
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")
    return interview


@router.get("/interviews", response_model=list[InterviewResponse])
def list_interviews(
    status: str | None = None, repo: InterviewStore = Depends(get_repo)
) -> list[InterviewResponse]:
    """List interviews, newest first, optionally filtered by status."""
    return repo.list(status=status)


@router.post(
    "/interviews/{interview_id}/expectation",
    response_model=InterviewExpectation,
    status_code=status.HTTP_201_CREATED,
)
async def generate_expectation(
    interview_id: str,
    repo: ExpectationWorkflowStore = Depends(get_repo),
    agent: InterviewExpectationAgent = Depends(get_expectation_agent),
) -> InterviewExpectation:
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
def get_expectation(
    interview_id: str, repo: ExpectationStore = Depends(get_repo)
) -> InterviewExpectation:
    """Fetch the stored expectation for an interview."""
    expectation = repo.get_expectation(interview_id)
    if not expectation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expectation not found")
    return expectation


# ---------------------------------------------------------------------------
# Virtual candidate enrollment
# ---------------------------------------------------------------------------


def get_candidate_agent() -> VirtualCandidateAgent:
    """Build the virtual candidate agent from environment configuration."""
    return VirtualCandidateAgent()


@router.get("/candidate-archetypes")
def list_archetypes() -> dict[str, object]:
    """The fixed persona catalog the enrollment UI offers."""
    return {
        "catalog_version": archetype_catalog.CATALOG_VERSION,
        "defaults": archetype_catalog.default_keys(),
        "archetypes": archetype_catalog.catalog(),
    }


@router.post(
    "/interviews/{interview_id}/candidates",
    response_model=list[VirtualCandidate],
    status_code=status.HTTP_201_CREATED,
)
async def enroll_candidates(
    interview_id: str,
    req: CandidateEnrollRequest | None = None,
    repo: EnrollmentStore = Depends(get_repo),
    agent: VirtualCandidateAgent = Depends(get_candidate_agent),
) -> list[VirtualCandidate]:
    """Cast virtual candidates for an interview.

    With no body this enrolls the two defaults — one who should be selected and
    one who should be rejected — both grounded in this interview's job spec.
    """
    req = req or CandidateEnrollRequest()
    interview = repo.get(interview_id)
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")

    keys = req.archetypes or archetype_catalog.default_keys()
    unknown = [k for k in keys if k not in archetype_catalog.ARCHETYPES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown archetypes: {', '.join(unknown)}",
        )

    # The expectation grounds personas in the flags the interviewer is watching
    # for. Optional — enrollment must not require it.
    expectation = repo.get_expectation(interview_id)

    results: list[VirtualCandidate] = []
    # Independent generations converge on the same names, which makes a training
    # set confusing. Feed each cast the names already taken.
    taken: list[str] = [c.name for c in repo.list_candidates(interview_id)]
    for key in keys:
        existing = repo.get_candidate_by_archetype(interview_id, key)
        if existing and not req.regenerate:
            results.append(existing)
            continue

        candidate = await agent.generate(
            interview_id=interview_id,
            archetype_key=key,
            job_title=interview.job_title,
            jd=interview.jd,
            skills_required=interview.skills_required,
            experience_level=interview.experience_level,
            company_type=interview.company_type,
            job_location_type=interview.job_location_type,
            duration_minutes=interview.config.duration_minutes,
            interview_type=(expectation.interview_type if expectation else "mixed"),
            expectation=expectation,
            seed_override=(f"{req.seed_prefix}:{key}" if req.seed_prefix else None),
            avoid_names=taken,
        )
        repo.save_candidate(candidate, model_used=agent.model)
        taken.append(candidate.name)
        results.append(candidate)

    return results


@router.get("/interviews/{interview_id}/candidates", response_model=list[VirtualCandidate])
def list_candidates(
    interview_id: str, repo: CandidateStore = Depends(get_repo)
) -> list[VirtualCandidate]:
    """List every persona enrolled for an interview."""
    return repo.list_candidates(interview_id)


@router.get("/candidates/{candidate_id}", response_model=VirtualCandidate)
def get_candidate(candidate_id: str, repo: CandidateStore = Depends(get_repo)) -> VirtualCandidate:
    """Fetch one persona."""
    candidate = repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
    return candidate


@router.get("/candidates/{candidate_id}/engine-contract", response_model=EngineContract)
def get_engine_contract(
    candidate_id: str, repo: CandidateStore = Depends(get_repo)
) -> EngineContract:
    """What the Go interview-candidate engine pulls to run this persona."""
    candidate = repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
    return candidate.engine_contract


@router.get("/candidates/{candidate_id}/scorecard", response_model=InterviewerScorecard)
def get_scorecard(
    candidate_id: str, repo: CandidateStore = Depends(get_repo)
) -> InterviewerScorecard:
    """Ground-truth answer key used to grade the interviewer after the session."""
    candidate = repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
    return candidate.interviewer_scorecard


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(candidate_id: str, repo: CandidateStore = Depends(get_repo)) -> None:
    """Remove a persona from an interview."""
    if not repo.delete_candidate(candidate_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate not found")
