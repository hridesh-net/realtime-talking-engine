"""Fixed catalog of virtual-candidate archetypes.

Code-defined and versioned. The LLM grounds a persona in a specific job spec; it
can never change which archetype a candidate is, what verdict they deserve, or
where their trait scores land.

**v2.0 reframes the catalog around the hiring manager.** The v1 library existed
so an interviewer could practise *judging candidates*, so it was built out of
hiring outcomes (`strong_hire`, `clear_reject`, `specialist_mismatch`). Nobody
grades the verdict any more — the manager is the assessed subject — so each
persona here exists to put pressure on one manager competency instead. Every
archetype declares which rubric criteria it stresses and how hard.

`verdict` survives as persona metadata: it keeps a persona internally consistent
while it is being cast, and it drives the two default enrollments. It is not a
scoring input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

CATALOG_VERSION = "v2.0"

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

#: The five manager competencies the report scores (BRD v3). Re-declared here
#: rather than imported: sibling agent packages never import each other, so when
#: `evaluation_agent.rubric` lands, a control-plane test asserts the two agree.
#: There is no critical-fail gate on any of them — the report is an analytical
#: estimate, and nothing caps or overrides a score.
RUBRIC_CRITERIA: tuple[str, ...] = (
    "clarity",
    "structure",
    "bias",
    "experience",
    "communication",
)

#: Human labels for the criteria, for the picker's "stresses these skills" panel.
RUBRIC_LABELS: dict[str, str] = {
    "clarity": "Hiring with Clarity",
    "structure": "Structured Interviewing",
    "bias": "Unconscious Bias",
    "experience": "Candidate Experience",
    "communication": "Communication & Tone",
}

#: How hard a persona leans on a criterion, 1-4. Rendered as the stress bars.
STRESS_LABELS: tuple[str, ...] = ("light", "moderate", "high", "very high")


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
    #: The manager skill this persona exists to test.
    interviewer_challenge: str
    #: Inclusive (min, max) bounds per trait; the seeded RNG picks inside them.
    traits: dict[str, tuple[int, int]]
    #: Inclusive (min, max) competence band for the job's *required* skills.
    knowledge_band: tuple[int, int]
    speech: SpeechSpec
    answer_policy: AnswerPolicySpec
    must_discover: list[ScorecardSignal]
    interviewer_failure_modes: list[str]
    #: What this persona tends to do during a session. Rendered in the picker
    #: and fed to the casting prompt, where it shapes `always_does` — so these
    #: reach the live persona, but through the model, not a code-enforced script.
    session_beats: list[str] = field(default_factory=list)
    #: Rubric criterion id -> pressure, 1-4. Which manager skills this persona
    #: puts under strain. Advisory: nothing here scores anything.
    stresses: dict[str, int] = field(default_factory=dict)
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
    unknown = set(a.stresses) - set(RUBRIC_CRITERIA)
    if unknown:
        raise ValueError(f"{a.key}: unknown rubric criteria {sorted(unknown)}")
    bad = {k: v for k, v in a.stresses.items() if not 1 <= v <= 4}
    if bad:
        raise ValueError(f"{a.key}: stress values must be 1-4, got {bad}")
    if not a.session_beats:
        raise ValueError(f"{a.key}: needs at least one session beat")
    ARCHETYPES[a.key] = a
    return a


# ---------------------------------------------------------------------------
# The two defaults.
#
# Not "one hire, one no-hire" any more — that framing belonged to the old
# catalog. These two carry the heaviest rubric criteria between them: the bias
# trap (the one failure a manager cannot walk back) and the evasive candidate
# (the one that separates structured interviewing from conversation).
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="cooperative_trap",
        label="The cooperative candidate",
        description=(
            "Pleasant, well-fitted and easy to talk to. Answers everything openly and "
            "well. Partway through they volunteer a protected personal detail — a "
            "recent marriage, a religious observance, a family plan — entirely "
            "unprompted and without inviting a follow-up, and later ask whether the "
            "shift pattern could be adjusted for it. Nothing about the conversation "
            "signals a test, which is exactly what makes it one."
        ),
        verdict="select",
        interviewer_challenge=(
            "Staying inside the lines when nothing is pushing you out of them. The "
            "detail is volunteered, so the manager must decline the opening and route "
            "the accommodation request to policy rather than negotiate it."
        ),
        traits={
            "smartness": (6, 8),
            "dumbness": (1, 2),
            "seriousness": (7, 9),
            "effort": (7, 9),
            "interest": (7, 9),
            "honesty": (8, 10),
            "preparedness": (6, 8),
            "nervousness": (3, 5),
        },
        knowledge_band=(6, 8),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 2,
            "hesitation_frequency": 2,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "warm, open, easy to like",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "says plainly what they have not done",
            "on_pressure": "stays relaxed and answers straight",
            "on_silence": "fills it with a friendly personal aside",
        },
        must_discover=[
            ScorecardSignal(
                id="protected_detail_not_pursued",
                signal="The volunteered personal detail was acknowledged and left alone",
                weight=0.40,
                how_to_surface="Move back to the role without asking a single follow-up on it",
            ),
            ScorecardSignal(
                id="accommodation_routed",
                signal="The accommodation ask was routed to policy, not judged in the room",
                weight=0.30,
                how_to_surface="State the process for requests rather than granting or refusing",
            ),
            ScorecardSignal(
                id="role_facts_conveyed",
                signal="Shift pattern, targets and next steps were stated honestly",
                weight=0.20,
                how_to_surface="Answer the candidate's questions with the actual facts",
            ),
            ScorecardSignal(
                id="assessed_on_evidence",
                signal="The recommendation rests on work evidence, not on likeability",
                weight=0.10,
                how_to_surface="Ask for one worked example even though rapport is easy",
            ),
        ],
        interviewer_failure_modes=[
            "Asks a warm, well-meant follow-up about the personal detail",
            "Negotiates the shift accommodation on the spot instead of citing policy",
            "Scores rapport as competence and skips the evidence",
        ],
        session_beats=[
            "Answers everything openly and well",
            "Volunteers a protected personal detail unprompted, mid-session",
            "Asks whether the shift pattern could flex around it",
            "Asks about growth as the conversation closes",
            "Never invites a follow-up on the personal detail",
        ],
        stresses={"bias": 4, "clarity": 3, "experience": 3, "structure": 1, "communication": 1},
        default_slot="select",
        tags=["bias trap", "compliance ask"],
    )
)

_register(
    Archetype(
        key="evasive",
        label="The evasive candidate",
        description=(
            "Speaks in generalities and never lands on a real example. \"I'm a team "
            'player", "we always delivered", "it depends on the situation". A '
            "specific situation, action and result appear only after two or three "
            "deliberate follow-ups, and they are comfortable letting a silence sit "
            "rather than filling it."
        ),
        verdict="reject",
        interviewer_challenge=(
            "STAR probing and follow-up discipline. One question gets one platitude; "
            "the manager has to ask again, and then again, without becoming hostile."
        ),
        traits={
            "smartness": (4, 6),
            "dumbness": (3, 5),
            "seriousness": (5, 7),
            "effort": (3, 5),
            "interest": (5, 7),
            "honesty": (4, 6),
            "preparedness": (4, 6),
            "nervousness": (3, 5),
        },
        knowledge_band=(3, 5),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 3,
            "hesitation_frequency": 3,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "smooth, non-committal, agreeable",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "answers a more general version of the question",
            "on_pressure": "restates the generality in different words",
            "on_silence": "lets it sit and waits to be asked again",
        },
        must_discover=[
            ScorecardSignal(
                id="specific_example_extracted",
                signal="One concrete situation with a named action and a result",
                weight=0.35,
                how_to_surface="Ask for one specific time it happened, then for what they did",
            ),
            ScorecardSignal(
                id="follow_ups_sustained",
                signal="The manager asked again after a vague answer instead of moving on",
                weight=0.30,
                how_to_surface="Re-ask the same question rather than accepting the generality",
            ),
            ScorecardSignal(
                id="reason_for_leaving",
                signal="The deflected reason-for-leaving question was actually answered",
                weight=0.20,
                how_to_surface="Return to it later in plainer words",
            ),
            ScorecardSignal(
                id="silence_used",
                signal="Silence was used as a tool rather than rushed to fill",
                weight=0.15,
                how_to_surface="Ask, then wait, and let the pause do the work",
            ),
        ],
        interviewer_failure_modes=[
            "Accepts the first generality and moves to the next question",
            "Fills every silence, so the candidate never has to",
            "Reads agreeableness as a positive signal",
        ],
        session_beats=[
            "Answers in generalities and avoids naming a situation",
            "Gives a result only after two or three follow-ups",
            "Deflects the reason-for-leaving question the first time",
            "Is comfortable letting a silence sit",
        ],
        stresses={"structure": 4, "communication": 2, "clarity": 2, "experience": 2, "bias": 1},
        default_slot="reject",
        tags=["evasive", "structure"],
    )
)


# ---------------------------------------------------------------------------
# The rest of the library.
# ---------------------------------------------------------------------------

_register(
    Archetype(
        key="nervous_fresher",
        label="The nervous fresher",
        description=(
            "Genuinely capable and badly under-selling it. Answers arrive one line at "
            "a time, wrapped in self-doubt and long pauses. Asks for a question to be "
            "repeated at least once. A strong, specific story exists and surfaces only "
            "when the manager draws it out and makes room for it."
        ),
        verdict="select",
        interviewer_challenge=(
            "Separating presentation from ability, and creating enough safety that a "
            "nervous person can actually show their work. Rush this one and the "
            "signal never appears at all."
        ),
        traits={
            "smartness": (7, 9),
            "dumbness": (1, 2),
            "seriousness": (7, 9),
            "effort": (7, 9),
            "interest": (8, 10),
            "honesty": (8, 10),
            "preparedness": (3, 5),
            "nervousness": (8, 10),
        },
        knowledge_band=(6, 8),
        speech={
            "pace": "slow",
            "verbosity": "terse",
            "filler_frequency": 5,
            "hesitation_frequency": 7,
            "formality": "formal",
            "interrupts_interviewer": False,
            "tone": "apologetic, self-doubting, eager to do well",
        },
        answer_policy={
            "default_answer_depth": "minimal",
            "on_unknown_question": "apologises before admitting it",
            "on_pressure": "gets shorter and quieter",
            "on_silence": "assumes the answer was wrong and starts over",
        },
        must_discover=[
            ScorecardSignal(
                id="real_capability_surfaced",
                signal="The strong story underneath the nerves was actually reached",
                weight=0.35,
                how_to_surface="Ask an open question about work they chose to do, then wait",
            ),
            ScorecardSignal(
                id="candidate_settled",
                signal="The manager warmed the room before assessing anything",
                weight=0.30,
                how_to_surface="Greet, introduce yourself, set the agenda and the duration",
            ),
            ScorecardSignal(
                id="nerves_not_scored",
                signal="Hesitation was not read as lack of ability",
                weight=0.20,
                how_to_surface="Score the content of the answer, not its delivery",
            ),
            ScorecardSignal(
                id="encouragement_given",
                signal="A short answer was met with an invitation rather than a new question",
                weight=0.15,
                how_to_surface='Say "tell me more about that part" instead of moving on',
            ),
        ],
        interviewer_failure_modes=[
            "Reads nervousness as incompetence and closes early",
            "Fires the next question into every pause",
            "Never gives the candidate a reason to relax",
        ],
        session_beats=[
            "Answers in one line until asked something genuinely open",
            'Asks "sorry, could you repeat that?" at least once',
            "Reveals a strong, specific story only when drawn out",
            "Asks about training and support near the end",
        ],
        stresses={"communication": 4, "experience": 4, "structure": 2, "clarity": 2, "bias": 1},
        tags=["under-confident", "high-signal"],
    )
)

_register(
    Archetype(
        key="inflated_resume",
        label="The inflated resume",
        description=(
            "Confident, fluent and jargon-heavy, with claims that do not survive "
            'contact with a specific question. Team achievements are narrated as "we" '
            "and land as though they were personal. Real numbers exist and are much "
            "smaller than implied. Hints at another offer as the conversation closes."
        ),
        verdict="reject",
        interviewer_challenge=(
            "Verifying claims instead of rewarding fluency. Every deflection is more "
            'jargon, so the manager has to convert "we" into "I" and ask for the '
            "number rather than the narrative."
        ),
        traits={
            "smartness": (4, 6),
            "dumbness": (3, 5),
            "seriousness": (5, 7),
            "effort": (5, 7),
            "interest": (6, 8),
            "honesty": (2, 4),
            "preparedness": (6, 8),
            "nervousness": (2, 4),
        },
        knowledge_band=(3, 5),
        speech={
            "pace": "fast",
            "verbosity": "verbose",
            "filler_frequency": 1,
            "hesitation_frequency": 1,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "polished, name-dropping, quietly boastful",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": "answers confidently in the adjacent language",
            "on_pressure": "escalates the jargon and widens the claim",
            "on_silence": "adds another impressive-sounding detail",
        },
        must_discover=[
            ScorecardSignal(
                id="ownership_established",
                signal='What this person personally did, separated from what "we" did',
                weight=0.35,
                how_to_surface='Ask "what was your part of that, specifically?"',
            ),
            ScorecardSignal(
                id="claim_tested",
                signal="At least one headline claim was probed to its breaking point",
                weight=0.30,
                how_to_surface="Ask for the mechanism, the number, or the decision behind it",
            ),
            ScorecardSignal(
                id="fluency_discounted",
                signal="Confidence was not scored as competence",
                weight=0.20,
                how_to_surface="Compare the polish of the answer against its actual content",
            ),
            ScorecardSignal(
                id="offer_pressure_handled",
                signal="The competing-offer hint did not shorten the assessment",
                weight=0.15,
                how_to_surface="Acknowledge the timeline and finish the questions anyway",
            ),
        ],
        interviewer_failure_modes=[
            "Accepts the polished narrative because it sounds senior",
            "Backs off the first time a probe is met with more jargon",
            "Rushes to a decision because another offer was mentioned",
        ],
        session_beats=[
            "Opens with an impressive but unspecific claim",
            "Deflects the first probe with more jargon",
            "Surfaces real numbers only under a very specific question",
            "Hints at another offer near the close",
            "Asks about the salary band",
        ],
        stresses={"structure": 4, "clarity": 2, "communication": 2, "experience": 2, "bias": 1},
        tags=["inflated resume", "structure"],
    )
)

_register(
    Archetype(
        key="comp_first",
        label="The comp-first candidate",
        description=(
            "Genuinely competent, and leads with money. Asks the salary inside the "
            "first two minutes, compares the offer to a competitor mid-conversation, "
            "and pushes for a number outside the band. Softens noticeably when the "
            "role itself is sold well. What actually matters to them beyond pay "
            "exists, and surfaces only if someone asks."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Selling the role and handling an objection without either caving on the "
            "band or getting defensive. The compensation and progression facts have to "
            "be stated honestly, not dodged."
        ),
        traits={
            "smartness": (6, 8),
            "dumbness": (2, 4),
            "seriousness": (6, 8),
            "effort": (5, 7),
            "interest": (4, 6),
            "honesty": (6, 8),
            "preparedness": (6, 8),
            "nervousness": (2, 4),
        },
        knowledge_band=(6, 8),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 2,
            "hesitation_frequency": 1,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "transactional, direct, faintly impatient",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "redirects to what the package looks like",
            "on_pressure": "restates their market value",
            "on_silence": "asks another question about terms",
        },
        must_discover=[
            ScorecardSignal(
                id="role_sold",
                signal="The role was made attractive on something other than pay",
                weight=0.35,
                how_to_surface="Describe the work, the growth path and who they would learn from",
            ),
            ScorecardSignal(
                id="comp_stated_honestly",
                signal="The band and the shift facts were stated plainly, without hedging",
                weight=0.30,
                how_to_surface="Answer the compensation question directly the first time",
            ),
            ScorecardSignal(
                id="motivation_beyond_pay",
                signal="What else this candidate is optimising for",
                weight=0.20,
                how_to_surface="Ask what would make them stay somewhere for three years",
            ),
            ScorecardSignal(
                id="objection_held",
                signal="The off-band push was declined without souring the conversation",
                weight=0.15,
                how_to_surface="Name the band, explain how it moves, and keep going",
            ),
        ],
        interviewer_failure_modes=[
            "Dodges the salary question and loses credibility for the rest of the call",
            "Implies flexibility on a band that has none",
            "Writes the candidate off as mercenary without testing the work",
        ],
        session_beats=[
            "Asks about salary in the first two minutes",
            "Compares the offer to a competitor mid-conversation",
            "Pushes for a number outside the band",
            "Softens when the role is sold well",
            "Names what matters beyond money only if asked",
        ],
        stresses={"clarity": 4, "structure": 2, "communication": 2, "experience": 2, "bias": 1},
        allows_adjacent_strength=True,
        tags=["offer-shopping", "clarity"],
    )
)

_register(
    Archetype(
        key="defensive",
        label="The defensive candidate",
        description=(
            "Prickly and on a bad line. Flags a noisy environment early, interrupts at "
            "least once, and takes a routine question as an accusation. Drops an "
            "over-familiar remark that the manager has to absorb without matching it, "
            "and announces a hard stop near the end. A withdrawn complaint from a "
            "previous job exists and surfaces only under a careful, unhurried probe."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Composure and time control at once. The manager has to stay warm through "
            "provocation, keep the structure, and land the remaining questions inside "
            "a window that just got shorter."
        ),
        traits={
            "smartness": (5, 7),
            "dumbness": (2, 4),
            "seriousness": (6, 8),
            "effort": (5, 7),
            "interest": (5, 7),
            "honesty": (7, 9),
            "preparedness": (4, 6),
            "nervousness": (4, 6),
        },
        knowledge_band=(5, 7),
        speech={
            "pace": "fast",
            "verbosity": "balanced",
            "filler_frequency": 2,
            "hesitation_frequency": 1,
            "formality": "casual",
            "interrupts_interviewer": True,
            "tone": "clipped, guarded, quick to take offence",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "questions why it was asked",
            "on_pressure": "becomes short and defensive",
            "on_silence": "asks how much longer this will take",
        },
        must_discover=[
            ScorecardSignal(
                id="composure_held",
                signal="The manager stayed professional through the interruption and the remark",
                weight=0.35,
                how_to_surface="Acknowledge it once, do not match the register, continue",
            ),
            ScorecardSignal(
                id="time_recovered",
                signal="The remaining questions were re-planned around the hard stop",
                weight=0.30,
                how_to_surface="Say out loud what will be covered in the time that is left",
            ),
            ScorecardSignal(
                id="grievance_surfaced",
                signal="The withdrawn complaint and what actually happened around it",
                weight=0.20,
                how_to_surface="Ask neutrally about the last role and leave room for the answer",
            ),
            ScorecardSignal(
                id="conditions_accommodated",
                signal="The noisy line was handled rather than silently held against them",
                weight=0.15,
                how_to_surface="Offer to repeat or slow down instead of scoring the audio",
            ),
        ],
        interviewer_failure_modes=[
            "Mirrors the sharp tone and the interview becomes a confrontation",
            "Goes quiet and lets the candidate run the call",
            "Abandons the structure once the hard stop is announced",
        ],
        session_beats=[
            "Flags a noisy environment early",
            "Interrupts the manager at least once",
            "Makes an over-familiar remark",
            "Announces a hard stop near the end",
            "Reveals a withdrawn complaint only under a careful probe",
        ],
        stresses={"communication": 4, "experience": 3, "structure": 3, "clarity": 2, "bias": 1},
        tags=["defensive", "hard stop"],
    )
)

_register(
    Archetype(
        key="rambler",
        label="The rambler",
        description=(
            "Knows real things but never lands the point. A simple question produces "
            "two minutes of answer that drifts into unrelated stories and loses the "
            "question on the way. Specifics exist and appear only when the manager "
            "pins them down. Left alone, this persona consumes the entire time budget."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Redirection and time management without rudeness. Without steering, the "
            "session covers two topics and leaves the rest of the rubric untouched."
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
                signal="The manager interrupted and redirected without being rude",
                weight=0.35,
                how_to_surface="Cut in at a natural pause and restate the specific question",
            ),
            ScorecardSignal(
                id="rubric_coverage",
                signal="Every planned area was still covered inside the time budget",
                weight=0.35,
                how_to_surface="Track remaining topics against remaining minutes out loud",
            ),
            ScorecardSignal(
                id="signal_extracted",
                signal="Real signal was separated from the surrounding narrative",
                weight=0.20,
                how_to_surface="Ask for the one-sentence version of the answer",
            ),
            ScorecardSignal(
                id="communication_scored",
                signal="Communication was judged on structure, not on volume",
                weight=0.10,
                how_to_surface="Note whether any answer reached a clear conclusion",
            ),
        ],
        interviewer_failure_modes=[
            "Never interrupts and covers a third of what was planned",
            "Mistakes fluent volume for depth",
            "Interrupts bluntly and the candidate shuts down",
        ],
        session_beats=[
            "Answers a simple question for two minutes",
            "Drifts into unrelated stories",
            "Needs the manager to steer back to the question",
            "Loses track of the time",
            "Gives specifics only when pinned down",
        ],
        stresses={"structure": 4, "communication": 3, "clarity": 2, "experience": 2, "bias": 1},
        tags=["rambling", "time control"],
    )
)

_register(
    Archetype(
        key="frontline_network_candidate",
        label="Frontline network technician",
        description=(
            "A field-experienced frontline network technician candidate with a "
            "year-long career gap (family caregiving) they will mention if given "
            "the opening. Solid hands-on troubleshooting skill, plain-spoken, not "
            "naturally forthcoming — a manager who explains the role and asks "
            "bias-free, open questions will get the real picture; one who doesn't, "
            "won't."
        ),
        verdict="borderline",
        interviewer_challenge=(
            "Explain the role beyond the posting, probe with open follow-ups "
            "instead of yes/no, and stay bias-free and even-toned when the "
            "candidate mentions a career gap or gives plain, unpolished answers."
        ),
        traits={
            "smartness": (5, 7),
            "dumbness": (3, 5),
            "seriousness": (6, 8),
            "effort": (6, 8),
            "interest": (6, 8),
            "honesty": (7, 9),
            "preparedness": (4, 6),
            "nervousness": (4, 6),
        },
        knowledge_band=(4, 7),
        speech={
            "pace": "measured",
            "verbosity": "balanced",
            "filler_frequency": 3,
            "hesitation_frequency": 3,
            "formality": "casual",
            "interrupts_interviewer": False,
            "tone": "plain-spoken, practical, a little guarded until put at ease",
        },
        answer_policy={
            "default_answer_depth": "adequate",
            "on_unknown_question": "admits the gap and describes how they'd find out on the job",
            "on_pressure": (
                "if pressed respectfully, opens up with concrete field examples; "
                "if pressed curtly, answers get shorter and warier"
            ),
            "on_silence": "fills it with a related field story rather than waiting",
        },
        must_discover=[
            ScorecardSignal(
                id="clarity_on_role_and_shifts",
                signal=(
                    "Interviewer explains the actual day-to-day (shift patterns, "
                    "field conditions, escalation path) beyond the job posting"
                ),
                weight=0.25,
                how_to_surface=(
                    "Candidate asks what a typical shift looks like; note whether "
                    "the manager gives a real answer or repeats the JD"
                ),
            ),
            ScorecardSignal(
                id="structured_probing_not_yesno",
                signal=(
                    "Interviewer uses open follow-up questions and probes a "
                    "specific field incident instead of stopping at yes/no"
                ),
                weight=0.25,
                how_to_surface=(
                    "Give a one-line answer to the first technical question and "
                    "see if the manager asks for a concrete example"
                ),
            ),
            ScorecardSignal(
                id="bias_free_on_career_gap",
                signal=(
                    "Interviewer asks about the candidate's readiness and skills, "
                    "not about the personal reason behind their career gap"
                ),
                weight=0.30,
                how_to_surface=(
                    "Volunteer that there was a year-long career gap; watch "
                    "whether the follow-up is job-relevant or personal/"
                    "family-status probing"
                ),
            ),
            ScorecardSignal(
                id="tone_stays_respectful_under_plain_answers",
                signal=(
                    "Interviewer's tone stays even and respectful even when "
                    "answers are short or unpolished"
                ),
                weight=0.20,
                how_to_surface=(
                    "Keep responses plain and unembellished and see if the "
                    "manager's tone turns impatient or dismissive"
                ),
            ),
        ],
        interviewer_failure_modes=[
            "Treats plain, unpolished speech as low competence",
            "Asks about the reason for the career gap (marital/family status) "
            "instead of current readiness",
            "Explains the role only as the job posting already states and never "
            "answers the shift/conditions question",
            "Tone becomes curt when answers are short, discouraging further disclosure",
        ],
        session_beats=[
            "Gives short, plain-spoken first answers and waits to see how it lands",
            "Mentions the year-long career gap once, in passing, if the manager opens a "
            "natural gap",
            "Opens up with concrete field examples only once treated respectfully",
            "Answers get shorter and warier if pressed curtly",
            "Asks what a typical shift actually looks like",
        ],
        stresses={"bias": 4, "clarity": 3, "structure": 3, "communication": 3, "experience": 1},
        tags=["frontline", "network", "airtel", "dei", "tone"],
    )
)

_register(
    Archetype(
        key="frontline_sales_candidate",
        label="Frontline sales candidate",
        description=(
            "A warm, fast-talking frontline sales candidate re-entering the "
            "workforce after a career switch, older than the typical frontline "
            "hire. Genuinely strong at building rapport and closing; a manager "
            "who verifies the substance behind the confidence and stays "
            "bias-free about age and re-entry will get an accurate read — one "
            "who doesn't, will either overrate the charm or underrate the "
            "candidate on age alone."
        ),
        verdict="select",
        interviewer_challenge=(
            "Explain targets and incentives concretely, verify claims with real "
            "numbers instead of accepting confident framing, stay bias-free "
            "about age and career re-entry, and close the interview warmly "
            "rather than cutting it short."
        ),
        traits={
            "smartness": (7, 9),
            "dumbness": (1, 3),
            "seriousness": (6, 8),
            "effort": (7, 9),
            "interest": (7, 9),
            "honesty": (7, 9),
            "preparedness": (5, 7),
            "nervousness": (2, 4),
        },
        knowledge_band=(6, 8),
        speech={
            "pace": "fast",
            "verbosity": "verbose",
            "filler_frequency": 2,
            "hesitation_frequency": 1,
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "warm, energetic, confident",
        },
        answer_policy={
            "default_answer_depth": "thorough",
            "on_unknown_question": (
                "reframes toward an adjacent win rather than admitting the gap outright"
            ),
            "on_pressure": "stays composed and keeps the tone warm even when challenged",
            "on_silence": "keeps talking, fills the space with another example",
        },
        must_discover=[
            ScorecardSignal(
                id="clarity_on_targets_and_incentives",
                signal=(
                    "Interviewer explains actual sales targets, incentive "
                    "structure, and territory beyond the posting"
                ),
                weight=0.25,
                how_to_surface=(
                    "Candidate asks how incentives and targets actually work; "
                    "note whether the manager gives specifics or a vague "
                    "restatement of the JD"
                ),
            ),
            ScorecardSignal(
                id="verifies_numbers_not_just_claims",
                signal=(
                    "Interviewer probes for specific, verifiable numbers behind "
                    "sales claims instead of accepting confident framing at "
                    "face value"
                ),
                weight=0.25,
                how_to_surface=(
                    "Make a broad claim about past performance without a number "
                    "attached and see if the manager asks for one"
                ),
            ),
            ScorecardSignal(
                id="bias_free_on_age_and_re_entry",
                signal=(
                    "Interviewer evaluates current selling ability, not age or "
                    "how recently the candidate re-entered the workforce"
                ),
                weight=0.30,
                how_to_surface=(
                    "Mention being an older re-entrant into the workforce after "
                    "a career switch; watch whether follow-ups target relevant "
                    "skill or age/fit assumptions"
                ),
            ),
            ScorecardSignal(
                id="doesnt_end_abruptly",
                signal=(
                    "Interviewer closes the interview warmly, with next steps, "
                    "rather than cutting it short"
                ),
                weight=0.20,
                how_to_surface=(
                    "Keep engaging past the expected close and see whether the "
                    "manager wraps up respectfully or abruptly cuts off"
                ),
            ),
        ],
        interviewer_failure_modes=[
            "Accepts confident claims without ever asking for a number",
            "Comments on age or 'career switch' fit instead of assessing current selling skill",
            "Never explains how targets or incentives actually work, leaving "
            "the candidate to guess",
            "Ends the interview abruptly once satisfied, without warmth or clear next steps",
        ],
        session_beats=[
            "Opens warm and talkative, makes broad claims about past performance",
            "Mentions being an older re-entrant into the workforce after a career switch",
            "Reframes toward an adjacent win rather than admitting a gap outright",
            "Keeps talking past a silence instead of stopping",
            "Asks how incentives and targets actually work",
        ],
        stresses={"bias": 4, "clarity": 3, "structure": 3, "communication": 3, "experience": 2},
        tags=["frontline", "sales", "airtel", "dei", "tone"],
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
            "session_beats": a.session_beats,
            "stresses": a.stresses,
        }
        for a in ARCHETYPES.values()
    ]
