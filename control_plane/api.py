"""FastAPI routes for interview creation and management."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from analysis_agent import AnalysisContext, AudioAnalysisAgent
from candidate_agent import archetypes as archetype_catalog
from candidate_agent import trait_dimensions
from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.archetypes import Archetype
from candidate_agent.engine_contract import GEMINI_TTS_VOICES
from candidate_agent.schema import (
    EngineContract,
    HumanTraitProfile,
    InterviewerScorecard,
    VirtualCandidate,
)
from candidate_agent.session import CANDIDATE, MANAGER, CandidateSessionAgent
from candidate_agent.voice import build_realtime_session
from control_plane import reporting
from control_plane.database import init_db
from control_plane.ports import (
    AnalysisWorkflowStore,
    CandidateStore,
    EnrollmentStore,
    ExpectationStore,
    ExpectationWorkflowStore,
    InterviewStore,
    RecordingStore,
    RecordingWorkflowStore,
    ReportWorkflowStore,
    SessionStore,
    SessionWorkflowStore,
    TurnWorkflowStore,
)
from control_plane.repository import InterviewRepository
from control_plane.schemas import (
    AnalysisMeta,
    CandidateEnrollRequest,
    ClarityFact,
    CustomPersonaSpec,
    InterviewCreateRequest,
    InterviewResponse,
    RealtimeCredentialResponse,
    RecordingMeta,
    RoleFactsRequest,
    SessionCreateRequest,
    SessionResponse,
    SessionSummary,
    TranscriptAppendRequest,
    Turn,
    TurnRequest,
    VoiceCapabilityResponse,
)
from evaluation_agent.role_facts import RoleFactsAgent
from expectation_agent.agent import InterviewExpectationAgent
from expectation_agent.schema import InterviewExpectation
from llm.base import ModelError, RealtimeBroker
from llm.factory import build_audio_model, build_realtime_broker, realtime_providers_available
from report_engine import render
from report_engine.schema import AssessmentReport


def get_repo() -> InterviewRepository:
    """Build the storage adapter that satisfies every port."""
    # In production this should be a connection-pool dependency.
    return InterviewRepository(init_db())


def get_expectation_agent() -> InterviewExpectationAgent:
    """Build the expectation agent from environment configuration."""
    return InterviewExpectationAgent()


#: Observation is extraction, not composition. Warmth here invents turns.
ANALYSIS_TEMPERATURE = 0.0

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

    try:
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
    except ModelError as exc:
        # A generation failure is the provider's answer, not a bug in this
        # service — surface it as a gateway error so the UI can say so plainly.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
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


def get_role_facts_agent() -> RoleFactsAgent:
    """Build the role-facts agent from environment configuration."""
    return RoleFactsAgent()


def get_analysis_agent() -> AudioAnalysisAgent:
    """Build the audio analysis agent from environment configuration."""
    return AudioAnalysisAgent(build_audio_model("analysis", ANALYSIS_TEMPERATURE))


@router.post("/role-facts", response_model=list[ClarityFact])
async def draft_role_facts(
    req: RoleFactsRequest,
    agent: RoleFactsAgent = Depends(get_role_facts_agent),
) -> list[ClarityFact]:
    """Draft the role-fact checklist from a job description; calls the model.

    Returns every key on the fixed checklist, in order, with an empty statement
    for anything the job description does not actually say. Nothing is stored —
    the operator edits these before the interview is created.
    """
    try:
        return await agent.extract(job_title=req.job_title, jd=req.jd, location=req.location)
    except ModelError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/candidate-archetypes")
def list_archetypes() -> dict[str, object]:
    """The fixed persona catalog the enrollment UI offers.

    Ships the rubric vocabulary alongside it so the picker can label a persona's
    stress bars without keeping its own copy of the criteria — a UI-side copy
    would drift the moment the rubric is retuned.
    """
    return {
        "catalog_version": archetype_catalog.CATALOG_VERSION,
        "defaults": archetype_catalog.default_keys(),
        "rubric_criteria": [
            {"id": c, "label": archetype_catalog.RUBRIC_LABELS[c]}
            for c in archetype_catalog.RUBRIC_CRITERIA
        ],
        "stress_labels": list(archetype_catalog.STRESS_LABELS),
        "archetypes": archetype_catalog.catalog(),
    }


@router.get("/trait-dimensions")
def list_trait_dimensions() -> dict[str, object]:
    """Every dimension and preset `custom_personas` values must come from."""
    return trait_dimensions.dimension_catalog()


def _compose_custom_persona(spec: CustomPersonaSpec) -> trait_dimensions.CustomPersona:
    """Compose one custom persona, turning a bad spec into a 422.

    Composition itself lives in `candidate_agent.trait_dimensions`; this only
    translates its failures into the transport's vocabulary.
    """
    try:
        return trait_dimensions.compose_custom_persona(**spec.model_dump())
    except (trait_dimensions.UnknownPresetError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


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

    if req.archetypes is None and not req.custom_personas:
        keys = archetype_catalog.default_keys()
    else:
        keys = req.archetypes or []
    unknown = [k for k in keys if k not in archetype_catalog.ARCHETYPES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown archetypes: {', '.join(unknown)}",
        )

    # Fixed-catalog keys resolve through the catalog and carry no human_traits.
    # A custom spec composes both layers here and carries its own archetype: it
    # is validated exactly like a catalog entry but never registered, so it
    # cannot leak into another interview's picker or grow the catalog without
    # bound. Its key is content-addressed, so re-submitting the same spec
    # resolves to the persona already enrolled.
    casts: list[tuple[str, Archetype | None, HumanTraitProfile | None]] = [
        (k, None, None) for k in keys
    ]
    for spec in req.custom_personas or []:
        composed = _compose_custom_persona(spec)
        casts.append((composed.key, composed.archetype, composed.human_traits))

    # The expectation grounds personas in the flags the interviewer is watching
    # for. Optional — enrollment must not require it.
    expectation = repo.get_expectation(interview_id)

    results: list[VirtualCandidate] = []
    # Independent generations converge on the same names, which makes a training
    # set confusing. Feed each cast the names already taken.
    taken: list[str] = [c.name for c in repo.list_candidates(interview_id)]
    for key, archetype, human_traits in casts:
        existing = repo.get_candidate_by_archetype(interview_id, key)
        if existing and not req.regenerate:
            results.append(existing)
            continue

        try:
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
                language=interview.language,
                candidate_notes=interview.candidate_notes,
                expectation=expectation,
                seed_override=(f"{req.seed_prefix}:{key}" if req.seed_prefix else None),
                avoid_names=taken,
                human_traits=human_traits,
                archetype=archetype,
                voices=GEMINI_TTS_VOICES,
            )
        except ModelError as exc:
            # A casting failure is the provider's answer, not a bug in this
            # service — surface it as a gateway error so the UI can say so
            # plainly instead of an opaque 500.
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
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


@router.get("/interviews/{interview_id}/sessions", response_model=list[SessionSummary])
def list_sessions(
    interview_id: str, repo: SessionStore = Depends(get_repo)
) -> list[SessionSummary]:
    """Every session held against one interview, newest first.

    Returns an empty list rather than 404 for an unknown interview: this is a
    list endpoint, and the caller asking "what has been run here" is answered by
    "nothing" just as well as by an error.
    """
    return repo.list_sessions(interview_id)


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


# ---------------------------------------------------------------------------
# Live text sessions
#
# The interviewer-training loop: a human manager types, a cast persona answers,
# and every turn is stamped server-side. This is the same session the Go voice
# engine will run later — same contract in, same transcript out — which is why
# the transcript carries `modality` from the first line.
# ---------------------------------------------------------------------------


def get_session_agent() -> CandidateSessionAgent:
    """Build the candidate session agent from environment configuration."""
    return CandidateSessionAgent()


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def start_session(
    req: SessionCreateRequest,
    repo: SessionWorkflowStore = Depends(get_repo),
    agent: VirtualCandidateAgent = Depends(get_candidate_agent),
) -> SessionResponse:
    """Open a session against one persona, casting it first if it is not enrolled."""
    interview = repo.get(req.interview_id)
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")
    # Look in the database before the catalog. An already-enrolled persona is
    # fully described by its stored record, and a custom-composed one is only
    # ever in the database — its archetype was validated at enrollment and
    # deliberately not registered, so requiring a catalog entry here would make
    # every composed persona unusable the moment the process restarted.
    candidate = repo.get_candidate_by_archetype(req.interview_id, req.archetype)
    if candidate is None:
        if req.archetype not in archetype_catalog.ARCHETYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"unknown archetype: {req.archetype}. Custom personas must be enrolled "
                    "through POST /interviews/{id}/candidates before a session can start."
                ),
            )
        try:
            candidate = await agent.generate(
                interview_id=req.interview_id,
                archetype_key=req.archetype,
                job_title=interview.job_title,
                jd=interview.jd,
                skills_required=interview.skills_required,
                experience_level=interview.experience_level,
                company_type=interview.company_type,
                job_location_type=interview.job_location_type,
                duration_minutes=interview.config.duration_minutes,
                interview_type="mixed",
                language=interview.language,
                candidate_notes=interview.candidate_notes,
                expectation=None,
                avoid_names=[c.name for c in repo.list_candidates(req.interview_id)],
                voices=GEMINI_TTS_VOICES,
            )
        except ModelError as exc:
            # A casting failure is the provider's answer, not a bug in this
            # service — surface it as a gateway error so the UI can say so
            # plainly instead of an opaque 500.
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        repo.save_candidate(candidate, model_used=agent.model)

    return repo.create_session(
        interview_id=req.interview_id,
        candidate_id=candidate.candidate_id,
        persona_key=candidate.archetype,
        planned_minutes=req.planned_minutes,
        opening_line=candidate.engine_contract.opening_line,
        modality=req.modality,
    )


@router.post(
    "/sessions/{session_id}/turns", response_model=Turn, status_code=status.HTTP_201_CREATED
)
async def take_turn(
    session_id: str,
    req: TurnRequest,
    repo: TurnWorkflowStore = Depends(get_repo),
    agent: CandidateSessionAgent = Depends(get_session_agent),
) -> Turn:
    """Record what the manager said and return the persona's reply.

    Both turns are persisted before the reply is returned, so a client that
    disconnects mid-call still leaves an honest transcript behind.
    """
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session is {session.status}, not live",
        )
    candidate = repo.get_candidate(session.candidate_id)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="the persona for this session has been deleted",
        )

    manager_turn = repo.append_turn(session_id, MANAGER, req.text)
    transcript = [
        *(t.model_dump() for t in session.turns),
        manager_turn.model_dump(),
    ]
    reply = await agent.reply(candidate.engine_contract, transcript)
    return repo.append_turn(session_id, CANDIDATE, reply)


@router.post("/sessions/{session_id}/end", response_model=SessionResponse)
def end_session(session_id: str, repo: SessionStore = Depends(get_repo)) -> SessionResponse:
    """Close a session. Ending it abruptly is itself a signal the report reads."""
    session = repo.end_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, repo: SessionStore = Depends(get_repo)) -> SessionResponse:
    """Fetch a session with its full timestamped transcript."""
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


# ---------------------------------------------------------------------------
# Voice sessions
#
# The audio never touches this service. The browser holds a WebRTC session with
# the realtime vendor directly, because routing 24 kHz PCM through Python would
# add hundreds of milliseconds to a budget measured in hundreds of milliseconds.
# What stays here is everything that must not be client-controlled: the compiled
# persona instructions, the voice, the turn-detection policy, and the transcript.
# ---------------------------------------------------------------------------

#: How long a minted credential stays redeemable. Long enough to cover a slow
#: page load and a microphone permission prompt, short enough that a leaked one
#: is worthless by the time it is found.
REALTIME_TTL_SECONDS = 600


def get_realtime_broker() -> RealtimeBroker:
    """Build the realtime-voice broker from environment configuration."""
    return build_realtime_broker()


@router.get("/voice-capability", response_model=VoiceCapabilityResponse)
def voice_capability() -> VoiceCapabilityResponse:
    """Whether this deployment can run voice sessions.

    The UI calls this before offering a Voice button. Absence of a realtime
    provider is a configuration answer, not an error — so this returns 200 with
    ``available: false`` rather than failing.
    """
    providers = realtime_providers_available()
    return VoiceCapabilityResponse(
        available=bool(providers),
        providers=providers,
        detail=(
            f"voice ready via {', '.join(providers)}"
            if providers
            else "no realtime-capable provider configured; set OPENAI_API_KEY"
        ),
    )


@router.post(
    "/sessions/{session_id}/realtime",
    response_model=RealtimeCredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mint_realtime_credential(
    session_id: str,
    repo: TurnWorkflowStore = Depends(get_repo),
    broker: RealtimeBroker = Depends(get_realtime_broker),
) -> RealtimeCredentialResponse:
    """Mint the browser's credential for a voice session.

    The persona instructions are compiled here and sealed into the credential
    vendor-side. The browser receives a secret and a URL — never the prompt, the
    knowledge ceilings, or the scorecard.
    """
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session is {session.status}, not live",
        )
    candidate = repo.get_candidate(session.candidate_id)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="the persona for this session has been deleted",
        )

    config = build_realtime_session(candidate.engine_contract, voices=broker.voices)
    try:
        credential = await broker.mint(session=config, ttl_seconds=REALTIME_TTL_SECONDS)
    except ModelError as exc:
        # A mint failure is the vendor's answer, not a bug in this service —
        # surface it as a gateway error so the UI can say so plainly.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    audio = config.get("audio")
    voice = ""
    if isinstance(audio, dict):
        output = audio.get("output")
        if isinstance(output, dict):
            voice = str(output.get("voice", ""))

    return RealtimeCredentialResponse(
        session_id=session_id,
        client_secret=credential.value,
        expires_at=credential.expires_at,
        model=credential.model,
        call_url=credential.call_url,
        voice=voice,
    )


@router.post(
    "/sessions/{session_id}/transcript",
    response_model=Turn,
    status_code=status.HTTP_201_CREATED,
)
def append_transcript_turn(
    session_id: str,
    req: TranscriptAppendRequest,
    repo: SessionStore = Depends(get_repo),
) -> Turn:
    """Record a turn that was spoken elsewhere, without generating a reply.

    The voice counterpart to ``POST /turns``. The timestamp is still stamped
    here rather than taken from the client: the browser knows when it *received*
    a transcript, which is not the same thing and is not comparable between two
    managers on two networks.
    """
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if session.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session is {session.status}, not live",
        )
    return repo.append_turn(session_id, req.speaker, req.text)


# ---------------------------------------------------------------------------
# Session recordings
#
# The browser's own MediaRecorder captures the tab audio (manager mic, left
# channel; persona TTS, right channel) and uploads it in chunks as it records
# -- this is the "browser" producer. When the Go engine's Finalizer becomes a
# second producer, it will PUT the same shape through the same table, just
# with `producer='engine'` and bytes that land in S3 instead of RECORDINGS_DIR.
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/recording/chunks",
    response_model=RecordingMeta,
    status_code=status.HTTP_201_CREATED,
)
async def append_recording_chunk(
    session_id: str,
    seq: int,
    request: Request,
    repo: RecordingWorkflowStore = Depends(get_repo),
) -> RecordingMeta:
    """Append one chunk of the session's audio recording.

    Chunks are accepted while the RECORDING is unfinalized, regardless of the
    session's own status: the last chunk legitimately lands around
    ``POST /sessions/{id}/end`` as the browser flushes its MediaRecorder on
    hangup, and gating on the recording's own status -- open until finalized --
    keeps acceptance deterministic instead of racing session teardown.
    """
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if session.modality != "voice":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session modality is {session.modality}, not voice",
        )
    data = await request.body()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty chunk body"
        )
    mime_type = request.headers.get("content-type", "application/octet-stream")
    try:
        return repo.append_recording_chunk(session_id, seq, mime_type, data)
    except ValueError as exc:
        # Wrong seq or already-finalized -- the adapter enforces both, the
        # same way append_turn's index and end_session's status guard do.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/recording/finalize", response_model=RecordingMeta)
def finalize_recording(session_id: str, repo: RecordingStore = Depends(get_repo)) -> RecordingMeta:
    """Mark the session's recording complete. Idempotent, like ``/end``."""
    meta = repo.finalize_recording(session_id)
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recording not found")
    return meta


@router.get("/sessions/{session_id}/recording")
def get_recording(session_id: str, repo: RecordingStore = Depends(get_repo)) -> Response:
    """Serve the session's recorded audio bytes.

    Serves a partial recording (``status == 'recording'``) too -- the honest
    artifact of a crashed or abandoned session, rather than a 404 that hides
    that a recording exists.
    """
    found = repo.read_recording(session_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recording not found")
    meta, data = found
    return Response(
        content=data,
        media_type=meta.mime_type,
        headers={"Content-Disposition": f'inline; filename="session-{session_id}.webm"'},
    )


# ---------------------------------------------------------------------------
# Session analysis
# ---------------------------------------------------------------------------
# Analysis reads the audio and takes about a minute, so it cannot be the same
# request that returns a report. It runs as a background task against a row
# created up front, and the caller polls. Report generation is gated on it
# having finished: a report built from a half-written analysis would be worse
# than no report.


async def _run_analysis(
    repo: AnalysisWorkflowStore,
    agent: AudioAnalysisAgent,
    session_id: str,
    recording_path: Path,
    context: AnalysisContext,
) -> None:
    """Run one analysis and record the outcome, whatever it is."""
    try:
        analysis = await agent.analyze(recording_path, context)
    except Exception as exc:  # the reason is stored on the row, not swallowed
        repo.fail_analysis(session_id, f"{type(exc).__name__}: {exc}")
        return
    repo.complete_analysis(session_id, analysis.model_dump(mode="json"))


@router.post(
    "/sessions/{session_id}/analyze",
    response_model=AnalysisMeta,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis(
    session_id: str,
    background: BackgroundTasks,
    repo: AnalysisWorkflowStore = Depends(get_repo),
    agent: AudioAnalysisAgent = Depends(get_analysis_agent),
) -> AnalysisMeta:
    """Begin analysing this session's recording. Returns immediately."""
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    interview = repo.get(session.interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")

    found = repo.read_recording(session_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this session has no recording, and the analysis reads the audio",
        )

    existing = repo.get_analysis_meta(session_id)
    if existing and existing.status == "running":
        return existing

    # The recording lives outside SQLite; hand the agent a real file rather than
    # bytes, so a long recording is not held in memory while it is windowed.
    _, data = found
    scratch = Path(tempfile.gettempdir()) / f"analysis-{session_id}.webm"
    scratch.write_bytes(data)

    context = reporting.build_analysis_context(
        interview, session, repo.get_candidate(session.candidate_id)
    )
    started = repo.begin_analysis(session_id)
    background.add_task(_run_analysis, repo, agent, session_id, scratch, context)
    return started


@router.get("/sessions/{session_id}/analysis", response_model=AnalysisMeta)
def get_analysis_status(
    session_id: str, repo: AnalysisWorkflowStore = Depends(get_repo)
) -> AnalysisMeta:
    """State and provenance of this session's analysis."""
    meta = repo.get_analysis_meta(session_id)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="this session has not been analysed"
        )
    return meta


@router.get("/sessions/{session_id}/analysis/full")
def get_analysis_body(
    session_id: str, repo: AnalysisWorkflowStore = Depends(get_repo)
) -> dict[str, Any]:
    """The analysis itself — transcript, observations and assessments."""
    body = repo.get_analysis(session_id)
    if body is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no completed analysis for this session",
        )
    return body


# ---------------------------------------------------------------------------
# Session reports
# ---------------------------------------------------------------------------
# The report is **stored**, not recomputed on read. A threshold change must not
# silently move a score a trainer already discussed with a manager -- the whole
# comparability design (spec section 9) rests on a report being a fixed artifact
# with its provenance stamped on it. Regenerating is an explicit POST.


def _report_or_404(repo: ReportWorkflowStore, session_id: str) -> dict[str, Any]:
    report = repo.get_report(session_id)
    if report is not None:
        return report
    # Distinguish the two 404s. "No report yet" sends someone to the generate
    # button; "no such session" sends them to check the id they were given.
    detail = (
        "no report generated for this session yet"
        if repo.get_session(session_id)
        else "session not found"
    )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


@router.post("/sessions/{session_id}/report", status_code=status.HTTP_201_CREATED)
def generate_session_report(
    session_id: str,
    english_weight: float | None = None,
    language_gate: bool = False,
    perspective: str = "manager",
    skills: str = "",
    max_development_areas: int = 3,
    repo: ReportWorkflowStore = Depends(get_repo),
) -> dict[str, Any]:
    """Generate (or regenerate) this session's report and store it.

    The query parameters are the operator's configuration: the two scoring
    toggles from the spec, plus who the report is written for and which
    competencies it is scored against. The toggles are stamped into the
    report's provenance because a report scored with English weighted in is not
    comparable to one without it.
    """
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    interview = repo.get(session.interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="interview not found")
    if not session.turns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="nothing was said in this session, so there is nothing to report on",
        )

    # A report is composed from the analysis. Building one before the analysis
    # finishes would quietly produce the deterministic half alone and present it
    # as the whole thing, which is the failure mode this gate exists to stop.
    analysis_meta = repo.get_analysis_meta(session_id)
    if analysis_meta is not None and analysis_meta.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="analysis is still running for this session",
        )

    # A composed persona keeps its scorecard on the candidate, not in the
    # catalog, so the ground truth is fetched rather than assumed.
    candidate = repo.get_candidate(session.candidate_id)

    report = reporting.generate(
        interview,
        session,
        candidate,
        repo.get_analysis(session_id),
        english_weight=english_weight,
        language_gate=language_gate,
        report_config={
            "perspective": perspective,
            # Comma-separated so the whole configuration fits in a link an
            # operator can share, rather than needing a request body.
            "skills": [s.strip() for s in skills.split(",") if s.strip()],
            "max_development_areas": max_development_areas,
        },
    )
    repo.save_report(session_id, report)
    return report


@router.get("/sessions/{session_id}/report")
def get_session_report(
    session_id: str, repo: ReportWorkflowStore = Depends(get_repo)
) -> dict[str, Any]:
    """The stored report for this session."""
    return _report_or_404(repo, session_id)


@router.get("/sessions/{session_id}/report.html")
def get_session_report_html(
    session_id: str, repo: ReportWorkflowStore = Depends(get_repo)
) -> Response:
    """The stored report as a self-contained HTML page.

    The console embeds this rather than re-implementing the layout, so what a
    trainer reads on screen and what comes out of the print dialog are the same
    document rendered once.
    """
    report = _report_or_404(repo, session_id)
    html = render.to_html(AssessmentReport.model_validate(report))
    return Response(content=html, media_type="text/html; charset=utf-8")
