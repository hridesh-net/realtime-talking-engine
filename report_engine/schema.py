"""Public models for the report engine — the bundle in, the report out.

Schema only. No logic lives here beyond field validation, which the
architecture suite checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class AnalysisInput(BaseModel):
    """The audio analysis, as data.

    Mirrors what `analysis_agent` produces without importing it: the report
    engine depends on no first-party package, so the analysis travels in the
    bundle the same way the rubric does. Only the fields the report uses are
    declared; anything else in the payload is ignored rather than rejected, so
    the analysis schema can grow without breaking report generation.
    """

    model_config = ConfigDict(extra="ignore")

    instructions_version: str = ""
    model_used: str = ""
    windows: int = 0
    dropped_anchors: int = 0
    audio_duration_ms: int = 0
    spoken_languages: list[str] = Field(default_factory=list)
    quality_notes: str = ""

    transcript: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    topic_flags: list[dict[str, Any]] = Field(default_factory=list)
    silences: list[dict[str, Any]] = Field(default_factory=list)
    interruptions: list[dict[str, Any]] = Field(default_factory=list)
    discovery: list[dict[str, Any]] = Field(default_factory=list)
    delivery: dict[str, Any] = Field(default_factory=dict)
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    persona_response: dict[str, Any] = Field(default_factory=dict)
    expectation_coverage: dict[str, Any] = Field(default_factory=dict)
    early_end: dict[str, Any] = Field(default_factory=dict)
    session_judgement: float = 0.0


class ReportConfig(BaseModel):
    """Who this report is written for, and what it should score against.

    Two things are configurable, and both are grounded in what the feedback
    research actually supports rather than in taste:

    **Perspective.** Kluger & DeNisi (1996, 607 effect sizes) found feedback
    raises performance by d = .41 on average while **over a third of feedback
    interventions made performance worse** — the split being whether attention
    lands on the task or on the person. Perspective therefore changes how the
    report addresses its reader, never how harsh it is: the same evidence reads
    differently to the manager who gave the interview, to the coach preparing
    their next session, and to a reviewer who needs the evidence first.

    **Skills.** The competency checklist a role is scored against. Job-analysis-
    based content is the first of Campion, Palmer & Campion's (1997) fifteen
    structure components, and a generic role-family list is a stand-in for it.
    An org that knows its own competencies should be able to say so.
    """

    #: `manager` addresses the interviewer directly ("you asked"), which is the
    #: task-focused second person the feedback literature supports for
    #: self-review. `coach` writes about them for someone preparing their next
    #: practice session. `reviewer` leads with evidence for someone auditing.
    perspective: str = Field("manager", pattern="^(manager|coach|reviewer)$")

    #: Competencies this role is scored against. Empty falls back to the shipped
    #: role-family pack.
    skills: list[str] = Field(default_factory=list)

    #: No study gives an optimal number. The default of 3 follows Kluger &
    #: DeNisi's mechanism — diffuse, high-volume feedback shifts attention from
    #: the task to the self — plus cognitive-load-based coaching practice that
    #: focused feedback beats comprehensive lists. Stated as convention.
    max_development_areas: int = Field(3, ge=1, le=8)


class Basis(BaseModel):
    """How this report was produced, in the reader's language.

    Printed on the report itself rather than kept in a design document: a
    trainer acting on a number is owed a plain statement of what produced it and
    what it could not see.
    """

    lines: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


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
    #: The audio analysis, when one has been run. Absent means the report is the
    #: deterministic half alone, and says so.
    analysis: AnalysisInput | None = None
    report_config: ReportConfig = Field(default_factory=ReportConfig)
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


class ChecklistItem(BaseModel):
    """One item a signal counted over, and whether the manager covered it.

    A ratio signal loses the thing a reader most wants back: *which* ones were
    missed. "4 of 5 role facts conveyed" sends them looking for the fifth. A
    signal that counts over a known list therefore publishes the list, and the
    scorecard prints it as a covered/missed strip.
    """

    label: str
    covered: bool


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
    #: Where the number came from. `measured` is counted from the transcript by
    #: code and is reproducible; `assessed` came from the audio analysis and
    #: rests on a model's reading of the recording; `judged` came from the report
    #: judge reading the transcript, and every claim under it carries a span
    #: checked verbatim. The report shows which is which, because a reader is
    #: owed the difference.
    source: str = Field("measured", pattern="^(measured|assessed|judged)$")
    #: Whether this measurement rests on English lexicons or English syntax. It
    #: still produces a number on a code-mixed session; that number is just
    #: worth less, and the criterion's confidence says so.
    language_sensitive: bool = False
    #: Populated only by signals that count over a named list. Empty everywhere
    #: else, and never scored from — the sub-score is the measurement, this is
    #: the same measurement itemised for the reader.
    checklist: list[ChecklistItem] = Field(default_factory=list)
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


class Bullet(BaseModel):
    """One plain-language line under a criterion: what the manager did, or did not.

    The scorecard a reader acts on has to say what happened, not which detector
    fired. `signals` still carries the measurement behind every bullet, so the
    claim stays checkable — this is the sentence, not the evidence.
    """

    text: str
    #: `positive` earned the criterion something, `negative` cost it something,
    #: `neutral` is context that did neither. Drives nothing but colour.
    polarity: str = Field("neutral", pattern="^(positive|negative|neutral)$")
    #: The signal this line was written about, so a bullet can always be traced
    #: back to the number it came from.
    signal_id: str = ""


class CriterionScore(BaseModel):
    """One rubric criterion, scored from its measurable signals."""

    id: str
    label: str
    #: The rubric's own description of what this criterion covers, copied so the
    #: scorecard can say what a competency *is* without importing the rubric.
    covers: list[str] = Field(default_factory=list)
    weight: float
    score: float | None = None
    confidence: str = "high"
    confidence_reason: str = ""
    signals: list[SignalResult] = Field(default_factory=list)

    #: The paragraph a reader gets instead of the signal table. Composed by code
    #: from the measurements; replaced by the judge's prose when one has run.
    narrative: str = ""
    #: Up to three plain-language lines under the narrative.
    bullets: list[Bullet] = Field(default_factory=list)


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
    #: The analysis that fed this report, when there was one.
    analysis_instructions_version: str = ""
    analysis_model: str = ""
    #: The judge that wrote this report's prose, when one has run. Empty means
    #: every sentence in the report was composed by code from the measurements.
    judge_model: str = ""
    judge_version: str = ""


class AssessmentReport(BaseModel):
    """The complete report for one session."""

    session_id: str
    manager_name: str = ""
    persona_label: str = ""
    job_title: str = ""
    modality: str = "text"
    duration_ms: int = 0
    #: When the session was held. Carried onto the report because a filed
    #: development report is read months later, when "which one was this" is the
    #: first question.
    started_at: datetime | None = None

    unscoreable: str = ""
    validity_warnings: list[str] = Field(default_factory=list)

    readiness_index: int | None = None
    band: str = ""
    #: The paragraph the report opens with. Composed by code from the criterion
    #: scores; replaced by the judge's prose when one has run.
    summary: str = ""
    criteria: list[CriterionScore] = Field(default_factory=list)

    strengths: list[Finding] = Field(default_factory=list)
    gaps: list[Finding] = Field(default_factory=list)
    development_areas: list[Finding] = Field(default_factory=list)
    next_practice: str = ""
    next_practice_reason: str = ""

    question_acts: list[QuestionAct] = Field(default_factory=list)
    language: LanguageCheck | None = None
    #: How the report was produced. Always populated.
    basis: Basis = Field(default_factory=Basis)
    provenance: Provenance = Field(default_factory=Provenance)
