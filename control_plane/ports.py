"""Storage ports.

Interface segregation: narrow protocols instead of one repository interface
every consumer has to depend on wholesale. A handler that only reads candidates
depends on :class:`CandidateStore` and is unaffected by changes to link storage.

Dependency inversion: handlers are typed against these protocols, so
``InterviewRepository`` (SQLite) can be replaced by a Postgres implementation
without touching a single route.

These are :class:`~typing.Protocol` classes — structural, so an implementation
does not import or subclass anything here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from candidate_agent.schema import VirtualCandidate
from control_plane.schemas import (
    AnalysisMeta,
    IngestReceipt,
    InterviewCreateRequest,
    InterviewLinkResponse,
    InterviewResponse,
    InterviewUpdateRequest,
    ParticipantResponse,
    ParticipantSessionRow,
    RecordingMeta,
    ReportMeta,
    SessionIngest,
    SessionResponse,
    SessionSummary,
    Turn,
)


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
class InterviewEditor(Protocol):
    """Partial edit of a stored interview.

    Separate from :class:`InterviewStore` rather than a fourth method on it,
    because the two have different blast radii: everything that reads a job
    spec depends on `InterviewStore`, and none of it should acquire the ability
    to rewrite one. The wizard's step 2 is the only caller, and it needs
    exactly this.
    """

    def update(self, interview_id: str, req: InterviewUpdateRequest) -> InterviewResponse | None:
        """Apply the fields present on `req`, or None when the interview is unknown."""
        ...


@runtime_checkable
class LinkStore(Protocol):
    """Persistence for the expiring links an interview is taken through.

    Expiry is **not** enforced here. A link's row is returned whatever its
    `expires_at` says, because the two callers need to tell the three cases
    apart — unknown (404), expired or revoked (410), live — and a store that
    silently returned None for the last two would collapse them into the first.
    """

    def create_link(self, interview_id: str, expires_at: datetime) -> InterviewLinkResponse:
        """Mint a link for an interview. Several per interview are allowed."""
        ...

    def get_link(self, token: str) -> InterviewLinkResponse | None:
        """Return one link whatever its state, or None when the token is unknown."""
        ...

    def revoke_link(self, token: str) -> bool:
        """Mark a link revoked. True when a live link was revoked."""
        ...


@runtime_checkable
class ParticipantStore(Protocol):
    """Persistence for the people who take interviews, keyed by email.

    An identity join key, not a user table — see the `participants` DDL. The
    upsert is the only way a row is ever created: there is no signup here.
    """

    def upsert_participant(
        self, *, name: str, email: str, user_id: str | None = None
    ) -> ParticipantResponse:
        """Create or refresh the row for this email, moving `last_seen_at`.

        The email is the identity, so the caller's `name` overwrites what is
        stored — the most recent form value is the current one. A `user_id`
        attaches when supplied and is never cleared by a later call that has
        none: arriving on a link once does not undo being a SkillBrew user.
        """
        ...

    def get_participant(self, participant_id: str) -> ParticipantResponse | None:
        """Return one participant, or None when the id is unknown."""
        ...

    def list_participant_sessions(self, participant_id: str) -> list[ParticipantSessionRow]:
        """Every session this person has held, across every interview, newest first."""
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
        archetype: str,
        planned_minutes: int,
        opening_line: str,
        modality: str = "text",
        participant_id: str | None = None,
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

    def open_recording(self, session_id: str) -> tuple[RecordingMeta, Path] | None:
        """Return the recording's metadata and the file holding it, or None.

        A **path**, not bytes: a recording now carries the manager's camera as
        well as the two audio channels — roughly 190 MB per session-hour — and
        neither serving it nor analysing it should pull that through the API
        process's heap. The caller streams from the path or hands it to ffmpeg.

        The file is the live spool; nothing in this service moves or prunes it
        (see the retention decision in `okf/concepts/contracts/session-recording.md`),
        so the path stays valid for as long as the recording exists. When
        recordings move to the object store this becomes a stream and the range
        handling moves with them.
        """
        ...


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


class IngestConflictError(ValueError):
    """The session id is already held by a different interview or persona."""


@runtime_checkable
class IngestStore(Protocol):
    """Persistence for the Go engine's end-of-session write-back.

    One method, deliberately: the ingest replaces the session's transcript and
    closes it in a single transaction, and it is idempotent on the session id
    because the engine retries. Turn indexes come from the engine's own turn
    table here — the engine's clock is the time base for a voice session, the
    same way :class:`SessionStore` is for a text one.
    """

    def store_ingest(
        self,
        ingest: SessionIngest,
        *,
        archetype: str,
        opening_line: str,
        planned_minutes: int,
    ) -> IngestReceipt:
        """Create or close the session, replace its turns, keep the raw payload.

        Raises :class:`IngestConflictError` when the session exists under a
        different interview or persona.
        """
        ...


@runtime_checkable
class EnrollmentStore(InterviewStore, CandidateStore, Protocol):
    """Composition for enrollment: read the interview, write the personas.

    Composed from the narrow ports rather than widened into one interface, so
    each port stays independently implementable.
    """


@runtime_checkable
class LinkSessionStore(
    InterviewStore, CandidateStore, SessionStore, LinkStore, ParticipantStore, Protocol
):
    """Everything `POST /sessions` needs, once a link may open one.

    Opening a session reads the interview, casts or reuses the persona and
    writes the session — and, on the token path, resolves the interview from
    the link while enforcing the expiry at that moment, then upserts the
    participant by email before the session row is written. It is one handler
    and therefore one port: splitting the two entry paths into two routes would
    let them drift on everything else they share.
    """


@runtime_checkable
class IngestWorkflowStore(InterviewStore, CandidateStore, IngestStore, Protocol):
    """What the ingest handler needs.

    The interview (for the session's planned length), the persona (for the
    archetype and opening line it answers for), and the ingest store itself.
    Not :class:`SessionStore` — the engine's turn table is written whole, never
    appended to.
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
    """What running an analysis needs: the brief, the session, the audio.

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

    Generating a report reads the interview (the job card and its role
    facts), the session (the transcript and the persona faced), the cast
    candidate - because a *composed* persona has no catalog entry, and its
    `must_discover` scorecard lives on the candidate rather than in code - and
    the stored analysis, which the report is built from. Then it writes the
    report. Composed from the narrow ports rather than handing the
    handler the whole repository.
    """
