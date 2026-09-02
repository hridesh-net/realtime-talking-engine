"""Pydantic request/response schemas for the interview control-plane API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from evaluation_agent.schema import CLARITY_FACT_KEYS, ClarityFact


class InterviewConfigInput(BaseModel):
    """Runtime configuration overrides."""

    duration_minutes: int = Field(60, gt=0, le=180)
    question_mode: str = Field("AI", pattern="^(AI|HYBRID|MANUAL)$")
    interview_mode: str = Field("STANDARD", pattern="^(STANDARD|DEEP)$")


LANGUAGES = ("english_indian", "hinglish", "hindi")

__all__ = ["CLARITY_FACT_KEYS", "ClarityFact"]  # re-exported for handlers and the schema export

#: The report sections a manager may be shown, and whether they are on by
#: default. Order is the order they render in. The two `False` entries are the
#: spec's own defaults: pace and fillers are advisory, and English proficiency
#: is off because it is not a competency this product assesses.
REPORT_SECTIONS: dict[str, bool] = {
    "readiness_index": True,
    "welcome_greeting": True,
    "role_explanation": True,
    "category_scorecard": True,
    "strengths_gaps": True,
    "key_moments": True,
    "question_analysis": True,
    "bias_check": True,
    "transcript": True,
    "next_practice": True,
    "advisory_pace_fillers": False,
    "manager_english": False,
}


class RoleFactsRequest(BaseModel):
    """POST /api/v1/role-facts body.

    Drafts the role-fact checklist from a job description so the wizard can
    offer the spec's "paste a JD to auto-fill" affordance. Deliberately not part
    of interview creation: the operator sees the drafts and corrects them before
    anything is stored, and creating an interview stays a fast, model-free call.
    """

    job_title: str = Field(..., min_length=1)
    jd: str = Field(..., min_length=1)
    location: str = ""


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
    location: str = Field("", description="Where the role is based, e.g. Jaipur.")
    department: str = Field("", description="Free text; the UI suggests, it does not constrain.")
    manager_level: str = Field("", description='e.g. "Frontline manager".')
    language: str = Field(
        "english_indian",
        pattern="^(english_indian|hinglish|hindi)$",
        description="The language the persona opens the interview in.",
    )
    proctoring: str = Field(
        "off",
        pattern="^(off|identity|full)$",
        description="Recorded on the interview. No camera is accessed at any setting.",
    )
    candidate_notes: str = Field(
        "",
        max_length=2000,
        description=(
            "Extra colour layered on top of the chosen archetype. Cannot override the "
            "archetype, the knowledge ceiling, or the universal safety rules."
        ),
    )
    clarity_facts: list[ClarityFact] = Field(
        default_factory=list,
        description="Left empty, these are extracted from the job description at creation.",
    )
    report_sections: dict[str, bool] = Field(
        default_factory=lambda: dict(REPORT_SECTIONS),
        description="Which report sections the manager sees. Unknown keys are rejected.",
    )
    config: InterviewConfigInput = Field(default_factory=InterviewConfigInput)
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("report_sections")
    @classmethod
    def _known_sections_only(cls, v: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(set(v) - set(REPORT_SECTIONS))
        if unknown:
            raise ValueError(f"unknown report sections: {', '.join(unknown)}")
        return {**REPORT_SECTIONS, **v}


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
    location: str = ""
    department: str = ""
    manager_level: str = ""
    language: str = "english_indian"
    proctoring: str = "off"
    candidate_notes: str = ""
    clarity_facts: list[ClarityFact] = Field(default_factory=list)
    report_sections: dict[str, bool] = Field(default_factory=lambda: dict(REPORT_SECTIONS))
    status: str
    config: InterviewConfigInput
    ai_persona: CandidatePersona | None = None
    scheduled_at: datetime | None = None
    created_at: datetime
    start_url: str
    metadata: dict[str, Any]


class CustomPersonaSpec(BaseModel):
    """One dynamically composed persona.

    Mirrors ``candidate_agent.trait_dimensions.compose_custom_persona``. Every
    field except ``label``, ``function`` and ``region`` takes its legal values
    from ``GET /api/v1/trait-dimensions``; those three are free text, and are
    length- and character-constrained here and by
    ``candidate_agent.schema.PROFILE_TEXT_PATTERN`` because they reach the
    compiled system prompt verbatim.

    Composing is validated exactly like a hand-written archetype — an unknown
    preset or an out-of-vocabulary value fails the request with a 422 rather
    than casting something malformed. The result is validated but never
    registered: a composed persona belongs to the interview it was cast for.
    """

    #: One line. Reaches the casting prompt, so no newlines and no essay.
    label: str = Field(..., pattern=r"^[^\r\n]{1,80}$")
    verdict: str = Field(..., pattern="^(select|reject|borderline)$")
    competence: str
    conscientiousness: str
    communication: str
    emotional_stance: str
    honesty: str
    bias_trap: str | None = None

    affect: str
    verbal_style: str
    language: str
    comprehension: str
    motivation: str
    negotiation_stance: str
    environment: str
    seniority: str
    function: str
    region: str
    gender_presentation: str
    age_band: str
    notice_period: str
    compliance_traps: list[str] = Field(default_factory=list)
    protected_info_type: str | None = None
    integrity_red_flags: list[str] = Field(default_factory=list)
    offers_in_hand: int = Field(0, ge=0)


class CandidateEnrollRequest(BaseModel):
    """POST /api/v1/interviews/{id}/candidates body.

    Omit `archetypes` to enroll the two defaults — the two personas that carry
    the heaviest rubric criteria between them.
    """

    archetypes: list[str] | None = Field(
        None,
        description="Archetype keys from GET /api/v1/candidate-archetypes. "
        "Defaults to ['cooperative_trap', 'evasive'].",
    )
    custom_personas: list[CustomPersonaSpec] | None = Field(
        None,
        description="Personas composed on the spot from GET /api/v1/trait-dimensions "
        "values, instead of a fixed archetype key.",
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


# ---------------------------------------------------------------------------
# Live text session
#
# Phase 1 of the manager-assessment pivot runs the conversation on the existing
# interview/archetype domain model, so a session hangs off `interview_id`. That
# field becomes `role_id` when the job card replaces the job spec; the rest of
# the shape — turns, timestamps, modality — is already what the evaluation layer
# and the Go voice engine will consume, so it does not move again.
# ---------------------------------------------------------------------------


class Turn(BaseModel):
    """One line of the transcript.

    ``at`` and ``elapsed_ms`` are stamped server-side, never by the client: they
    are the evaluation layer's time base, and a client clock would make two
    sessions incomparable.
    """

    index: int = Field(..., ge=0, description="Position in the transcript, from 0.")
    speaker: str = Field(..., pattern="^(manager|candidate)$")
    text: str
    at: datetime
    elapsed_ms: int = Field(..., ge=0, description="Milliseconds since the session started.")


class SessionCreateRequest(BaseModel):
    """POST /api/v1/sessions body.

    Opens a live interview against one persona. If that archetype is not yet
    enrolled for the interview it is cast on the spot, so starting a
    conversation never needs a separate enrollment step.
    """

    interview_id: str
    archetype: str = Field(..., description="Archetype key from GET /api/v1/candidate-archetypes.")
    planned_minutes: int = Field(20, ge=5, le=45)
    modality: str = Field(
        "text",
        pattern="^(text|voice)$",
        description="A voice session still opens here; the browser then redeems a "
        "credential from POST /sessions/{id}/realtime and talks to the vendor directly.",
    )


class TurnRequest(BaseModel):
    """POST /api/v1/sessions/{id}/turns body — what the manager just said."""

    text: str = Field(..., min_length=1)


class RecordingMeta(BaseModel):
    """The session's audio artifact. Bytes via GET /sessions/{id}/recording."""

    session_id: str
    status: str = Field(..., pattern="^(recording|complete)$")
    producer: str = Field("browser", pattern="^(browser|engine)$")
    mime_type: str
    byte_size: int = Field(..., ge=0)
    next_seq: int = Field(..., ge=0)
    channel_layout: str = "manager_left_candidate_right"
    created_at: datetime
    updated_at: datetime


class SessionResponse(BaseModel):
    """A live or finished interview session with its full transcript."""

    id: str
    interview_id: str
    candidate_id: str
    persona_key: str
    candidate_name: str
    status: str = Field(..., pattern="^(live|completed|abandoned)$")
    modality: str = Field(
        "text",
        pattern="^(text|voice)$",
        description="Voice arrives with the Go engine; the transcript shape does not change.",
    )
    planned_minutes: int
    started_at: datetime
    ended_at: datetime | None = None
    opening_line: str
    turns: list[Turn] = Field(default_factory=list)
    recording: RecordingMeta | None = None


class AnalysisMeta(BaseModel):
    """An analysis run's state and provenance, without the analysis itself.

    The body is large; a caller polling for completion does not need it.
    """

    session_id: str
    status: str = Field(..., pattern="^(running|complete|failed)$")
    error: str = ""
    instructions_version: str = ""
    model_used: str = ""
    session_judgement: float | None = None
    dropped_anchors: int = 0
    windows: int = 0
    started_at: datetime
    finished_at: datetime | None = None


class ReportMeta(BaseModel):
    """A generated report's headline and provenance, without its body.

    The body is large and the list view does not need it. Provenance rides here
    because two reports are only comparable when it matches - see
    `docs/REPORT_ENGINE_SCORING_SPEC.md` section 9.
    """

    session_id: str
    readiness_index: int | None = None
    band: str = ""
    unscoreable: str = ""
    scoring_version: str
    rubric_version: str
    english_weight: float | None = None
    language_gate: bool = True
    created_at: datetime
    updated_at: datetime


class SessionSummary(BaseModel):
    """One row of GET /api/v1/interviews/{id}/sessions.

    Deliberately transcript-free. The list screen needs to know that a session
    happened and how long it ran; shipping every transcript to render a table
    would send the evaluation layer's evidence over the wire to draw a row count.
    """

    id: str
    interview_id: str
    persona_key: str
    candidate_name: str
    status: str = Field(..., pattern="^(live|completed|abandoned)$")
    modality: str = Field("text", pattern="^(text|voice)$")
    planned_minutes: int
    started_at: datetime
    ended_at: datetime | None = None
    turn_count: int = Field(..., ge=0, description="Turns stored so far, both speakers.")
    has_recording: bool = False
    has_report: bool = False
    analysis_status: str = ""


class TranscriptAppendRequest(BaseModel):
    """POST /api/v1/sessions/{id}/transcript body.

    Records a turn **without** generating a reply. Voice sessions need this: the
    audio never passes through this service, so the browser reports each
    finalised transcript back and the stored record stays complete.
    """

    speaker: str = Field(..., pattern="^(manager|candidate)$")
    text: str = Field(..., min_length=1)


class RealtimeCredentialResponse(BaseModel):
    """POST /api/v1/sessions/{id}/realtime response.

    Everything the browser needs to open a speech-to-speech session, and nothing
    it does not. The persona instructions are baked into the minted credential
    vendor-side, so they are deliberately **not** returned here — a client that
    could read them could also edit them. ``client_config`` is the one field a
    client is handed to pass back to the vendor, and it carries only connect
    parameters (transcription toggles, turn detection, resumption) — never the
    prompt, the opening line, or the ceilings.
    """

    session_id: str
    client_secret: str = Field(..., description="Ephemeral. Expires; scoped to one session.")
    expires_at: int = Field(..., description="Unix seconds. Connect before this.")
    model: str
    provider: str = Field(..., description="Which talker: selects the browser's transport.")
    call_url: str = Field(
        default="",
        description="POST the SDP offer here with the secret as bearer. "
        "Empty for providers whose SDK owns the endpoint.",
    )
    voice: str = Field(..., description="Derived from the persona; stable across sessions.")
    stt_source: str = Field(
        default="", description="Who transcribes the interviewer, for the UI's status line."
    )
    noise_reduction: str = Field(
        default="", description="Vendor-side denoising profile; empty when the vendor applies none."
    )
    client_config: dict = Field(
        default_factory=dict,
        description="Non-secret connect parameters the browser passes to the vendor SDK verbatim.",
    )


class VoiceCapabilityResponse(BaseModel):
    """GET /api/v1/voice-capability — whether this deployment can do voice at all."""

    available: bool
    providers: list[str] = Field(default_factory=list)
    detail: str
