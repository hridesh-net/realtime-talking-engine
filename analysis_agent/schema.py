"""Shapes for the audio analysis.

Declarations only. The rules the model follows live in `INSTRUCTIONS.md`, and
the decision logic that validates its answers lives in `agent.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Bumped whenever INSTRUCTIONS.md changes in a way that alters what the model
#: is asked to do. Stamped onto every stored analysis, because two analyses are
#: only comparable when they were produced under the same instructions.
ANALYSIS_INSTRUCTIONS_VERSION = "v1.1"

#: How the session judgement is composed. **Reading the person in front of you
#: outweighs working through a list**, because the list is a plan and the
#: interview is a conversation. A manager who correctly reads a disengaged or
#: hostile candidate and closes early did the right thing, and will necessarily
#: have left expectation items unmet - scoring coverage first would mark that
#: down as a failure when it is the correct call.
#:
#: Applied in code, not by the model: the model assesses each half separately
#: and never sees the weights.
PERSONA_RESPONSE_WEIGHT = 0.60
EXPECTATION_COVERAGE_WEIGHT = 0.40

CONFIDENCE = "^(high|medium|low)$"


class AnalysedTurn(BaseModel):
    """One turn as the model heard it, in the spoken language and in English."""

    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    speaker: str = Field(..., pattern="^(manager|candidate)$")
    text: str
    text_en: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class QuestionObservation(BaseModel):
    """A manager question, typed by the rules in INSTRUCTIONS.md section 5.1."""

    at_ms: int = Field(..., ge=0)
    text: str
    text_en: str = ""
    type: str = Field(
        ..., pattern="^(leading|double_barrelled|behavioural|situational|closed|open)$"
    )
    is_probe: bool = False
    targets_skill: str = ""
    clarity: int = Field(5, ge=0, le=10)
    confidence: str = Field("medium", pattern=CONFIDENCE)


class TopicFlag(BaseModel):
    """A protected, high-risk or stereotyped moment. Section 5.2."""

    at_ms: int = Field(..., ge=0)
    category: str
    raised_by: str = Field("manager", pattern="^(manager|candidate)$")
    pursued_by_manager: bool = False
    quote: str
    quote_en: str = ""
    why: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class SilenceObservation(BaseModel):
    """A pause over two seconds, and who ended it. Section 5.4."""

    at_ms: int = Field(..., ge=0)
    seconds: float = Field(..., ge=0)
    broken_by: str = Field(..., pattern="^(manager|candidate|nobody)$")


class InterruptionObservation(BaseModel):
    """The manager cutting across the candidate. Backchannels excluded."""

    at_ms: int = Field(..., ge=0)
    quote: str = ""
    candidate_cut_short: bool = True
    confidence: str = Field("medium", pattern=CONFIDENCE)


class DiscoveryObservation(BaseModel):
    """Whether one `must_discover` item was surfaced. Section 5.5."""

    id: str
    status: str = Field(..., pattern="^(surfaced|not_surfaced|volunteered|unclear)$")
    is_restraint_item: bool = False
    at_ms: int = Field(0, ge=0)
    evidence: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class DeliveryObservation(BaseModel):
    """How the manager came across, from what is audible. Section 5.3."""

    question_clarity: int = Field(5, ge=0, le=10)
    explanation_quality: int = Field(5, ge=0, le=10)
    tone_trajectory: str = ""
    tone_shifts: list[dict[str, Any]] = Field(default_factory=list)
    pace_note: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class PersonaResponseAssessment(BaseModel):
    """Did the manager read *this* candidate and adapt to them?

    The dominant half of the judgement. A nervous fresher needs warmth before
    they can answer; an evasive candidate needs probing discipline; a
    comp-first candidate needs the band held. Doing the same interview
    regardless of who is in front of you is the failure this measures.
    """

    read_the_candidate: int = Field(5, ge=0, le=10)
    adapted_approach: int = Field(5, ge=0, le=10)
    handled_the_hard_moment: int = Field(5, ge=0, le=10)
    rating: int = Field(5, ge=0, le=10)
    reasoning: str = ""
    misread_signals: list[str] = Field(default_factory=list)
    evidence_at_ms: list[int] = Field(default_factory=list)
    confidence: str = Field("medium", pattern=CONFIDENCE)


class EarlyEndAssessment(BaseModel):
    """Whether the interview was closed early, and whether that was right.

    Closing early on a candidate who is plainly disengaged, dishonest or
    unsuited is a legitimate decision, not an abandoned interview. What makes it
    right is that the manager had *evidence* before deciding — enough to know,
    and a civil close. Cutting someone off in the first minute on a hunch is a
    different thing entirely, and this separates the two.
    """

    ended_early: bool = False
    at_ms: int = Field(0, ge=0)
    evidence_before_deciding: int = Field(5, ge=0, le=10)
    closed_civilly: bool = True
    justified: bool = True
    reasoning: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class ExpectationCoverageAssessment(BaseModel):
    """How much of the plan was worked through — read conditionally.

    An item is only a gap if it was *reachable*: there was time, and the
    candidate was engaged enough to answer it. Unreached items in a session the
    manager rightly closed at four minutes are not gaps.
    """

    rating: int = Field(5, ge=0, le=10)
    reachable_items: int = 0
    covered_items: int = 0
    reasoning: str = ""
    unreachable_because: str = ""
    confidence: str = Field("medium", pattern=CONFIDENCE)


class CriterionAssessment(BaseModel):
    """The model's rating for one rubric criterion — an input, not the score."""

    id: str
    rating: int = Field(..., ge=0, le=10)
    reasoning: str
    evidence_at_ms: list[int] = Field(default_factory=list)
    confidence: str = Field("medium", pattern=CONFIDENCE)


class SessionAnalysis(BaseModel):
    """Everything the model observed in one session."""

    instructions_version: str = ANALYSIS_INSTRUCTIONS_VERSION
    model_used: str = ""
    windows: int = 1
    audio_duration_ms: int = 0

    spoken_languages: list[str] = Field(default_factory=list)
    quality_notes: str = ""

    transcript: list[AnalysedTurn] = Field(default_factory=list)
    questions: list[QuestionObservation] = Field(default_factory=list)
    topic_flags: list[TopicFlag] = Field(default_factory=list)
    silences: list[SilenceObservation] = Field(default_factory=list)
    interruptions: list[InterruptionObservation] = Field(default_factory=list)
    discovery: list[DiscoveryObservation] = Field(default_factory=list)
    delivery: DeliveryObservation = Field(default_factory=DeliveryObservation)
    criteria: list[CriterionAssessment] = Field(default_factory=list)

    #: The two halves of the session judgement, weighted in code at 60/40.
    persona_response: PersonaResponseAssessment = Field(default_factory=PersonaResponseAssessment)
    expectation_coverage: ExpectationCoverageAssessment = Field(
        default_factory=ExpectationCoverageAssessment
    )
    early_end: EarlyEndAssessment = Field(default_factory=EarlyEndAssessment)
    #: The two halves composed at PERSONA_RESPONSE_WEIGHT / EXPECTATION_COVERAGE_WEIGHT.
    #: Computed in the harness so the weighting is auditable and tunable in one
    #: place, and so the model never learns what it is being weighted on.
    session_judgement: float = 0.0

    #: Anchors the harness rejected for falling outside the recording. Kept
    #: rather than silently dropped: a model that confabulates timestamps is
    #: something the operator should be able to see.
    dropped_anchors: int = 0


class AnalysisContext(BaseModel):
    """What the interview was held against — the expectation, as context."""

    job_title: str = ""
    job_description: str = ""
    skills_required: list[str] = Field(default_factory=list)
    clarity_facts: list[dict[str, str]] = Field(default_factory=list)
    language_setting: str = ""

    persona_label: str = ""
    persona_description: str = ""
    interviewer_challenge: str = ""
    #: What kind of person the manager was facing. These are what a manager is
    #: supposed to read and adapt to, so the model cannot judge adaptation
    #: without them.
    persona_traits: dict[str, Any] = Field(default_factory=dict)
    persona_speech: dict[str, Any] = Field(default_factory=dict)
    persona_answer_policy: dict[str, Any] = Field(default_factory=dict)
    persona_knowledge_band: list[int] = Field(default_factory=list)
    must_discover: list[dict[str, Any]] = Field(default_factory=list)
    session_beats: list[str] = Field(default_factory=list)
    interviewer_failure_modes: list[str] = Field(default_factory=list)

    rubric: list[dict[str, Any]] = Field(default_factory=list)
    #: The generated InterviewExpectation, when one exists. Supplied as "what
    #: this interview was meant to cover", never as scoring guidance - its own
    #: criteria describe assessing the candidate, not the manager.
    interview_expectation: dict[str, Any] | None = None
