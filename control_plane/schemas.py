"""Pydantic request/response schemas for the interview control-plane API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, overload

from pydantic import BaseModel, Field, field_validator, model_validator

from evaluation_agent.expectations import (
    COMPETENCY_IDS,
    MAX_CUSTOM_ITEMS,
    ExpectationClassification,
    ExpectationItem,
    fixed_items,
    fixed_text_by_id,
)
from evaluation_agent.schema import ROLE_FACT_KEYS, RoleFact

#: Longest interview, and therefore longest session, this service will accept.
#: `SessionCreateRequest.planned_minutes` shares it because the portal launcher
#: opens a session with the interview's own `duration_minutes` so the session
#: clock matches the configured length — a lower cap here rejects a valid
#: interview. It is a sanity bound, not an engine limit: the engine runs a
#: 45-60 minute interview and handles resumption (see okf engine.md).
MAX_INTERVIEW_MINUTES = 180


class InterviewConfigInput(BaseModel):
    """Runtime configuration overrides."""

    duration_minutes: int = Field(60, gt=0, le=MAX_INTERVIEW_MINUTES)
    question_mode: str = Field("AI", pattern="^(AI|HYBRID|MANUAL)$")
    interview_mode: str = Field("STANDARD", pattern="^(STANDARD|DEEP)$")


LANGUAGES = ("english_indian", "hinglish", "hindi")

#: Re-exported for handlers and the schema export. The expectation models are
#: owned by `evaluation_agent` — the same arrangement as `RoleFact` — because
#: the checklist is the evaluation layer's, not the transport's.
__all__ = [
    "COMPETENCY_IDS",
    "MAX_CUSTOM_ITEMS",
    "ROLE_FACT_KEYS",
    "ExpectationClassification",
    "ExpectationItem",
    "RoleFact",
]

#: The report sections a manager may be shown, and whether they are on by
#: default. Order is the order they render in.
#:
#: Re-keyed 2026-09-13 to the sections `report_engine/render.py` actually has.
#: The twelve keys copied from the wizard mockup named seven sections the engine
#: does not measure, and a toggle that changes nothing is the inert guard this
#: repo forbids. The rule behind the defaults: everything the current report
#: shows stays on; a number is on by default only when code computes it
#: deterministically (the readiness index is); prose no number stands behind is
#: off (the summary); and the transcript is raw evidence rather than a
#: computation, so it is off until asked for.
REPORT_SECTIONS: dict[str, bool] = {
    "scorecard": True,
    "qna": True,
    "bei": True,
    "strengths_gaps": True,
    "areas": True,
    "percentage_score": True,
    "transcript": False,
    "summary": False,
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


class ExpectationsDraftRequest(BaseModel):
    """POST /api/v1/expectations/draft body.

    The expectation counterpart of :class:`RoleFactsRequest`, and deliberately
    the same shape of call: it drafts, it stores nothing, and the operator
    edits what comes back before `POST /interviews` records it.
    """

    job_title: str = Field(..., min_length=1)
    jd: str = Field(..., min_length=1)
    skills_required: list[str] = Field(default_factory=list)
    location: str = ""


class ExpectationsClassifyRequest(BaseModel):
    """POST /api/v1/expectations/classify body — one item the manager typed."""

    text: str = Field(..., min_length=1, max_length=2000)


# ---------------------------------------------------------------------------
# The checklist validators
#
# Module functions rather than methods because two request models need exactly
# the same rules: `InterviewCreateRequest` writes the checklist, and
# `InterviewUpdateRequest` rewrites it. A second copy of them would be a second
# instrument, and the two would drift on the first rubric change.
#
# Both are **None-safe**, and that is a 500 this repo would otherwise ship:
# `InterviewUpdateRequest`'s fields are optional, so an explicit `"expectations":
# null` reaches the field validator as `None`. Pydantic maps only `ValueError`
# and `AssertionError` to a 422 — a `TypeError` from iterating `None` escapes as
# an unhandled exception. Returning `None` unchanged keeps "an explicit null is
# the same as absent" a decision made here, not a stack trace.
# ---------------------------------------------------------------------------


@overload
def validate_report_sections(v: dict[str, bool]) -> dict[str, bool]: ...


@overload
def validate_report_sections(v: None) -> None: ...


def validate_report_sections(v: dict[str, bool] | None) -> dict[str, bool] | None:
    """Reject unknown section keys and merge the rest onto the code defaults.

    The merge is onto :data:`REPORT_SECTIONS`, **not** onto whatever is stored:
    a partial map means "these keys, defaults for the rest", so a caller that
    sends one key resets the other seven. That is why the wizard sends all
    eight.
    """
    if v is None:
        return None
    unknown = sorted(set(v) - set(REPORT_SECTIONS))
    if unknown:
        raise ValueError(f"unknown report sections: {', '.join(unknown)}")
    return {**REPORT_SECTIONS, **v}


@overload
def validate_expectations(v: list[ExpectationItem]) -> list[ExpectationItem]: ...


@overload
def validate_expectations(v: None) -> None: ...


def validate_expectations(v: list[ExpectationItem] | None) -> list[ExpectationItem] | None:
    """Clamp the supplied list onto the instrument code owns.

    The four competencies, the wording of every fixed item and the custom
    ceiling are all code's. What the caller decides is which items are
    enabled, what the custom ones say, and which drafted ones survived.
    Missing fixed items are restored rather than refused: an interview that
    silently lost part of the instrument would stop being comparable to the
    ones beside it, and that is not a mistake worth failing a creation over.

    Restoring them is also why a partial list is destructive on **update**: the
    omitted fixed items come back *enabled* and the omitted drafted and custom
    ones are simply gone. A caller editing a checklist sends the whole list.
    """
    if v is None:
        return None
    rubric_text = fixed_text_by_id()
    kept: list[ExpectationItem] = []
    custom = 0
    for item in v:
        if item.competency_id not in COMPETENCY_IDS:
            raise ValueError(
                f"unknown competency: {item.competency_id}. One of: {', '.join(COMPETENCY_IDS)}"
            )
        if not item.text.strip():
            raise ValueError(f"expectation {item.id} has no text")
        if item.id in rubric_text:
            if item.text != rubric_text[item.id]:
                raise ValueError(f"fixed expectation {item.id} may be toggled off but not reworded")
            kept.append(item.model_copy(update={"source": "fixed"}))
            continue
        if item.source == "fixed":
            raise ValueError(f"{item.id} is not a fixed expectation id")
        if item.source == "custom":
            custom += 1
            kept.append(item.model_copy(update={"id": f"custom.{custom}"}))
            continue
        kept.append(item)

    if custom > MAX_CUSTOM_ITEMS:
        raise ValueError(f"at most {MAX_CUSTOM_ITEMS} custom expectations, got {custom}")

    ids = [item.id for item in kept]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"duplicate expectation ids: {', '.join(duplicated)}")

    present = set(ids)
    kept.extend(item for item in fixed_items() if item.id not in present)
    return kept


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
    persona_notes: str = Field(
        "",
        max_length=2000,
        description=(
            "Extra colour layered on top of the chosen archetype. Cannot override the "
            "archetype, the knowledge ceiling, or the universal safety rules."
        ),
    )
    role_facts: list[RoleFact] = Field(
        default_factory=list,
        description="Left empty, these are extracted from the job description at creation.",
    )
    expectations: list[ExpectationItem] = Field(
        default_factory=fixed_items,
        description=(
            "The behaviours the interviewer is expected to show, grouped under the four "
            "fixed competencies. Omit to take the rubric's own list with every item "
            "enabled; a fixed item may be toggled off but not reworded."
        ),
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
        return validate_report_sections(v)

    @field_validator("expectations")
    @classmethod
    def _valid_expectations(cls, v: list[ExpectationItem]) -> list[ExpectationItem]:
        return validate_expectations(v)


class InterviewUpdateRequest(BaseModel):
    """PATCH /api/v1/interviews/{interview_id} body.

    The wizard's step 1 creates the interview and step 2 edits it, so exactly
    two fields are editable: the checklist the interviewer is measured against
    and which report sections the manager sees. Everything else on the record —
    the job spec, the mode, the language — is step 1's and is not reachable
    here.

    Both fields are optional so either can be sent alone, and a body with
    neither is a 422 rather than a silent no-op that still moved
    ``updated_at``. An explicit ``null`` counts as absent for that rule, which
    makes ``{"expectations": null}`` on its own a 422 too: null means "I am not
    editing this field", and a request editing no field is the empty body.

    There is no partial-list merge. The validators here are the create
    validators, so a short ``expectations`` list re-enables every fixed item it
    omits and drops every drafted and custom item it omits, and a short
    ``report_sections`` map resets the keys it omits to their defaults. The
    client sends the whole list and all eight keys.
    """

    expectations: list[ExpectationItem] | None = None
    report_sections: dict[str, bool] | None = None

    @field_validator("report_sections")
    @classmethod
    def _known_sections_only(cls, v: dict[str, bool] | None) -> dict[str, bool] | None:
        return validate_report_sections(v)

    @field_validator("expectations")
    @classmethod
    def _valid_expectations(cls, v: list[ExpectationItem] | None) -> list[ExpectationItem] | None:
        return validate_expectations(v)

    @model_validator(mode="after")
    def _edits_something(self) -> InterviewUpdateRequest:
        """An update that changes nothing is a mistake, not an identity."""
        if self.expectations is None and self.report_sections is None:
            raise ValueError("send expectations, report_sections, or both")
        return self


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
    persona_notes: str = ""
    role_facts: list[RoleFact] = Field(default_factory=list)
    expectations: list[ExpectationItem] = Field(default_factory=fixed_items)
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
# Links and participants
#
# SkillBrew accounts create interviews; anyone holding a link takes them. What
# this service owns is therefore a *token* — because expiry has to be enforced
# by whatever creates the session — and a *participant keyed by email* — because
# cross-interview history has to be joined where the sessions are. Neither is a
# user table: there is no password, no login and no role here, and no email is
# ever sent from this service.
# ---------------------------------------------------------------------------

#: Deliberately not `EmailStr`: this is an identity **join key**, not an address
#: anything delivers to, and pulling in a deliverability validator would imply a
#: guarantee this service does not make. Shape only — one `@`, a dot in the
#: domain, no whitespace.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InterviewLinkCreateRequest(BaseModel):
    """POST /api/v1/interviews/{id}/links body.

    Several links per interview are allowed on purpose — a cohort in March and
    another in June — and one link serves any number of takers.
    """

    expires_at: datetime


class InterviewLinkResponse(BaseModel):
    """A minted link. The token is the credential; treat it as one."""

    token: str
    interview_id: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime


class PublicLinkResponse(BaseModel):
    """GET /api/v1/links/{token} — the only unauthenticated link route.

    Exactly what the landing form needs to render, and nothing else. The job
    description, the personas and the expectation checklist are all deliberately
    absent: this endpoint answers to anyone holding a token, so everything on it
    is public by construction.
    """

    job_title: str
    duration_minutes: int
    language: str
    expires_at: datetime


class ParticipantInput(BaseModel):
    """Who is taking the interview, from the landing form or the portal.

    The email is the identity: the same address in a different case or with
    stray whitespace is the same person, so it is trimmed and lower-cased here
    rather than at each call site.
    """

    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _normalised_email(cls, v: str) -> str:
        email = v.strip().lower()
        if not EMAIL_PATTERN.match(email):
            raise ValueError("email must look like name@example.com")
        return email

    @field_validator("name")
    @classmethod
    def _trimmed_name(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name


class ParticipantResponse(BaseModel):
    """One person who has taken at least one interview here."""

    id: str
    name: str
    email: str
    user_id: str = Field(
        "", description="The SkillBrew user id, when one has ever been supplied for this email."
    )
    created_at: datetime
    last_seen_at: datetime


class ParticipantSessionRow(BaseModel):
    """One row of GET /api/v1/participants/{id}/sessions.

    Every session this person has held, across every interview — which is what
    makes the same email meaning the same person worth storing. The four
    competency scores and the readiness index are read from the **stored**
    report, so a session that has not been reported on carries nulls rather
    than numbers computed on the fly for a list view.
    """

    session_id: str
    interview_id: str
    job_title: str
    archetype: str
    modality: str = Field("text", pattern="^(text|voice)$")
    status: str = Field(..., pattern="^(live|completed|abandoned)$")
    started_at: datetime
    ended_at: datetime | None = None
    readiness_index: int | None = None
    competency_scores: dict[str, float | None] | None = Field(
        None,
        description=(
            "The four competency scores from the stored report, keyed by competency id. "
            "None when this session has no report."
        ),
    )


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

    Two ways in. A console or portal caller names the ``interview_id``
    directly. A link holder sends ``invite_token`` instead, and the service
    resolves the interview from the link and enforces the expiry **at that
    moment** — an interview a cohort was invited to in March is not reopened in
    June because a tab was left open.
    """

    interview_id: str = Field(
        "", description="Required unless `invite_token` is sent; must match the link's when both."
    )
    archetype: str = Field(..., description="Archetype key from GET /api/v1/candidate-archetypes.")
    planned_minutes: int = Field(20, ge=5, le=MAX_INTERVIEW_MINUTES)
    modality: str = Field(
        "text",
        pattern="^(text|voice)$",
        description="A voice session still opens here; the browser then redeems a "
        "credential from POST /sessions/{id}/realtime and talks to the vendor directly.",
    )
    invite_token: str | None = Field(
        None, description="The token from GET /api/v1/links/{token}. Requires `participant`."
    )
    participant: ParticipantInput | None = Field(
        None,
        description=(
            "Who is taking the interview. Required with an `invite_token`; a logged-in "
            "portal caller sends its own user's name and email here too."
        ),
    )
    user_id: str | None = Field(
        None,
        description=(
            "The SkillBrew user id, when the caller is authenticated. Attaches to the "
            "participant row for this email and is never required."
        ),
    )

    @model_validator(mode="after")
    def _one_way_in(self) -> SessionCreateRequest:
        """A link needs a participant; no link needs an interview id."""
        if self.invite_token:
            if not self.participant:
                raise ValueError("participant (name and email) is required with an invite_token")
        elif not self.interview_id:
            raise ValueError("interview_id is required without an invite_token")
        return self


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
    archetype: str
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
    participant: ParticipantResponse | None = Field(
        None,
        description=(
            "Who took this session. Null only for sessions that predate participants "
            "(2026-09-13) and for the engine's own ingest-created rows."
        ),
    )


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
    archetype: str
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
    participant: ParticipantResponse | None = Field(
        None, description="Who took this session, when one was recorded."
    )


# ---------------------------------------------------------------------------
# Engine ingest — the Go engine's single write-back at the end of a voice
# session (docs/ENGINE_IMPLEMENTATION_PLAN.md §8.2). Idempotent on session_id.
# ---------------------------------------------------------------------------


class IngestTurn(BaseModel):
    """One turn as the engine observed it. Speakers are the engine's own names."""

    turn: int = Field(..., ge=0)
    speaker: str = Field(..., pattern="^(human|persona)$")
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    text: str = ""
    probed_skill: str = ""
    deferred: bool = False
    fallback_used: bool = Field(
        False, description="The Thinker missed its deadline; depth on this turn is discounted."
    )
    trimmed: bool = False
    barged_in: bool = False
    heard_ms: int = Field(0, ge=0)


class IngestCeilingFlag(BaseModel):
    """A post-hoc Judge finding against a skill's knowledge ceiling."""

    turn: int = Field(..., ge=0)
    skill: str
    severity: str
    rationale: str = ""
    walkback_hint: str = ""


class IngestUnlockFlip(BaseModel):
    """The single instant the persona's unlock_condition was judged met."""

    turn: int = Field(..., ge=0)
    evidence: str = ""
    at: datetime


class IngestObjectKeys(BaseModel):
    """Where the rest of the bundle landed in object storage. Empty until the engine uploads."""

    recording: str = ""
    transcript: str = ""
    event_log: str = ""


class SessionIngest(BaseModel):
    """POST /api/v1/sessions/{id}/ingest body — the engine's write-back for one session."""

    session_id: str = Field(..., min_length=1, max_length=120, pattern="^[A-Za-z0-9_-]+$")
    candidate_id: str = Field(..., min_length=1)
    interview_id: str = Field(..., min_length=1)
    contract_fingerprint: str = Field(
        "", description="SHA-256 of the contract bytes the session ran on."
    )
    engine_version: str = ""
    started_at: datetime
    ended_at: datetime
    end_reason: str = Field(..., pattern="^(interviewer_ended|abandoned|duration_cap|error)$")
    s3: IngestObjectKeys = Field(default_factory=IngestObjectKeys)
    turns: list[IngestTurn] = Field(default_factory=list)
    ceiling_flags: list[IngestCeilingFlag] = Field(default_factory=list)
    unlock_flip: IngestUnlockFlip | None = None
    suppressed_answers: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    degradations: list[str] = Field(default_factory=list)


class IngestReceipt(BaseModel):
    """What the engine gets back: the session's final state on this side."""

    session_id: str
    status: str = Field(..., pattern="^(completed|abandoned)$")
    turns_stored: int = Field(..., ge=0)
    duplicate: bool = Field(
        ...,
        description="True when this session had already been ingested; the record was replaced.",
    )
    received_at: datetime


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
