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

from typing import Any, Protocol, runtime_checkable

from candidate_agent.schema import VirtualCandidate
from control_plane.schemas import (
    AnalysisMeta,
    InterviewCreateRequest,
    InterviewResponse,
    RecordingMeta,
    ReportMeta,
    SessionResponse,
    SessionSummary,
    Turn,
)
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
class SessionStore(Protocol):
    """Persistence for live interview sessions and their transcripts.

    Turn indexes and timestamps are assigned here, not by the caller: the
    transcript is the evaluation layer's evidence, so its clock and its ordering
    belong to one place that cannot be argued with.
    """

    def create_session(
        self,
        *,
        interview_id: str,
        candidate_id: str,
        persona_key: str,
        planned_minutes: int,
        opening_line: str,
        modality: str = "text",
    ) -> SessionResponse:
        """Open a session, seeding turn 0 with the persona's opening line."""
        ...

    def get_session(self, session_id: str) -> SessionResponse | None:
        """Return one session with its full transcript, or None."""
        ...

    def append_turn(self, session_id: str, speaker: str, text: str) -> Turn:
        """Append a turn, stamping its index, wall time, and elapsed offset."""
        ...

    def end_session(self, session_id: str, status: str = "completed") -> SessionResponse | None:
        """Close a session. Returns the final record, or None when unknown."""
        ...

    def list_sessions(self, interview_id: str) -> list[SessionSummary]:
        """Every session held against one interview, newest first, no transcripts."""
        ...


@runtime_checkable
class RecordingStore(Protocol):
    """Persistence for a session's audio artifact.

    Chunk ordering is enforced here, not by the caller -- same reason turn
    indexes are.
    """

    def append_recording_chunk(
        self, session_id: str, seq: int, mime_type: str, data: bytes
    ) -> RecordingMeta:
        """Append one chunk. `seq` must equal the recording's next expected seq."""
        ...

    def finalize_recording(self, session_id: str) -> RecordingMeta | None:
        """Mark the recording complete. Idempotent; None when there is none."""
        ...

    def get_recording_meta(self, session_id: str) -> RecordingMeta | None:
        """Return the recording's metadata, or None when it does not exist."""
        ...

    def read_recording(self, session_id: str) -> tuple[RecordingMeta, bytes] | None:
        """Return the recording's metadata and its bytes, or None."""
        ...


@runtime_checkable
@runtime_checkable
class AnalysisStore(Protocol):
    """Persistence for one session's audio analysis."""

    def begin_analysis(self, session_id: str) -> AnalysisMeta:
        """Mark analysis as running, replacing any previous attempt."""
        ...

    def complete_analysis(self, session_id: str, analysis: dict[str, Any]) -> AnalysisMeta:
        """Store a finished analysis."""
        ...

    def fail_analysis(self, session_id: str, error: str) -> AnalysisMeta:
        """Record that analysis failed, and why."""
        ...

    def get_analysis(self, session_id: str) -> dict[str, Any] | None:
        """The stored analysis body, or None when there is none."""
        ...

    def get_analysis_meta(self, session_id: str) -> AnalysisMeta | None:
        """State and provenance without the body."""
        ...


@runtime_checkable
class ReportStore(Protocol):
    """Persistence for one session's generated report."""

    def save_report(self, session_id: str, report: dict[str, Any]) -> ReportMeta:
        """Store or replace this session's report. Returns its metadata."""
        ...

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        """The stored report body, or None when none has been generated."""
        ...

    def get_report_meta(self, session_id: str) -> ReportMeta | None:
        """The stored report's headline and provenance, without its body."""
        ...


class ExpectationWorkflowStore(InterviewStore, ExpectationStore, Protocol):
    """Composition for handlers that read an interview and write its expectation."""


@runtime_checkable
class EnrollmentStore(InterviewStore, ExpectationStore, CandidateStore, Protocol):
    """Composition for enrollment, which reads the interview and its expectation.

    Composed from the narrow ports rather than widened into one interface, so
    each port stays independently implementable.
    """


@runtime_checkable
class SessionWorkflowStore(
    InterviewStore, ExpectationStore, CandidateStore, SessionStore, Protocol
):
    """Composition for opening a session.

    Reads the interview, casts or reuses the persona, then opens the session
    against it. Carries :class:`ExpectationStore` for the same reason
    :class:`EnrollmentStore` does: a persona cast here is grounded in the
    interview's expectation document, so this handler casts the same persona
    enrollment would rather than a weaker one.
    """


@runtime_checkable
class TurnWorkflowStore(CandidateStore, SessionStore, Protocol):
    """Composition for running a turn: read the persona's contract, write turns.

    Deliberately excludes :class:`InterviewStore` — the busiest endpoint in the
    system has no business depending on job-spec storage.
    """


@runtime_checkable
class RecordingWorkflowStore(SessionStore, RecordingStore, Protocol):
    """For the chunk handler, which must check the session's modality first."""


class AnalysisWorkflowStore(
    InterviewStore, CandidateStore, SessionStore, AnalysisStore, RecordingStore, Protocol
):
    """What running an analysis needs: the expectation, the session, the audio.

    It reads the interview and the cast candidate to build the brief, the
    session for the persona faced, the recording for the audio itself, and
    writes the analysis. It does **not** get the report store: analysis and
    report generation are separate actions, and a handler that can do both is a
    handler that will eventually do both by accident.
    """


class ReportWorkflowStore(
    InterviewStore, CandidateStore, SessionStore, AnalysisStore, ReportStore, Protocol
):
    """The ports report generation needs, and no more.

    Generating a report reads the interview (the job card and its clarity
    facts), the session (the transcript and the persona faced), the cast
    candidate - because a *composed* persona has no catalog entry, and its
    `must_discover` scorecard lives on the candidate rather than in code - and
    the stored analysis, which the report is built from. Then it writes the
    report. Composed from the narrow ports rather than handing the
    handler the whole repository.
    """
