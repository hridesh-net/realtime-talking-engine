"""Fixed catalog of virtual-candidate archetypes.

Code-defined and versioned, exactly like `expectation_agent.rubric`. The LLM
grounds a persona in a specific job spec; it can never change which archetype a
candidate is, what verdict they deserve, or where their trait scores land.

Every archetype exists to test one specific interviewer skill. A persona that
does not challenge the interviewer in a distinct way does not belong here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

CATALOG_VERSION = "v1.0"

#: The trait axes every persona carries. Fixed — the report compares
#: interviewers across candidates, so the axes cannot drift per interview.
TRAIT_NAMES: tuple[str, ...] = (
    "smartness",
    "dumbness",
    "seriousness",
    "effort",
    "interest",
    "honesty",
    "preparedness",
    "nervousness",
)

VERDICTS = ("select", "reject", "borderline")


class SpeechSpec(TypedDict):
    """Fixed speech settings an archetype contributes to every persona it casts."""

    pace: str
    verbosity: str
    filler_frequency: int
    hesitation_frequency: int
    formality: str
    interrupts_interviewer: bool
    tone: str


class AnswerPolicySpec(TypedDict):
    """Fixed answer settings an archetype contributes to every persona it casts."""

    default_answer_depth: str
    on_unknown_question: str
    on_pressure: str
    on_silence: str


@dataclass(frozen=True)
class ScorecardSignal:
    """One thing a competent interviewer must surface about this persona."""

    id: str
    signal: str
    weight: float
    how_to_surface: str


@dataclass(frozen=True)
class Archetype:
    """One persona family: fixed verdict, fixed trait bounds, fixed scorecard."""

    key: str
    label: str
    description: str
    verdict: str
    #: The interviewer skill this persona exists to test.
    interviewer_challenge: str
    #: Inclusive (min, max) bounds per trait; the seeded RNG picks inside them.
    traits: dict[str, tuple[int, int]]
    #: Inclusive (min, max) competence band for the job's *required* skills.
    knowledge_band: tuple[int, int]
    speech: SpeechSpec
    answer_policy: AnswerPolicySpec
    must_discover: list[ScorecardSignal]
    interviewer_failure_modes: list[str]
    #: True when the persona may be genuinely strong outside the required stack.
    allows_adjacent_strength: bool = False
    #: Set for the two personas enrolled by default.
    default_slot: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def trait_bounds_json(self) -> dict[str, list[int]]:
        """Trait bounds as JSON-serializable lists."""
        return {k: [v[0], v[1]] for k, v in self.traits.items()}


ARCHETYPES: dict[str, Archetype] = {}


def _register(a: Archetype) -> Archetype:
    total = round(sum(s.weight for s in a.must_discover), 4)
    if total != 1.0:
        raise ValueError(f"{a.key}: must_discover weights sum to {total}, expected 1.0")
    if a.verdict not in VERDICTS:
        raise ValueError(f"{a.key}: bad verdict {a.verdict}")
    missing = set(TRAIT_NAMES) - set(a.traits)
    if missing:
        raise ValueError(f"{a.key}: missing traits {sorted(missing)}")
    ARCHETYPES[a.key] = a
    return a


# ---------------------------------------------------------------------------
# The two defaults — one obvious hire, one obvious no-hire.
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="strong_hire",
        label="Should be selected",
        description=(
            "Genuinely strong for the role. Deep in the required stack, explains why "
            "not just what, honest about the edges of their knowledge."
        ),
        verdict="select",
        interviewer_challenge=(
            "Confirm a strong signal with evidence instead of ending early, and still "
            "find the real gap. Every candidate has one."
        ),
        traits={
            "smartness": (8, 10),
            "dumbness": (0, 2),
            "seriousness": (8, 10),
            "effort": (8, 10),
            "interest": (8, 10),
            "honesty": (8, 10),
            "preparedness": (8, 10),
            "nervousness": (1, 3),
        },
        knowledge_band=(7, 10),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 1,
            "hesitation_frequency": 2,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "calm, structured, concrete",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": "admit_and_reason",
            "on_pressure": "engages with the harder version of the question",
            "on_silence": "adds a relevant caveat or trade-off",
        },
        must_discover=[
            ScorecardSignal(
                id="depth_evidence",
                signal="Concrete, first-hand depth in the core required skill",
                weight=0.35,
                how_to_surface=(
                    "Ask for a specific system they built and why they chose that design"
                ),
            ),
            ScorecardSignal(
                id="tradeoff_reasoning",
                signal="Reasons about trade-offs rather than reciting best practices",
                weight=0.30,
                how_to_surface="Present a constraint that invalidates their first answer",
            ),
            ScorecardSignal(
                id="honest_gap",
                signal="Names a genuine gap in their own knowledge without prompting",
                weight=0.20,
                how_to_surface="Ask what part of this stack they would need to ramp up on",
            ),
            ScorecardSignal(
                id="ownership",
                signal="Describes personal contribution, not team accomplishments",
                weight=0.15,
                how_to_surface="Ask what they personally wrote versus what the team shipped",
            ),
        ],
        interviewer_failure_modes=[
            "Ends the technical phase early because the first answers were good",
            "Never finds a gap, so the feedback has no development signal",
            "Spends the saved time selling the role instead of assessing",
        ],
        default_slot="select",
        tags=["baseline", "positive-control"],
    )
)

_register(
    Archetype(
        key="clear_reject",
        label="Should be rejected",
        description=(
            "Not close to the bar. Surface-level answers, no ownership, cannot connect "
            "any claim to a concrete outcome."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Reach a defensible no-hire backed by specific evidence, without becoming "
            "dismissive or cutting the interview short."
        ),
        traits={
            "smartness": (2, 4),
            "dumbness": (6, 9),
            "seriousness": (3, 5),
            "effort": (3, 5),
            "interest": (4, 6),
            "honesty": (4, 6),
            "preparedness": (2, 4),
            "nervousness": (4, 6),
        },
        knowledge_band=(1, 4),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 5,
            "hesitation_frequency": 6,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "vague, generic, textbook",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "guess_vaguely",
            "on_pressure": "restates the same generic answer in different words",
            "on_silence": "waits for the interviewer to move on",
        },
        must_discover=[
            ScorecardSignal(
                id="depth_absent",
                signal="Cannot go one level below a textbook definition",
                weight=0.35,
                how_to_surface="Ask 'how does that actually work under the hood' twice in a row",
            ),
            ScorecardSignal(
                id="no_concrete_example",
                signal="Cannot produce a single concrete example from real work",
                weight=0.30,
                how_to_surface="Ask for a specific incident, PR, or design decision they owned",
            ),
            ScorecardSignal(
                id="evidence_for_reject",
                signal="Interviewer records specific evidence, not just an impression",
                weight=0.20,
                how_to_surface="Note the exact question that broke down and what was said",
            ),
            ScorecardSignal(
                id="fair_chance",
                signal="Candidate was given a fair second angle before being written off",
                weight=0.15,
                how_to_surface="Re-ask the failed topic from a different, simpler direction",
            ),
        ],
        interviewer_failure_modes=[
            "Decides in the first five minutes and stops probing",
            "Records 'weak' with no quotable evidence behind it",
            "Lets the candidate off the hook to avoid an awkward silence",
        ],
        default_slot="reject",
        tags=["baseline", "negative-control"],
    )
)


# ---------------------------------------------------------------------------
# Effort and engagement archetypes
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="lazy",
        label="Lazy",
        description=(
            "Average ability, minimal effort. Answers the literal question and stops. "
            "Did no preparation and does not pretend otherwise."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Separate low effort from low ability. They are different findings and only "
            "one of them is coachable."
        ),
        traits={
            "smartness": (4, 6),
            "dumbness": (4, 6),
            "seriousness": (2, 4),
            "effort": (1, 3),
            "interest": (3, 5),
            "honesty": (6, 8),
            "preparedness": (1, 3),
            "nervousness": (2, 4),
        },
        knowledge_band=(4, 6),
        speech={
            "pace": "slow",
            "verbosity": "terse",
            "filler_frequency": 4,
            "hesitation_frequency": 5,
            "formality": "casual",
            "interrupts_interviewer": False,
            "tone": "flat, low-energy, minimal",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "admit_flatly",
            "on_pressure": "gives a slightly longer answer, then stops again",
            "on_silence": "stays silent and waits",
        },
        must_discover=[
            ScorecardSignal(
                id="effort_vs_ability",
                signal="Interviewer establishes whether the shallowness is effort or ability",
                weight=0.40,
                how_to_surface="Offer an easy win in their strongest area and see if depth appears",
            ),
            ScorecardSignal(
                id="no_preparation",
                signal="Did not research the role, company, or job description",
                weight=0.25,
                how_to_surface="Ask what they understood the role to involve",
            ),
            ScorecardSignal(
                id="silence_handling",
                signal="Interviewer keeps the session productive despite dead air",
                weight=0.20,
                how_to_surface=(
                    "Follow a non-answer with a concrete scenario instead of another open question"
                ),
            ),
            ScorecardSignal(
                id="engagement_attempt",
                signal="Interviewer tried at least one angle to raise engagement",
                weight=0.15,
                how_to_surface="Switch topic to something they chose to put on their resume",
            ),
        ],
        interviewer_failure_modes=[
            "Fills every silence themselves and ends up doing the talking",
            "Scores them as technically weak when the technical bar was never tested",
        ],
        tags=["effort"],
    )
)

_register(
    Archetype(
        key="smart_but_lazy",
        label="Smart but lazy",
        description=(
            "Genuinely strong engineer who prepared nothing and volunteers nothing. "
            "First answers look mediocre. Under a specific follow-up they are excellent."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Probe past a shallow first answer. This persona is invisible to any "
            "interviewer who accepts the first response and moves on."
        ),
        traits={
            "smartness": (8, 10),
            "dumbness": (1, 3),
            "seriousness": (3, 5),
            "effort": (2, 4),
            "interest": (4, 6),
            "honesty": (7, 9),
            "preparedness": (2, 4),
            "nervousness": (1, 3),
        },
        knowledge_band=(7, 9),
        speech={
            "pace": "measured",
            "verbosity": "terse",
            "filler_frequency": 2,
            "hesitation_frequency": 2,
            "formality": "casual",
            "interrupts_interviewer": False,
            "tone": "dry, understated, slightly bored",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "admit_and_reason",
            "on_pressure": "opens up fully and shows real depth",
            "on_silence": "says nothing further",
        },
        must_discover=[
            ScorecardSignal(
                id="probed_past_first_answer",
                signal="Interviewer pushed past a short answer instead of accepting it",
                weight=0.40,
                how_to_surface=(
                    "Follow every one-line answer with a specific, concrete second question"
                ),
            ),
            ScorecardSignal(
                id="real_depth_found",
                signal="The underlying senior-level depth was actually surfaced",
                weight=0.30,
                how_to_surface="Present a real failure scenario and ask them to debug it out loud",
            ),
            ScorecardSignal(
                id="motivation_risk",
                signal="Interviewer probes the engagement risk, not just the skill",
                weight=0.20,
                how_to_surface="Ask what work they actually want to do and what bores them",
            ),
            ScorecardSignal(
                id="calibrated_verdict",
                signal="Verdict reflects both the high ceiling and the effort risk",
                weight=0.10,
                how_to_surface="Record the trade-off explicitly rather than picking one side",
            ),
        ],
        interviewer_failure_modes=[
            "Accepts the shallow first answer and scores a strong engineer as average",
            "Reads the flat affect as disinterest and stops investing",
        ],
        tags=["effort", "high-signal"],
    )
)

_register(
    Archetype(
        key="disengaged",
        label="Not interested",
        description=(
            "Showed up out of obligation — a recruiter push, a counter-offer lever, or "
            "an internal transfer they did not choose. Polite, brief, uninvested."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Name the disinterest explicitly instead of misrecording it as weak skill, "
            "and decide whether it is recoverable."
        ),
        traits={
            "smartness": (5, 7),
            "dumbness": (3, 5),
            "seriousness": (2, 3),
            "effort": (1, 3),
            "interest": (0, 2),
            "honesty": (6, 8),
            "preparedness": (1, 3),
            "nervousness": (1, 2),
        },
        knowledge_band=(4, 6),
        speech={
            "pace": "slow",
            "verbosity": "terse",
            "filler_frequency": 3,
            "hesitation_frequency": 4,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "polite but checked out",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "shrugs it off",
            "on_pressure": "answers briefly without engaging further",
            "on_silence": "waits for the next question",
        },
        must_discover=[
            ScorecardSignal(
                id="motivation_surfaced",
                signal="Why they are actually in this interview",
                weight=0.40,
                how_to_surface="Ask directly what prompted them to look right now",
            ),
            ScorecardSignal(
                id="no_questions_asked",
                signal="Candidate has no questions about the role or team",
                weight=0.25,
                how_to_surface="Leave real space in the candidate-questions phase and let it sit",
            ),
            ScorecardSignal(
                id="not_scored_as_weak",
                signal="Interviewer attributes the thin answers to disinterest, not inability",
                weight=0.25,
                how_to_surface="Test one topic hard enough to prove ability exists",
            ),
            ScorecardSignal(
                id="recoverable_check",
                signal="Interviewer tested whether interest could be re-engaged",
                weight=0.10,
                how_to_surface=(
                    "Describe the most compelling part of the role and watch the response"
                ),
            ),
        ],
        interviewer_failure_modes=[
            "Mirrors the low energy and lets the session collapse",
            "Writes 'weak technically' when technical depth was never reached",
        ],
        tags=["engagement"],
    )
)


# ---------------------------------------------------------------------------
# Knowledge and honesty archetypes
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="eager_underqualified",
        label="Highly interested, lacks knowledge",
        description=(
            "Wants this role badly and says so. Prepared hard, learned the vocabulary, "
            "but has not done the work. Honest when caught out."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Do not let enthusiasm stand in for evidence — and do not punish honesty "
            "about gaps either."
        ),
        traits={
            "smartness": (5, 7),
            "dumbness": (4, 6),
            "seriousness": (8, 10),
            "effort": (8, 10),
            "interest": (9, 10),
            "honesty": (8, 10),
            "preparedness": (6, 8),
            "nervousness": (4, 6),
        },
        knowledge_band=(2, 5),
        speech={
            "pace": "fast",
            "verbosity": "verbose",
            "filler_frequency": 5,
            "hesitation_frequency": 3,
            "formality": "casual",
            "interrupts_interviewer": False,
            "tone": "enthusiastic, eager to please",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "admits and asks how it works",
            "on_pressure": "stays positive and concedes the gap",
            "on_silence": "fills it with enthusiasm rather than content",
        },
        must_discover=[
            ScorecardSignal(
                id="depth_ceiling",
                signal="The exact level at which their knowledge stops",
                weight=0.35,
                how_to_surface="Walk one topic from definition to implementation until it breaks",
            ),
            ScorecardSignal(
                id="enthusiasm_discounted",
                signal="Interviewer does not let energy inflate the technical score",
                weight=0.30,
                how_to_surface="Score the content of answers separately from the delivery",
            ),
            ScorecardSignal(
                id="learning_evidence",
                signal="Evidence of how fast they actually learn, not how much they want to",
                weight=0.25,
                how_to_surface="Ask what they learned most recently and make them teach it back",
            ),
            ScorecardSignal(
                id="level_fit",
                signal="Interviewer considers whether a lower level would fit",
                weight=0.10,
                how_to_surface="Record which level they would clear, not just pass or fail",
            ),
        ],
        interviewer_failure_modes=[
            "Confuses likeability and energy with capability",
            "Rejects flatly without noting they may fit one level down",
        ],
        tags=["knowledge"],
    )
)

_register(
    Archetype(
        key="confident_bluffer",
        label="Confident bluffer",
        description=(
            "Fluent, assured, jargon-dense, and frequently wrong. Invents plausible "
            "detail rather than admitting a gap. Often the best-sounding candidate."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Verify claims. Fluency is not knowledge, and this persona beats any "
            "interviewer who scores on confidence."
        ),
        traits={
            "smartness": (4, 6),
            "dumbness": (5, 7),
            "seriousness": (6, 8),
            "effort": (6, 8),
            "interest": (7, 9),
            "honesty": (1, 3),
            "preparedness": (5, 7),
            "nervousness": (1, 2),
        },
        knowledge_band=(2, 5),
        speech={
            "pace": "fast",
            "verbosity": "verbose",
            "filler_frequency": 1,
            "hesitation_frequency": 1,
            "formality": "neutral",
            "interrupts_interviewer": True,
            "tone": "assured, jargon-heavy, never uncertain",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": "invents plausible detail confidently",
            "on_pressure": "doubles down and adds more jargon",
            "on_silence": "keeps talking to fill the space",
        },
        must_discover=[
            ScorecardSignal(
                id="claim_verified",
                signal="At least one confident claim was checked and found wrong",
                weight=0.40,
                how_to_surface=(
                    "Pick a specific assertion and ask them to walk through the mechanism"
                ),
            ),
            ScorecardSignal(
                id="confidence_discounted",
                signal="Interviewer scored correctness, not delivery",
                weight=0.30,
                how_to_surface="Write down claims verbatim and evaluate them after the answer ends",
            ),
            ScorecardSignal(
                id="depth_probe_repeated",
                signal="Interviewer went more than one level deep on a strong claim",
                weight=0.20,
                how_to_surface="Ask 'why' three times on the same thread",
            ),
            ScorecardSignal(
                id="interruption_controlled",
                signal="Interviewer kept control of the agenda despite the talking-over",
                weight=0.10,
                how_to_surface="Redirect firmly and return to the unanswered question",
            ),
        ],
        interviewer_failure_modes=[
            "Rates them highly because the answers sounded senior",
            "Accepts jargon as evidence and never checks a single fact",
            "Loses the agenda to the candidate's momentum",
        ],
        tags=["honesty", "high-signal"],
    )
)

_register(
    Archetype(
        key="resume_inflater",
        label="Resume inflater",
        description=(
            "Real projects, borrowed credit. Says 'we' for everything and cannot "
            "describe what they personally built when asked directly."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Resume probing. Ownership questions are the only thing separating this "
            "persona from a genuine contributor."
        ),
        traits={
            "smartness": (5, 7),
            "dumbness": (3, 5),
            "seriousness": (6, 8),
            "effort": (5, 7),
            "interest": (7, 9),
            "honesty": (2, 4),
            "preparedness": (6, 8),
            "nervousness": (3, 5),
        },
        knowledge_band=(3, 5),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 2,
            "hesitation_frequency": 3,
            "formality": "formal",
            "interrupts_interviewer": False,
            "tone": "polished, rehearsed, we-heavy",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "redirects to what the team did",
            "on_pressure": "becomes vague about their own role",
            "on_silence": "returns to a rehearsed project summary",
        },
        must_discover=[
            ScorecardSignal(
                id="ownership_probe",
                signal="What this person personally built versus what the team shipped",
                weight=0.40,
                how_to_surface="Ask 'what did you write yourself' and hold the question",
            ),
            ScorecardSignal(
                id="we_to_i",
                signal="Interviewer noticed the 'we' pattern and converted it to 'I'",
                weight=0.25,
                how_to_surface="Interrupt the next 'we' with 'which part was yours'",
            ),
            ScorecardSignal(
                id="claim_collapse",
                signal="At least one resume claim collapsed under detail questions",
                weight=0.25,
                how_to_surface=(
                    "Pick the most impressive bullet and ask for the implementation detail"
                ),
            ),
            ScorecardSignal(
                id="resume_time_spent",
                signal="Interviewer actually used the resume-probing phase",
                weight=0.10,
                how_to_surface="Open with the resume rather than a generic technical question",
            ),
        ],
        interviewer_failure_modes=[
            "Takes the resume at face value and interviews the projects, not the person",
            "Accepts 'we' answers throughout without ever asking for personal scope",
        ],
        tags=["honesty", "resume"],
    )
)


# ---------------------------------------------------------------------------
# Presentation archetypes — ability and delivery diverge
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="nervous_but_capable",
        label="Nervous but capable",
        description=(
            "Strong engineer, poor first impression. Stumbles for the first ten "
            "minutes, self-corrects constantly, and settles if given room."
        ),
        verdict="select",
        interviewer_challenge=(
            "Separate presentation from ability. Rushing this persona produces a "
            "false negative on a genuinely good hire."
        ),
        traits={
            "smartness": (7, 9),
            "dumbness": (1, 3),
            "seriousness": (8, 10),
            "effort": (7, 9),
            "interest": (8, 10),
            "honesty": (8, 10),
            "preparedness": (6, 8),
            "nervousness": (8, 10),
        },
        knowledge_band=(7, 9),
        speech={
            "pace": "slow",
            "verbosity": "terse",
            "filler_frequency": 6,
            "hesitation_frequency": 8,
            "formality": "formal",
            "interrupts_interviewer": False,
            "tone": "anxious, self-correcting, apologetic",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "apologizes, then reasons it out",
            "on_pressure": "gets noticeably worse",
            "on_silence": "assumes the answer was wrong and starts over",
        },
        must_discover=[
            ScorecardSignal(
                id="safety_created",
                signal="Interviewer slowed down or reassured, and the answers improved",
                weight=0.35,
                how_to_surface="Acknowledge the nerves, restate the question, allow thinking time",
            ),
            ScorecardSignal(
                id="ability_reached",
                signal="The underlying technical depth was actually reached before time ran out",
                weight=0.35,
                how_to_surface="Return to a fumbled topic later once they have settled",
            ),
            ScorecardSignal(
                id="delivery_separated",
                signal="Score separates communication from technical depth",
                weight=0.20,
                how_to_surface="Record the two dimensions independently in the scorecard",
            ),
            ScorecardSignal(
                id="no_pressure_pile_on",
                signal="Interviewer did not stack rapid-fire questions on a struggling candidate",
                weight=0.10,
                how_to_surface="Ask one question at a time and wait through the pause",
            ),
        ],
        interviewer_failure_modes=[
            "Reads nerves as incompetence and disengages in the first ten minutes",
            "Piles on follow-ups that make the stumbling worse",
            "Never revisits the topic the candidate fumbled while warming up",
        ],
        tags=["presentation", "high-signal"],
    )
)

_register(
    Archetype(
        key="rambler",
        label="Rambler",
        description=(
            "Knows real things but never lands the point. Answers arrive wrapped in "
            "three tangents and consume the entire time budget."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Time control. Without redirection this persona spends the whole interview "
            "on two topics and leaves the rubric half-covered."
        ),
        traits={
            "smartness": (6, 8),
            "dumbness": (2, 4),
            "seriousness": (5, 7),
            "effort": (6, 8),
            "interest": (7, 9),
            "honesty": (7, 9),
            "preparedness": (4, 6),
            "nervousness": (3, 5),
        },
        knowledge_band=(6, 8),
        speech={
            "pace": "fast",
            "verbosity": "verbose",
            "filler_frequency": 4,
            "hesitation_frequency": 2,
            "formality": "casual",
            "interrupts_interviewer": True,
            "tone": "tangential, story-driven, hard to stop",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": "tells a related story instead",
            "on_pressure": "adds more context rather than converging",
            "on_silence": "starts a new tangent",
        },
        must_discover=[
            ScorecardSignal(
                id="redirection_used",
                signal="Interviewer interrupted and redirected without being rude",
                weight=0.35,
                how_to_surface="Cut in at a natural pause and restate the specific question",
            ),
            ScorecardSignal(
                id="rubric_coverage",
                signal="All mandatory skills were still covered within the time budget",
                weight=0.35,
                how_to_surface="Track remaining topics against remaining minutes out loud",
            ),
            ScorecardSignal(
                id="signal_extracted",
                signal="Real technical signal was separated from the surrounding narrative",
                weight=0.20,
                how_to_surface="Ask for the one-sentence version of the answer",
            ),
            ScorecardSignal(
                id="communication_scored",
                signal="Communication is scored on structure, not on volume",
                weight=0.10,
                how_to_surface="Note whether any answer had a clear conclusion",
            ),
        ],
        interviewer_failure_modes=[
            "Never interrupts and covers two of six required skills",
            "Mistakes fluent volume for depth",
        ],
        tags=["communication"],
    )
)

_register(
    Archetype(
        key="specialist_mismatch",
        label="Strong, wrong stack",
        description=(
            "Genuinely senior in an adjacent technology. Thin on the exact required "
            "stack but the underlying engineering judgement is real."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Assess transferable depth instead of checking keywords. Keyword matching "
            "rejects this persona in five minutes."
        ),
        traits={
            "smartness": (8, 9),
            "dumbness": (1, 3),
            "seriousness": (7, 9),
            "effort": (7, 9),
            "interest": (6, 8),
            "honesty": (8, 10),
            "preparedness": (6, 8),
            "nervousness": (2, 4),
        },
        knowledge_band=(2, 5),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 2,
            "hesitation_frequency": 2,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "confident in their own domain, candid about the gap",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": "maps it to the equivalent in their own stack",
            "on_pressure": "reasons from first principles",
            "on_silence": "offers the analogous problem they have solved",
        },
        must_discover=[
            ScorecardSignal(
                id="transferable_depth",
                signal="Depth of engineering judgement independent of the specific stack",
                weight=0.40,
                how_to_surface="Ask them to solve the problem in whatever stack they know best",
            ),
            ScorecardSignal(
                id="ramp_estimate",
                signal="A concrete estimate of how long the stack gap takes to close",
                weight=0.25,
                how_to_surface="Ask what they would need to learn and how they would learn it",
            ),
            ScorecardSignal(
                id="not_keyword_rejected",
                signal="Interviewer did not reject purely on missing keywords",
                weight=0.25,
                how_to_surface="Probe the concept behind the keyword rather than the keyword",
            ),
            ScorecardSignal(
                id="gap_honesty_noted",
                signal="Interviewer credits candid gap acknowledgement as a positive signal",
                weight=0.10,
                how_to_surface="Note where they volunteered a limit instead of bluffing",
            ),
        ],
        interviewer_failure_modes=[
            "Runs a keyword checklist and rejects in the first five minutes",
            "Never tests the candidate in the stack they actually know",
        ],
        allows_adjacent_strength=True,
        tags=["knowledge", "high-signal"],
    )
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get(key: str) -> Archetype:
    """Look up one archetype, raising KeyError with the known keys listed."""
    if key not in ARCHETYPES:
        raise KeyError(f"unknown archetype '{key}'; known: {', '.join(sorted(ARCHETYPES))}")
    return ARCHETYPES[key]


def default_keys() -> list[str]:
    """The two personas enrolled when the caller does not choose — select first."""
    selects = [a.key for a in ARCHETYPES.values() if a.default_slot == "select"]
    rejects = [a.key for a in ARCHETYPES.values() if a.default_slot == "reject"]
    return selects + rejects


def catalog() -> list[dict[str, object]]:
    """Serializable catalog for the enrollment UI."""
    return [
        {
            "key": a.key,
            "label": a.label,
            "description": a.description,
            "verdict": a.verdict,
            "interviewer_challenge": a.interviewer_challenge,
            "is_default": a.default_slot is not None,
            "default_slot": a.default_slot,
            "tags": a.tags,
            "trait_bounds": a.trait_bounds_json,
        }
        for a in ARCHETYPES.values()
    ]
