"""Storage ports.

Interface segregation: three narrow protocols instead of one repository
interface every consumer has to depend on wholesale. A handler that only reads
candidates depends on :class:`CandidateStore` and is unaffected by changes to
expectation storage.

Dependency inversion: handlers are typed against these protocols, so
``InterviewRepository`` (SQLite) can be replaced by a Postgres implementation
without touching a single route.

These are :class:`~typing.Protocol` classes — structural, so an implementation
does not import or subclass anything here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from candidate_agent.schema import VirtualCandidate
from control_plane.schemas import InterviewCreateRequest, InterviewResponse
from expectation_agent.schema import InterviewExpectation


@runtime_checkable
class InterviewStore(Protocol):
    """Persistence for interview job specs."""

    def create(self, req: InterviewCreateRequest) -> InterviewResponse:
        """Persist a new interview and return the stored record."""
        ...

    def get(self, interview_id: str) -> InterviewResponse | None:
        """Return one interview, or None when it does not exist."""
        ...

    def list(self, status: str | None = None) -> list[InterviewResponse]:
        """Return interviews, newest first, optionally filtered by status."""
        ...


@runtime_checkable
class ExpectationStore(Protocol):
    """Persistence for interviewer expectation documents."""

    def save_expectation(self, expectation: InterviewExpectation, model_used: str) -> None:
        """Upsert the expectation for an interview."""
        ...

    def get_expectation(self, interview_id: str) -> InterviewExpectation | None:
        """Return the stored expectation, or None when not generated yet."""
        ...


@runtime_checkable
class CandidateStore(Protocol):
    """Persistence for virtual candidate personas."""

    def save_candidate(self, candidate: VirtualCandidate, model_used: str) -> None:
        """Upsert a persona, keyed by (interview, archetype)."""
        ...

    def list_candidates(self, interview_id: str) -> list[VirtualCandidate]:
        """Return every persona enrolled for an interview."""
        ...

    def get_candidate(self, candidate_id: str) -> VirtualCandidate | None:
        """Return one persona, or None when it does not exist."""
        ...

    def get_candidate_by_archetype(
        self, interview_id: str, archetype: str
    ) -> VirtualCandidate | None:
        """Return the persona cast for this archetype, if one is enrolled."""
        ...

    def delete_candidate(self, candidate_id: str) -> bool:
        """Remove a persona. True when a row was deleted."""
        ...


@runtime_checkable
class ExpectationWorkflowStore(InterviewStore, ExpectationStore, Protocol):
    """Composition for handlers that read an interview and write its expectation."""


@runtime_checkable
class EnrollmentStore(InterviewStore, ExpectationStore, CandidateStore, Protocol):
    """Composition for enrollment, which reads the interview and its expectation.

    Composed from the narrow ports rather than widened into one interface, so
    each port stays independently implementable.
    """
