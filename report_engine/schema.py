"""Public models for the report engine — the bundle in, the report out.

Schema only. No logic lives here beyond field validation, which the
architecture suite checks.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

BUNDLE_VERSION = "v1"

#: Bumped whenever a threshold, transfer function or signal weight changes.
#: Two reports are only comparable when this matches. See spec section 9.
SCORING_VERSION = "v1.0"


# ------------------------------------------------------------------ input ----


class Turn(BaseModel):
    """One transcript turn, server-stamped."""

    index: int = Field(..., ge=0)
    speaker: str = Field(..., pattern="^(manager|candidate)$")
    text: str
    elapsed_ms: int = Field(0, ge=0)
    #: Recording-timeline span. Voice sessions only; None in text mode.
    start_ms: int | None = None
    end_ms: int | None = None


class ClarityFact(BaseModel):
    """A role fact the manager is expected to convey. Empty statement = not applicable."""

    key: str
    statement: str = ""


class ScorecardSignal(BaseModel):
    """One thing the persona is hiding, and what it takes to surface it."""

    id: str
    signal: str
    weight: float = Field(..., gt=0.0, le=1.0)
    how_to_surface: str = ""


class Persona(BaseModel):
    """The archetype faced. Supplies the fixed denominator — see spec section 1."""

    archetype_key: str
    label: str = ""
    must_discover: list[ScorecardSignal] = Field(default_factory=list)
    session_beats: list[str] = Field(default_factory=list)
    stresses: dict[str, int] = Field(default_factory=dict)


class JobCard(BaseModel):
    """The role. Supplies the clarity checklist and nothing else."""

    job_title: str
    summary: str = ""
    role_family: str = "sales"
    clarity_facts: list[ClarityFact] = Field(default_factory=list)


class SessionMeta(BaseModel):
    """Identity and clock for one session."""

    session_id: str
    manager_id: str = ""
    manager_name: str = ""
    modality: str = Field("text", pattern="^(text|voice)$")
    planned_minutes: int = 20
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str = ""


class RecordingRef(BaseModel):
    """Where the audio is, and how its channels are laid out."""

    path: str
    channel_layout: str = "manager_left_candidate_right"
    status: str = "complete"


class ScoringOptions(BaseModel):
    """The operator's two toggles. See spec sections 3.4 and 4.1."""

    #: None = English is advisory only. A float adds a fifth weighted criterion
    #: and scales the rubric's four by (1 - w).
    english_weight: float | None = Field(None, gt=0.0, lt=1.0)
    #: Interviews happen in whatever language the room speaks, so the default is
    #: to **score anyway** and say plainly which signals that weakens. Turning
    #: this on refuses a non-English session outright instead - available for an
    #: org that would rather have no number than a shaky one, but never the
    #: default, because a missing report helps nobody.
    language_gate: bool = False


class Criterion(BaseModel):
    """One scored manager competency, as declared by the org's rubric."""

    id: str
    label: str
    weight: float = Field(..., gt=0.0, le=1.0)
    covers: list[str] = Field(default_factory=list)


class Band(BaseModel):
    """A readiness band. `floor` is inclusive; the highest matching band wins."""

    label: str
    floor: int = Field(..., ge=0, le=100)


class Rubric(BaseModel):
    """The scoring instrument. Org-owned configuration, passed in, never authored here."""

    version: str
    criteria: list[Criterion]
    bands: list[Band]

    def band_for(self, readiness: int) -> str:
        """The band a 0-100 readiness index falls in."""
        for band in sorted(self.bands, key=lambda b: b.floor, reverse=True):
            if readiness >= band.floor:
                return band.label
        return self.bands[0].label if self.bands else "unbanded"


class SessionBundle(BaseModel):
    """Everything the engine needs. One file, no database."""

    bundle_version: str = BUNDLE_VERSION
    session: SessionMeta
    job_card: JobCard
    persona: Persona
    turns: list[Turn]
    rubric: Rubric
    jurisdiction: str = "IN"
    recording: RecordingRef | None = None
    scoring_options: ScoringOptions = Field(default_factory=ScoringOptions)


# ----------------------------------------------------------------- output ----


class Evidence(BaseModel):
    """A quoted transcript moment. Every claim in the report carries one."""

    turn_index: int
    at_ms: int
    speaker: str
    quote: str

    @property
    def timestamp(self) -> str:
        """`mm:ss` on the session clock."""
        total = self.at_ms // 1000
        return f"{total // 60:02d}:{total % 60:02d}"


class SignalResult(BaseModel):
    """One deterministic measurement and the score it transfers to."""

    id: str
    label: str
    criterion: str
    modality: str = Field("both", pattern="^(text|voice|both)$")
    #: None means not measurable in this session. Never a fake zero.
    value: float | None = None
    display: str = "—"
    sub_score: float | None = None
    weight: float = 1.0
    basis: str = ""
    reason: str = ""
    #: Whether this measurement rests on English lexicons or English syntax. It
    #: still produces a number on a code-mixed session; that number is just
    #: worth less, and the criterion's confidence says so.
    language_sensitive: bool = False
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def measurable(self) -> bool:
        """Whether this signal produced a score for this session."""
        return self.sub_score is not None

    def dedupe_evidence(self) -> None:
        """Drop repeated quotes.

        Two candidate questions answered in one manager turn are two hits on
        one piece of evidence; quoting that turn twice makes the report look
        padded rather than thorough.
        """
        seen: set[tuple[int, str]] = set()
        unique = []
        for item in self.evidence:
            key = (item.turn_index, item.quote)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        self.evidence = unique


class CriterionScore(BaseModel):
    """One rubric criterion, scored from its measurable signals."""

    id: str
    label: str
    weight: float
    score: float | None = None
    confidence: str = "high"
    confidence_reason: str = ""
    signals: list[SignalResult] = Field(default_factory=list)


class QuestionAct(BaseModel):
    """One question the manager asked. The unit of analysis — spec section 3.2."""

    turn_index: int
    at_ms: int
    text: str
    type: str
    is_probe: bool = False
    probe_depth: int = 0
    topic_id: int = 0
    segment: str = "ASSESS"
    protected_topic: str = ""

    @property
    def timestamp(self) -> str:
        """`mm:ss` on the session clock."""
        total = self.at_ms // 1000
        return f"{total // 60:02d}:{total % 60:02d}"


class Finding(BaseModel):
    """A strength or a gap: a behaviour, a moment, and what to do about it."""

    signal_id: str
    headline: str
    detail: str = ""
    alternative: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class LanguageCheck(BaseModel):
    """What language the manager spoke, always reported — spec section 3.4."""

    detected: str
    english_token_share: float
    confidence: str
    gated: bool = False


class Provenance(BaseModel):
    """What produced this report. Reports are only comparable when these match."""

    scoring_version: str = SCORING_VERSION
    bundle_version: str = BUNDLE_VERSION
    rubric_version: str = ""
    english_weight: float | None = None
    language_gate: bool = False
    jurisdiction: str = "IN"
    pack_version: str = ""
    judge: str = "none"


class AssessmentReport(BaseModel):
    """The complete report for one session."""

    session_id: str
    manager_name: str = ""
    persona_label: str = ""
    job_title: str = ""
    modality: str = "text"
    duration_ms: int = 0

    unscoreable: str = ""
    validity_warnings: list[str] = Field(default_factory=list)

    readiness_index: int | None = None
    band: str = ""
    criteria: list[CriterionScore] = Field(default_factory=list)

    strengths: list[Finding] = Field(default_factory=list)
    gaps: list[Finding] = Field(default_factory=list)
    development_areas: list[Finding] = Field(default_factory=list)
    next_practice: str = ""
    next_practice_reason: str = ""

    question_acts: list[QuestionAct] = Field(default_factory=list)
    language: LanguageCheck | None = None
    provenance: Provenance = Field(default_factory=Provenance)
