"""Virtual candidate persona schema.

Two documents live here:

* ``VirtualCandidate`` — the full persona. Assembled in code from a fixed
  archetype plus a job-grounded LLM draft.
* ``EngineContract`` — the slice the Go interview-candidate engine consumes at
  runtime. Versioned separately so the engine can pin a contract version while
  the persona document keeps evolving.

``CandidateDraft`` is the narrow schema the LLM is allowed to fill. Everything
outside it — verdict, trait scores, scorecard weights — is computed.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

PERSONA_VERSION = "v1.2"
ENGINE_CONTRACT_VERSION = "v1.3"


# ---------------------------------------------------------------------------
# Persona sub-documents
# ---------------------------------------------------------------------------


class SpeechProfile(BaseModel):
    """Way of talking. Drives the realtime voice model in the Go engine."""

    pace: str = Field(..., pattern="^(slow|measured|fast)$")
    verbosity: str = Field(..., pattern="^(terse|balanced|verbose)$")
    filler_frequency: int = Field(..., ge=0, le=10)
    hesitation_frequency: int = Field(..., ge=0, le=10)
    formality: str = Field(..., pattern="^(casual|neutral|formal)$")
    interrupts_interviewer: bool
    tone: str
    verbal_tics: list[str] = Field(default_factory=list)
    sample_phrases: list[str] = Field(default_factory=list)


class AptitudeProfile(BaseModel):
    """Smartness/dumbness ratio and seriousness. All axes fixed across personas."""

    smartness: int = Field(..., ge=0, le=10)
    dumbness: int = Field(..., ge=0, le=10)
    #: smartness / (smartness + dumbness), rounded to 2dp. 0.5 means evenly split.
    smartness_ratio: float = Field(..., ge=0.0, le=1.0)
    seriousness: int = Field(..., ge=0, le=10)
    effort: int = Field(..., ge=0, le=10)
    interest: int = Field(..., ge=0, le=10)
    honesty: int = Field(..., ge=0, le=10)
    preparedness: int = Field(..., ge=0, le=10)
    nervousness: int = Field(..., ge=0, le=10)


class SkillKnowledge(BaseModel):
    """What the persona actually knows about one required skill."""

    skill: str
    level: int = Field(..., ge=0, le=10)
    stance: str = Field(..., pattern="^(solid|shallow|bluffs|absent)$")
    talking_points: list[str] = Field(default_factory=list)
    #: The question depth at which this persona stops being able to answer.
    breaking_point: str
    #: Specific incorrect things they will assert. Empty unless they bluff.
    wrong_beliefs: list[str] = Field(default_factory=list)
    #: Pre-authored ways this persona expands a wrong belief when pushed. The
    #: engine replays these; it never lets a model invent competence downward
    #: at runtime, which would void `seed_fingerprint` determinism.
    belief_elaborations: list[str] = Field(default_factory=list)
    #: Literal vague material for a skill the persona cannot actually discuss.
    #: Vagueness is a generation target, not an absence of output.
    vague_deflections: list[str] = Field(default_factory=list)
    #: Phrases an interviewer uses when probing this skill. Feeds the engine's
    #: deterministic pre-gate, which classifies from partial transcripts.
    probe_aliases: list[str] = Field(default_factory=list)


class ResumeClaim(BaseModel):
    """One claim on the persona's resume, and how truthful it is."""

    claim: str
    truthfulness: str = Field(..., pattern="^(true|exaggerated|false)$")
    probe_that_exposes_it: str


class AnswerPolicy(BaseModel):
    """How the persona decides what to reveal. The engine treats this as law."""

    default_answer_depth: str = Field(..., pattern="^(minimal|adequate|thorough)$")
    #: What the interviewer must do to unlock a deeper answer.
    reveals_depth_when: str
    on_unknown_question: str
    on_pressure: str
    on_silence: str
    always_does: list[str] = Field(default_factory=list)
    never_does: list[str] = Field(default_factory=list)


#: Free-text profile fields reach the compiled system prompt verbatim, so they
#: are constrained to a single short line of ordinary characters. The closed
#: vocabularies elsewhere in this model come from the directive tables in
#: `candidate_agent.engine_contract`; a test asserts the two stay in step.
#: (Re-declared rather than imported — `engine_contract` imports this module.)
PROFILE_TEXT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 &'./-]{0,39}$"


class EnvironmentProfile(BaseModel):
    """Session-logistics realism — the 'Environment' row of the realism taxonomy."""

    camera_behavior: str = Field(..., pattern="^(on|off|toggling)$")
    network_drops_at_minute: int | None = Field(default=None, ge=0)
    background_noise: str
    joins_late_minutes: int = Field(default=0, ge=0)
    mobile_or_driving: bool = False
    hard_stop_minute: int | None = Field(default=None, ge=1)


class HumanTraitProfile(BaseModel):
    """The generic human-candidate trait dimensions (the realism taxonomy).

    Orthogonal to the archetype's skill/verdict mechanics — this is the
    realism, communication, and compliance-training layer. Entirely
    code-derived from fixed dimension presets, same as trait scores; the model
    never authors or sees these values.
    """

    affect: str = Field(
        ...,
        pattern="^(hostile|defensive|anxious|apathetic|over_eager|arrogant|"
        "cooperative|flirtatious_inappropriate|grieving_distressed)$",
    )
    verbal_style: str = Field(
        ...,
        pattern="^(rambling|monosyllabic|tangential|interrupts|long_silences|"
        "jargon_flooder|over_formal)$",
    )

    fluency: int = Field(..., ge=0, le=10)
    literacy_level: str = Field(..., pattern="^(basic|functional|fluent|native)$")
    native_speaker: bool
    accent_strength: float = Field(..., ge=0.0, le=1.0)
    code_switch_probability: float = Field(..., ge=0.0, le=1.0)
    vocabulary_ceiling: str = Field(..., pattern="^(basic|workplace|technical|executive)$")

    clarification_rate: str = Field(..., pattern="^(low|medium|high)$")
    misinterprets_question_rate: str = Field(..., pattern="^(low|medium|high)$")
    needs_rephrasing: bool

    #: Subset of resume_inflation, concealed_termination, ghost_employer,
    #: dual_employment, proxy_candidate, ai_assisted_answers.
    integrity_red_flags: list[
        Annotated[
            str,
            StringConstraints(
                pattern="^(resume_inflation|concealed_termination|ghost_employer|"
                "dual_employment|proxy_candidate|ai_assisted_answers)$"
            ),
        ]
    ] = Field(default_factory=list)

    motivation: str = Field(
        ...,
        pattern="^(comp_only|counter_offer_risk|not_really_looking|"
        "location_blocked|family_pressured|passion_hire)$",
    )
    negotiation_stance: str = Field(
        ...,
        pattern="^(anchors_high|refuses_to_disclose_ctc|lowballs_self|"
        "demands_off_band|offer_shopping)$",
    )

    #: Subset of volunteers_protected_info, requests_off_policy_favour,
    #: asks_illegal_question_back.
    compliance_traps: list[
        Annotated[
            str,
            StringConstraints(
                pattern="^(volunteers_protected_info|requests_off_policy_favour|"
                "asks_illegal_question_back)$"
            ),
        ]
    ] = Field(default_factory=list)
    #: Set only when "volunteers_protected_info" is in compliance_traps:
    #: pregnancy, age, religion, caste, disability, marital_status.
    protected_info_type: str | None = Field(
        default=None, pattern="^(pregnancy|age|religion|caste|disability|marital_status)$"
    )

    environment: EnvironmentProfile

    seniority: str = Field(..., pattern="^(fresher|junior|mid|senior|lead|manager)$")
    gender_presentation: str = Field(..., pattern="^(woman|man|non_binary|unspecified)$")
    age_band: str = Field(..., pattern=r"^(18-24|25-34|35-44|45-54|55\+)$")
    notice_period: str = Field(..., pattern="^(immediate|15_days|30_days|60_days|90_days)$")
    #: Genuinely open — an org has more regions and functions than a closed list
    #: can hold. Constrained instead: no newlines, no control characters, and
    #: short enough that nothing sentence-shaped fits. Both are rendered quoted
    #: and *above* the hard rules in the compiled prompt, so a value that does
    #: get creative still cannot displace them.
    function: str = Field(..., pattern=PROFILE_TEXT_PATTERN)
    region: str = Field(..., pattern=PROFILE_TEXT_PATTERN)
    offers_in_hand: int = Field(default=0, ge=0)


class ScorecardItem(BaseModel):
    """One weighted signal the interviewer is expected to surface."""

    id: str
    signal: str
    weight: float = Field(..., ge=0.0, le=1.0)
    how_to_surface: str


class InterviewerScorecard(BaseModel):
    """Ground-truth answer key for grading the interviewer, not the candidate."""

    expected_verdict: str = Field(..., pattern="^(select|reject|borderline)$")
    interviewer_challenge: str
    must_discover: list[ScorecardItem]
    interviewer_failure_modes: list[str]
    pass_condition: str


class PrecompiledBelief(BaseModel):
    """One wrong belief, with the material to sustain it, fixed at design time.

    `claim_id` is assigned by code in a stable order so the same persona
    compiles the same ids every time — the claims ledger seeds from these at
    turn 0, and a runtime-invented belief would break that determinism.
    """

    claim_id: str = Field(..., pattern="^b[0-9]+$")
    skill: str
    statement: str
    elaborations: list[str] = Field(default_factory=list)
    vague_deflections: list[str] = Field(default_factory=list)


class PregateSkill(BaseModel):
    """How the engine recognises a probe at this skill, from partial speech."""

    aliases: list[str] = Field(default_factory=list)
    #: Probe this skill at or below this ceiling and the engine defers rather
    #: than letting the speech model answer unaided.
    defer_at_or_below: int = Field(..., ge=0, le=10)


class UnlockSpec(BaseModel):
    """`unlock_condition` prose compiled into something the engine can act on.

    `never` short-circuits per-turn assessment entirely — most personas never
    reveal depth, and paying a reasoning call per turn to re-learn that is
    waste.
    """

    kind: str = Field(..., pattern="^(never|conditional)$")
    condition: str = ""
    hints: list[str] = Field(default_factory=list)


class EngineContract(BaseModel):
    """Runtime slice consumed by the Go interview-candidate engine."""

    contract_version: str = ENGINE_CONTRACT_VERSION
    candidate_id: str
    interview_id: str
    #: Compiled deterministically from the persona — inject verbatim as the
    #: realtime model's system instruction. The engine does not re-derive it.
    system_prompt: str
    opening_line: str
    voice_directives: dict[str, Any]
    turn_policy: dict[str, Any]
    #: skill -> hard ceiling (0-10). The engine must not let the persona
    #: demonstrate more than this, whatever the interviewer asks.
    knowledge_ceiling: dict[str, int]
    unlock_condition: str
    forbidden_behaviors: list[str]

    # ---- engine runtime fields (contract v1.3) ----------------------------
    #: Seeds the engine's claims ledger at turn 0. The persona's false beliefs
    #: exist before the first question is asked.
    precompiled_beliefs: list[PrecompiledBelief] = Field(default_factory=list)
    #: Persona-voiced filler, synthesized to audio at contract load so a defer
    #: can start playing inside 50 ms while the reasoning model is still
    #: thinking. Derived from this persona's own tics and phrases.
    stall_phrases: list[str] = Field(default_factory=list)
    #: skill -> how to spot a probe at it, for the deterministic pre-gate.
    pregate_lexicon: dict[str, PregateSkill] = Field(default_factory=dict)
    unlock_spec: UnlockSpec = Field(default_factory=lambda: UnlockSpec(kind="never"))
    #: Voice the stall clips are synthesized in. Must equal the speech model's
    #: voice or the filler and the answer are audibly two different people.
    #: Empty means the engine resolves it with the same deterministic rule.
    tts_voice_id: str = ""


class VirtualCandidate(BaseModel):
    """A cast persona: who they are, what they know, and how to run them."""

    persona_version: str = PERSONA_VERSION
    candidate_id: str
    interview_id: str
    archetype: str
    archetype_label: str
    catalog_version: str

    name: str
    headline: str
    background: str
    years_experience: int = Field(..., ge=0, le=40)

    verdict: str = Field(..., pattern="^(select|reject|borderline)$")
    verdict_rationale: str

    speech_profile: SpeechProfile
    aptitude: AptitudeProfile
    knowledge_map: list[SkillKnowledge]
    resume_claims: list[ResumeClaim] = Field(default_factory=list)
    answer_policy: AnswerPolicy
    interviewer_scorecard: InterviewerScorecard
    engine_contract: EngineContract
    #: Optional realism-taxonomy layer — realism, communication, and compliance
    #: training dimensions, orthogonal to the archetype's skill/verdict axis.
    human_traits: HumanTraitProfile | None = None

    #: SHA256 over the full persona — integrity check on a stored record.
    #: Changes whenever any content changes, including on a re-cast.
    fingerprint: str
    #: SHA256 over the seeded identity only (seed, archetype, traits, verdict,
    #: versions). Stable across re-casts — this is the reproducibility claim.
    seed_fingerprint: str
    seed: str
    raw_model_output: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# LLM draft — the ONLY fields the model is allowed to author
# ---------------------------------------------------------------------------

CANDIDATE_DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "headline": {"type": "string"},
        "background": {"type": "string"},
        "years_experience": {"type": "integer"},
        "verdict_rationale": {"type": "string"},
        "verbal_tics": {"type": "array", "items": {"type": "string"}},
        "sample_phrases": {"type": "array", "items": {"type": "string"}},
        "reveals_depth_when": {"type": "string"},
        "always_does": {"type": "array", "items": {"type": "string"}},
        "never_does": {"type": "array", "items": {"type": "string"}},
        "opening_line": {"type": "string"},
        "knowledge_map": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "level": {"type": "integer"},
                    "stance": {
                        "type": "string",
                        "enum": ["solid", "shallow", "bluffs", "absent"],
                    },
                    "talking_points": {"type": "array", "items": {"type": "string"}},
                    "breaking_point": {"type": "string"},
                    "wrong_beliefs": {"type": "array", "items": {"type": "string"}},
                    "belief_elaborations": {"type": "array", "items": {"type": "string"}},
                    "vague_deflections": {"type": "array", "items": {"type": "string"}},
                    "probe_aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "skill",
                    "level",
                    "stance",
                    "talking_points",
                    "breaking_point",
                    "wrong_beliefs",
                    "belief_elaborations",
                    "vague_deflections",
                    "probe_aliases",
                ],
            },
        },
        "resume_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "truthfulness": {
                        "type": "string",
                        "enum": ["true", "exaggerated", "false"],
                    },
                    "probe_that_exposes_it": {"type": "string"},
                },
                "required": ["claim", "truthfulness", "probe_that_exposes_it"],
            },
        },
        "must_discover": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "signal": {"type": "string"},
                    "how_to_surface": {"type": "string"},
                },
                "required": ["id", "signal", "how_to_surface"],
            },
        },
    },
    "required": [
        "name",
        "headline",
        "background",
        "years_experience",
        "verdict_rationale",
        "verbal_tics",
        "sample_phrases",
        "reveals_depth_when",
        "always_does",
        "never_does",
        "opening_line",
        "knowledge_map",
        "resume_claims",
        "must_discover",
    ],
}
