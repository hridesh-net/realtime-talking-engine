"""Compose archetypes from generic human-trait dimensions, on demand.

The fixed catalog in `archetypes.py` stays the source of truth for the curated
personas — this module does not replace it. It gives a second, dynamic path to
the same destination: an `Archetype`, built by picking one preset from each of a
small set of orthogonal, reusable trait dimensions instead of hand authoring
every field. The determinism split still holds — every value a composed
archetype carries is code-owned, drawn from a fixed preset table, and
`archetypes.validate_archetype` still checks it (trait bounds present, verdict
legal, weights sum to 1.0, speech and answer-policy shapes correct) before it
can be cast. Nothing here lets the model choose a trait or a weight; it only
changes how many *engineer* keystrokes a new persona costs.

Composed archetypes are **validated but never registered**. A persona composed
for one interview is not a catalog entry: putting it in the process-wide
`ARCHETYPES` dict would leak it into every other interview's picker, grow
without bound, and — because that dict is memory and the candidate row is not —
vanish on the next restart while the persona it describes stayed in the
database. `compose_custom_persona` returns the archetype; the caller passes it
straight to `VirtualCandidateAgent.generate`.

Five dimensions, each a closed set of presets:

* `COMPETENCE`       — smartness/dumbness/knowledge_band
* `CONSCIENTIOUSNESS` — effort/preparedness/seriousness
* `COMMUNICATION`    — speech spec (pace, verbosity, formality, tone)
* `EMOTIONAL_STANCE` — nervousness/interest, filler/hesitation, on_pressure
* `HONESTY`          — the honesty trait and how they handle being pressed
* `BIAS_TRAP`        — optional: a realistic, job-irrelevant detail a biased
  interviewer might latch onto, plus the scorecard signal that catches it

Each preset also declares which rubric criteria it puts under strain; a composed
persona's `stresses` are the sum, clamped to the catalog's 1-4 scale, so the
stress bars and the "next practice" recommendation mean the same thing for a
composed persona as for a hand-written one.

A composed archetype always carries exactly 4 `must_discover` signals —
depth-vs-effort, claim verification, tone-and-composure, and either the bias
trap or a generic structured-probing signal — at fixed weights, so every
composed persona plugs into the same scorecard shape as the hand-written ones.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict, TypeVar

from candidate_agent.archetypes import (
    RUBRIC_CRITERIA,
    AnswerPolicySpec,
    Archetype,
    ScorecardSignal,
    SpeechSpec,
    validate_archetype,
)
from candidate_agent.engine_contract import (
    AFFECT_DIRECTIVES,
    COMPLIANCE_TRAP_DIRECTIVES,
    INTEGRITY_DIRECTIVES,
    MOTIVATION_DIRECTIVES,
    NEGOTIATION_DIRECTIVES,
    VERBAL_STYLE_DIRECTIVES,
)
from candidate_agent.schema import EnvironmentProfile, HumanTraitProfile


class CommunicationSpeech(TypedDict):
    """The speech fields a communication preset fixes; the rest come from affect."""

    pace: str
    verbosity: str
    formality: str
    interrupts_interviewer: bool
    tone: str


class CompetencePreset(TypedDict):
    """How able this candidate actually is."""

    traits: dict[str, tuple[int, int]]
    knowledge_band: tuple[int, int]
    text: str
    failure_mode: str
    stresses: dict[str, int]
    #: 0-10 strength on this axis. Presentation only — the composer's radar.
    score: int


class ConscientiousnessPreset(TypedDict):
    """How much effort and preparation they bring."""

    traits: dict[str, tuple[int, int]]
    answer_depth: str
    text: str
    failure_mode: str
    stresses: dict[str, int]
    #: 0-10 strength on this axis. Presentation only — the composer's radar.
    score: int


class CommunicationPreset(TypedDict):
    """How they sound."""

    speech: CommunicationSpeech
    text: str
    stresses: dict[str, int]


class EmotionalStancePreset(TypedDict):
    """How they hold up."""

    traits: dict[str, tuple[int, int]]
    filler_frequency: int
    hesitation_frequency: int
    on_pressure: str
    text: str
    stresses: dict[str, int]
    #: 0-10 composure. Presentation only — the composer's radar.
    score: int


class HonestyPreset(TypedDict):
    """What they do with a question they cannot answer."""

    traits: dict[str, tuple[int, int]]
    on_unknown_question: str
    text: str
    stresses: dict[str, int]
    #: 0-10 strength on this axis. Presentation only — the composer's radar.
    score: int


class BiasTrapPreset(TypedDict):
    """A job-irrelevant detail a biased interviewer might latch onto."""

    text: str
    signal: str
    how_to_surface: str
    failure_mode: str
    stresses: dict[str, int]


class LanguagePreset(TypedDict):
    """Fluency, accent and code-switching as a correlated set."""

    fluency: int
    literacy_level: str
    native_speaker: bool
    accent_strength: float
    code_switch_probability: float
    vocabulary_ceiling: str


class ComprehensionPreset(TypedDict):
    """How reliably they understand what was asked."""

    clarification_rate: str
    misinterprets_question_rate: str
    needs_rephrasing: bool


class EnvironmentPreset(TypedDict):
    """Session logistics — camera, noise, connection, timing."""

    camera_behavior: str
    network_drops_at_minute: int | None
    background_noise: str
    joins_late_minutes: int
    mobile_or_driving: bool
    hard_stop_minute: int | None


@dataclass(frozen=True)
class CustomPersona:
    """One composed persona: a content-addressed key and both trait layers."""

    key: str
    archetype: Archetype
    human_traits: HumanTraitProfile


class UnknownPresetError(KeyError):
    """Raised when a dimension preset name is not in its table."""


COMPETENCE: dict[str, CompetencePreset] = {
    "expert": {
        "stresses": {"structure": 2},
        "traits": {"smartness": (8, 10), "dumbness": (0, 2)},
        "knowledge_band": (7, 9),
        "text": "genuinely strong in the required skills",
        "failure_mode": "keyword-checks instead of testing the real ceiling",
        "score": 9,
    },
    "solid": {
        "stresses": {"structure": 1},
        "traits": {"smartness": (6, 8), "dumbness": (2, 4)},
        "knowledge_band": (5, 7),
        "text": "solidly competent, not exceptional",
        "failure_mode": "either overrates them as expert or underrates them as weak",
        "score": 7,
    },
    "developing": {
        "stresses": {"structure": 1, "communication": 1},
        "traits": {"smartness": (4, 6), "dumbness": (4, 6)},
        "knowledge_band": (3, 5),
        "text": "still developing in the required skills",
        "failure_mode": "does not distinguish a coachable gap from a hard ceiling",
        "score": 5,
    },
    "weak": {
        "stresses": {"structure": 2, "communication": 1},
        "traits": {"smartness": (2, 4), "dumbness": (6, 8)},
        "knowledge_band": (1, 3),
        "text": "genuinely below the bar on the required skills",
        "failure_mode": "gets talked out of a clear reject by confidence or rapport",
        "score": 3,
    },
}

CONSCIENTIOUSNESS: dict[str, ConscientiousnessPreset] = {
    "diligent": {
        "stresses": {"clarity": 2},
        "traits": {"effort": (8, 10), "preparedness": (7, 9), "seriousness": (7, 9)},
        "answer_depth": "thorough",
        "text": "prepared and puts in real effort",
        "failure_mode": "spends the saved time selling the role instead of probing further",
        "score": 9,
    },
    "adequate": {
        "stresses": {"structure": 1},
        "traits": {"effort": (5, 7), "preparedness": (4, 6), "seriousness": (5, 7)},
        "answer_depth": "adequate",
        "text": "average effort, no more and no less",
        "failure_mode": "never checks whether more depth is available on request",
        "score": 6,
    },
    "low_effort": {
        "stresses": {"structure": 2, "communication": 1},
        "traits": {"effort": (1, 3), "preparedness": (1, 3), "seriousness": (2, 4)},
        "answer_depth": "minimal",
        "text": "did little preparation and does not pretend otherwise",
        "failure_mode": "scores them as unskilled when the skill was never actually tested",
        "score": 2,
    },
}

COMMUNICATION: dict[str, CommunicationPreset] = {
    "direct": {
        "stresses": {"clarity": 1},
        "speech": {
            "pace": "measured",
            "verbosity": "terse",
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "plain, to the point",
        },
        "text": "speaks plainly and briefly",
    },
    "expressive": {
        "stresses": {"structure": 1},
        "speech": {
            "pace": "fast",
            "verbosity": "verbose",
            "formality": "neutral",
            "interrupts_interviewer": False,
            "tone": "warm, energetic",
        },
        "text": "warm and talkative",
    },
    "guarded": {
        "stresses": {"communication": 3},
        "speech": {
            "pace": "slow",
            "verbosity": "terse",
            "formality": "casual",
            "interrupts_interviewer": False,
            "tone": "careful, a little withheld until put at ease",
        },
        "text": "guarded until they trust the interviewer",
    },
    "formal": {
        "stresses": {"communication": 1},
        "speech": {
            "pace": "measured",
            "verbosity": "balanced",
            "formality": "formal",
            "interrupts_interviewer": False,
            "tone": "polished and formal",
        },
        "text": "formal and polished in register",
    },
}

EMOTIONAL_STANCE: dict[str, EmotionalStancePreset] = {
    "composed": {
        "stresses": {"structure": 1},
        "traits": {"nervousness": (1, 3), "interest": (7, 9)},
        "filler_frequency": 1,
        "hesitation_frequency": 1,
        "on_pressure": "stays steady and reasons it through out loud",
        "text": "composed under pressure",
        "score": 8,  # composure = 10 - midpoint(nervousness)
    },
    "nervous": {
        "stresses": {"communication": 4},
        "traits": {"nervousness": (7, 9), "interest": (5, 7)},
        "filler_frequency": 5,
        "hesitation_frequency": 6,
        "on_pressure": "stumbles, self-corrects mid-sentence, and needs room to settle",
        "text": "nervous, self-corrects constantly",
        "score": 2,
    },
    "disengaged": {
        "stresses": {"communication": 2, "clarity": 2},
        "traits": {"nervousness": (2, 4), "interest": (1, 3)},
        "filler_frequency": 3,
        "hesitation_frequency": 3,
        "on_pressure": "gives a slightly longer answer, then stops again",
        "text": "visibly disengaged",
        "score": 7,
    },
    "defensive": {
        "stresses": {"communication": 3, "structure": 1},
        "traits": {"nervousness": (5, 7), "interest": (4, 6)},
        "filler_frequency": 3,
        "hesitation_frequency": 4,
        "on_pressure": "gets clipped and guarded rather than opening up",
        "text": "turns defensive under pressure",
        "score": 4,
    },
}

HONESTY: dict[str, HonestyPreset] = {
    "transparent": {
        "stresses": {"clarity": 1},
        "traits": {"honesty": (8, 10)},
        "on_unknown_question": "admits the gap plainly and reasons about it out loud",
        "text": "straightforwardly honest about limits",
        "score": 9,
    },
    "embellishing": {
        "stresses": {"structure": 2},
        "traits": {"honesty": (4, 6)},
        "on_unknown_question": (
            "reframes toward an adjacent win rather than admitting the gap outright"
        ),
        "text": "tends to embellish rather than lie outright",
        "score": 5,
    },
    "bluffing": {
        "stresses": {"structure": 3},
        "traits": {"honesty": (1, 3)},
        "on_unknown_question": (
            "bluffs with confident, vague language rather than admitting the gap"
        ),
        "text": "bluffs when they don't know something",
        "score": 2,
    },
}

#: Optional. A realistic, job-irrelevant detail a biased interviewer might
#: latch onto instead of assessing the actual skill. `None` is a legal choice
#: — the fourth scorecard signal falls back to generic structured probing.
BIAS_TRAP: dict[str, BiasTrapPreset] = {
    "career_gap": {
        "stresses": {"fairness": 4},
        "text": "has a career gap (family caregiving) they will mention if given the opening",
        "signal": (
            "Interviewer asks about readiness and skills, not the personal reason behind the gap"
        ),
        "how_to_surface": (
            "Volunteer the career gap; watch whether the follow-up is job-relevant or personal"
        ),
        "failure_mode": "asks about marital or family status instead of current readiness",
    },
    "age_or_re_entry": {
        "stresses": {"fairness": 4},
        "text": (
            "is re-entering the workforce after a career switch, older than the typical hire "
            "for this role"
        ),
        "signal": (
            "Interviewer evaluates current ability, not age or how recently they re-entered "
            "the workforce"
        ),
        "how_to_surface": (
            "Mention the career switch and age; watch for age/fit assumptions in the follow-up"
        ),
        "failure_mode": "comments on age or 'career switch' fit instead of assessing current skill",
    },
    "regional_or_accent": {
        "stresses": {"fairness": 4, "communication": 1},
        "text": "speaks with a regional accent and comes from a non-metro background",
        "signal": "Interviewer assesses substance, not accent or regional background",
        "how_to_surface": (
            "Keep the accent/regional cues present; watch whether questions target skill or origin"
        ),
        "failure_mode": "reads the accent or regional background as a competence signal",
    },
    "caregiving": {
        "stresses": {"fairness": 4},
        "text": "manages caregiving responsibilities that shape their availability",
        "signal": (
            "Interviewer asks about scheduling needs without treating caregiving as a "
            "competence flag"
        ),
        "how_to_surface": (
            "Mention caregiving responsibilities; watch whether it derails into a fitness judgement"
        ),
        "failure_mode": "treats caregiving responsibilities as a proxy for lower commitment",
    },
}


def _merge_traits(*parts: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    merged: dict[str, tuple[int, int]] = {}
    for part in parts:
        merged.update(part)
    return merged


_Preset = TypeVar("_Preset")


def _lookup(table: Mapping[str, _Preset], name: str, dimension: str) -> _Preset:
    if name not in table:
        known = ", ".join(sorted(table))
        raise UnknownPresetError(f"unknown {dimension} preset '{name}'; known: {known}")
    return table[name]


def _derive_stresses(*presets: Mapping[str, object]) -> dict[str, int]:
    """Sum each chosen preset's rubric pressure, clamped to the catalog's 1-4.

    Every criterion is present at 1 or above: a persona that puts no strain on a
    competency still gives the manager an opportunity to fail at it, and the
    catalog's own hand-written archetypes score it 1 rather than omitting it.
    """
    totals = dict.fromkeys(RUBRIC_CRITERIA, 0)
    for preset in presets:
        contributions = preset.get("stresses") or {}
        assert isinstance(contributions, dict)
        for criterion, weight in contributions.items():
            totals[criterion] += weight
    return {criterion: max(1, min(4, total)) for criterion, total in totals.items()}


def compose_archetype(
    *,
    key: str,
    label: str,
    verdict: str,
    competence: str,
    conscientiousness: str,
    communication: str,
    emotional_stance: str,
    honesty: str,
    bias_trap: str | None = None,
    interviewer_challenge: str = "",
    tags: list[str] | None = None,
) -> Archetype:
    """Build one `Archetype` from five generic trait-dimension presets.

    All values come from the fixed preset tables above — this only chooses which
    combination to assemble, so `archetypes.validate_archetype` (trait bounds
    present, verdict legal, weights summing to 1.0, speech and answer-policy
    shape correct) applies unchanged.

    The result is **not** registered. A persona composed for one interview is
    not a catalog entry; the caller passes it to `VirtualCandidateAgent.generate`
    directly.
    """
    comp = _lookup(COMPETENCE, competence, "competence")
    cons = _lookup(CONSCIENTIOUSNESS, conscientiousness, "conscientiousness")
    comm = _lookup(COMMUNICATION, communication, "communication")
    emo = _lookup(EMOTIONAL_STANCE, emotional_stance, "emotional_stance")
    hon = _lookup(HONESTY, honesty, "honesty")
    trap = _lookup(BIAS_TRAP, bias_trap, "bias_trap") if bias_trap else None

    traits = _merge_traits(comp["traits"], cons["traits"], emo["traits"], hon["traits"])

    # Built field by field rather than by `**` merge: SpeechSpec is a TypedDict,
    # so an explicit constructor is the only form mypy can check — a preset that
    # misspells a key becomes a type error here instead of a persona that
    # silently speaks wrong.
    speech = SpeechSpec(
        pace=comm["speech"]["pace"],
        verbosity=comm["speech"]["verbosity"],
        formality=comm["speech"]["formality"],
        interrupts_interviewer=comm["speech"]["interrupts_interviewer"],
        tone=comm["speech"]["tone"],
        filler_frequency=emo["filler_frequency"],
        hesitation_frequency=emo["hesitation_frequency"],
    )

    answer_policy = AnswerPolicySpec(
        default_answer_depth=cons["answer_depth"],
        on_unknown_question=hon["on_unknown_question"],
        on_pressure=emo["on_pressure"],
        on_silence=(
            "stays silent and waits"
            if emotional_stance == "disengaged"
            else "waits for the interviewer to redirect"
        ),
    )

    fourth_signal = (
        ScorecardSignal(
            id="bias_free_handling",
            signal=trap["signal"],
            weight=0.25,
            how_to_surface=trap["how_to_surface"],
        )
        if trap
        else ScorecardSignal(
            id="structured_probing",
            signal=(
                "Interviewer uses open follow-ups and probes a specific example instead of "
                "stopping at yes/no"
            ),
            weight=0.25,
            how_to_surface=(
                "Give a short first answer and see if the interviewer asks for a concrete example"
            ),
        )
    )

    must_discover = [
        ScorecardSignal(
            id="depth_vs_effort",
            signal="Interviewer separates actual skill ceiling from effort and preparation",
            weight=0.30,
            how_to_surface="Offer an easy win in the strongest area and see if real depth appears",
        ),
        ScorecardSignal(
            id="claim_verification",
            signal=(
                "Interviewer verifies claims with specifics rather than accepting them at "
                "face value"
            ),
            weight=0.25,
            how_to_surface=(
                "Make a claim without a concrete example attached and see if it's probed"
            ),
        ),
        fourth_signal,
        ScorecardSignal(
            id="tone_and_composure",
            signal=(
                "Interviewer's tone stays even and respectful across the full range of this "
                "candidate's responses"
            ),
            weight=0.20,
            how_to_surface=(
                "React in character (guarded/nervous/disengaged/defensive) and watch the "
                "interviewer's tone"
            ),
        ),
    ]

    failure_modes = [
        comp["failure_mode"],
        cons["failure_mode"],
        (trap["failure_mode"] if trap else "accepts a shallow first answer and moves on"),
    ]

    description = (
        f"A candidate who is {comp['text']}, {cons['text']}, {comm['text']}, and "
        f"{emo['text']}. They are {hon['text']}." + (f" They {trap['text']}." if trap else "")
    )

    default_challenge = (
        interviewer_challenge
        or f"Separate {comp['text']} from {cons['text']}, and stay bias-free and even-toned "
        f"while this candidate is {emo['text']}."
    )

    # v2.0 catalog requirements: at least one observable session_beats entry,
    # and stresses restricted to the rubric criteria at weight 1-4. Both are
    # derived from the same presets the rest of this archetype uses — composing
    # must satisfy exactly what a hand-written archetype has to (see
    # `archetypes.validate_archetype`), not a relaxed subset of it.
    session_beats = [
        f"Is {comp['text']}",
        f"Is {cons['text']}",
        f"Speaks in a way that is {comm['text']}",
        f"Is {emo['text']}",
        f"Is {hon['text']}",
    ]
    if trap:
        session_beats.append(f"At some point, {trap['text']}")

    presets: list[Mapping[str, object]] = [comp, cons, comm, emo, hon]
    if trap:
        presets.append(trap)
    stresses = _derive_stresses(*presets)

    return validate_archetype(
        Archetype(
            key=key,
            label=label,
            description=description,
            verdict=verdict,
            interviewer_challenge=default_challenge,
            traits=traits,
            knowledge_band=comp["knowledge_band"],
            speech=speech,
            answer_policy=answer_policy,
            must_discover=must_discover,
            interviewer_failure_modes=failure_modes,
            session_beats=session_beats,
            stresses=stresses,
            tags=(tags or []) + ["dynamic"],
        )
    )


# ---------------------------------------------------------------------------
# The realism taxonomy — realism, communication and compliance-training axes.
#
# PROVENANCE, UNRESOLVED: this vocabulary was introduced citing "BRD §3.2". It
# is not from there. BRD v3 §3.2 is the job card and BRD v2 §3.2 is the
# non-functional requirements, and no document in `docs/` contains any of these
# terms. The taxonomy may well come from a source outside the repo — but until
# someone says which, treat it as a design proposal rather than a requirement,
# and do not cite a section number for it.
#
# Orthogonal to everything above: `compose_archetype` decides whether the
# candidate can do the job; this decides how believably, and dangerously for
# an unprepared interviewer, they come across while doing it. `affect`,
# `verbal_style`, `motivation`, `negotiation_stance`, and `compliance_traps`
# take the taxonomy's own vocabulary directly — `HumanTraitProfile` validates
# them, so a typo raises a pydantic error rather than silently no-op'ing.
# Language, comprehension, and environment are compound (several correlated
# numbers/flags), so those three get convenience presets below.
# ---------------------------------------------------------------------------

LANGUAGE_PROFILE_PRESETS: dict[str, LanguagePreset] = {
    "native_fluent": {
        "fluency": 9,
        "literacy_level": "native",
        "native_speaker": True,
        "accent_strength": 0.1,
        "code_switch_probability": 0.05,
        "vocabulary_ceiling": "executive",
    },
    "confident_non_native": {
        "fluency": 7,
        "literacy_level": "fluent",
        "native_speaker": False,
        "accent_strength": 0.4,
        "code_switch_probability": 0.2,
        "vocabulary_ceiling": "technical",
    },
    "hinglish_code_switcher": {
        "fluency": 6,
        "literacy_level": "functional",
        "native_speaker": False,
        "accent_strength": 0.5,
        "code_switch_probability": 0.6,
        "vocabulary_ceiling": "workplace",
    },
    "developing_esl": {
        "fluency": 4,
        "literacy_level": "basic",
        "native_speaker": False,
        "accent_strength": 0.7,
        "code_switch_probability": 0.3,
        "vocabulary_ceiling": "basic",
    },
}

COMPREHENSION_PRESETS: dict[str, ComprehensionPreset] = {
    "sharp_listener": {
        "clarification_rate": "low",
        "misinterprets_question_rate": "low",
        "needs_rephrasing": False,
    },
    "average_listener": {
        "clarification_rate": "medium",
        "misinterprets_question_rate": "medium",
        "needs_rephrasing": False,
    },
    "frequent_clarifier": {
        "clarification_rate": "high",
        "misinterprets_question_rate": "low",
        "needs_rephrasing": True,
    },
    "misreads_questions": {
        "clarification_rate": "low",
        "misinterprets_question_rate": "high",
        "needs_rephrasing": True,
    },
}

ENVIRONMENT_PRESETS: dict[str, EnvironmentPreset] = {
    "clean_professional_setup": {
        "camera_behavior": "on",
        "network_drops_at_minute": None,
        "background_noise": "quiet",
        "joins_late_minutes": 0,
        "mobile_or_driving": False,
        "hard_stop_minute": None,
    },
    "spotty_home_network": {
        "camera_behavior": "toggling",
        "network_drops_at_minute": 8,
        "background_noise": "moderate household noise",
        "joins_late_minutes": 0,
        "mobile_or_driving": False,
        "hard_stop_minute": None,
    },
    "mobile_commuting": {
        "camera_behavior": "off",
        "network_drops_at_minute": None,
        "background_noise": "street and traffic noise",
        "joins_late_minutes": 0,
        "mobile_or_driving": True,
        "hard_stop_minute": None,
    },
    "habitual_latecomer": {
        "camera_behavior": "on",
        "network_drops_at_minute": None,
        "background_noise": "quiet",
        "joins_late_minutes": 6,
        "mobile_or_driving": False,
        "hard_stop_minute": 20,
    },
}


#: The taxonomy's own closed vocabularies — mirrors the `pattern=` constraints
#: on `HumanTraitProfile` in `schema.py`. Exposed via `dimension_catalog()` so
#: a caller (e.g. the enrollment UI) never has to hardcode these lists.
#: The taxonomy's closed vocabularies, derived from the directive tables in
#: `engine_contract` so a value can never exist without the behaviour it names.
#: `schema.HumanTraitProfile` re-declares the same sets as `pattern=`
#: constraints (it cannot import `engine_contract` — that module imports it),
#: and `tests/test_architecture.py` asserts the two never drift apart.
AFFECT_VALUES: tuple[str, ...] = tuple(AFFECT_DIRECTIVES)
VERBAL_STYLE_VALUES: tuple[str, ...] = tuple(VERBAL_STYLE_DIRECTIVES)
MOTIVATION_VALUES: tuple[str, ...] = tuple(MOTIVATION_DIRECTIVES)
NEGOTIATION_STANCE_VALUES: tuple[str, ...] = tuple(NEGOTIATION_DIRECTIVES)
COMPLIANCE_TRAP_VALUES: tuple[str, ...] = tuple(COMPLIANCE_TRAP_DIRECTIVES)
INTEGRITY_RED_FLAG_VALUES: tuple[str, ...] = tuple(INTEGRITY_DIRECTIVES)
PROTECTED_INFO_TYPES: tuple[str, ...] = (
    "pregnancy",
    "age",
    "religion",
    "caste",
    "disability",
    "marital_status",
)

#: The profile fields. `seniority`, `gender_presentation`, `age_band` and
#: `notice_period` are closed sets; `function` and `region` are genuinely open
#: (no fixed list survives contact with a real org chart) and are constrained by
#: `schema.PROFILE_TEXT_PATTERN` instead — one short line, no newlines, no
#: control characters. Both reach the compiled prompt, so both are rendered
#: quoted and above the hard rules rather than after them.
SENIORITY_VALUES: tuple[str, ...] = ("fresher", "junior", "mid", "senior", "lead", "manager")
GENDER_PRESENTATION_VALUES: tuple[str, ...] = ("woman", "man", "non_binary", "unspecified")
AGE_BAND_VALUES: tuple[str, ...] = ("18-24", "25-34", "35-44", "45-54", "55+")
NOTICE_PERIOD_VALUES: tuple[str, ...] = (
    "immediate",
    "15_days",
    "30_days",
    "60_days",
    "90_days",
)


#: Radar-chart strength per comprehension preset. Deliberately not a key inside
#: `COMPREHENSION_PRESETS`: that table's shape is the set of fields
#: `HumanTraitProfile` takes, and a presentation-only number is not one of them.
COMPREHENSION_SCORES: dict[str, int] = {
    "sharp_listener": 9,
    "average_listener": 6,
    "frequent_clarifier": 5,
    "misreads_questions": 2,
}


def dimension_catalog() -> dict[str, object]:
    """Every dimension and preset this module knows, serializable for a UI.

    The archetype-side dimensions that carry a comparable 0-10 "score"
    (competence, conscientiousness, emotional_stance, honesty, comprehension)
    return `{key: {"text": ..., "score": ...}}` so a radar chart can plot the
    *actual selected preset's* trait strength — not a stand-in — alongside
    its hint text. `communication` and `bias_trap` have no single comparable
    scalar, so they stay `{key: text}`. `language` and `environment` return
    their full preset dicts, including the numeric fields (fluency,
    accent_strength, code_switch_probability) a radar chart can plot directly
    without re-deriving them.
    """
    return {
        "competence": {k: {"text": v["text"], "score": v["score"]} for k, v in COMPETENCE.items()},
        "conscientiousness": {
            k: {"text": v["text"], "score": v["score"]} for k, v in CONSCIENTIOUSNESS.items()
        },
        "communication": {k: v["text"] for k, v in COMMUNICATION.items()},
        "emotional_stance": {
            k: {"text": v["text"], "score": v["score"]} for k, v in EMOTIONAL_STANCE.items()
        },
        "honesty": {k: {"text": v["text"], "score": v["score"]} for k, v in HONESTY.items()},
        "bias_trap": {k: v["text"] for k, v in BIAS_TRAP.items()},
        # Value -> the behaviour it actually produces. The picker shows the
        # sentence rather than the token, which is also the only honest way to
        # let someone choose between "tangential" and "rambling".
        "affect": dict(AFFECT_DIRECTIVES),
        "verbal_style": dict(VERBAL_STYLE_DIRECTIVES),
        "motivation": dict(MOTIVATION_DIRECTIVES),
        "negotiation_stance": dict(NEGOTIATION_DIRECTIVES),
        "compliance_traps": dict(COMPLIANCE_TRAP_DIRECTIVES),
        "integrity_red_flags": dict(INTEGRITY_DIRECTIVES),
        "language": LANGUAGE_PROFILE_PRESETS,
        "comprehension": {
            k: {**v, "score": COMPREHENSION_SCORES[k]} for k, v in COMPREHENSION_PRESETS.items()
        },
        "environment": ENVIRONMENT_PRESETS,
        "protected_info_types": list(PROTECTED_INFO_TYPES),
        "seniority": list(SENIORITY_VALUES),
        "gender_presentation": list(GENDER_PRESENTATION_VALUES),
        "age_band": list(AGE_BAND_VALUES),
        "notice_period": list(NOTICE_PERIOD_VALUES),
    }


def compose_human_traits(
    *,
    affect: str,
    verbal_style: str,
    language: str,
    comprehension: str,
    motivation: str,
    negotiation_stance: str,
    environment: str,
    seniority: str,
    function: str,
    region: str,
    gender_presentation: str,
    age_band: str,
    notice_period: str,
    integrity_red_flags: list[str] | None = None,
    compliance_traps: list[str] | None = None,
    protected_info_type: str | None = None,
    offers_in_hand: int = 0,
) -> HumanTraitProfile:
    """Compose one `HumanTraitProfile` from the realism taxonomy.

    `affect`, `verbal_style`, `motivation`, `negotiation_stance`, and each entry
    in `compliance_traps` and `integrity_red_flags` must be a key of the
    matching directive table in `candidate_agent.engine_contract` —
    `HumanTraitProfile` re-declares those vocabularies as patterns and raises if
    not. `language`, `comprehension` and `environment` are preset keys into the
    tables above. `function` and `region` are free text, constrained to one
    short line by `schema.PROFILE_TEXT_PATTERN`.
    """
    lang = _lookup(LANGUAGE_PROFILE_PRESETS, language, "language")
    comp = _lookup(COMPREHENSION_PRESETS, comprehension, "comprehension")
    env = _lookup(ENVIRONMENT_PRESETS, environment, "environment")
    if "volunteers_protected_info" in (compliance_traps or []) and not protected_info_type:
        raise ValueError(
            "protected_info_type is required when 'volunteers_protected_info' is a "
            "compliance trap — otherwise the compliance line silently drops from the "
            "compiled prompt"
        )
    return HumanTraitProfile(
        affect=affect,
        verbal_style=verbal_style,
        integrity_red_flags=integrity_red_flags or [],
        motivation=motivation,
        negotiation_stance=negotiation_stance,
        compliance_traps=compliance_traps or [],
        # "" (the UI's default when the field doesn't apply) must mean "not
        # set", not "set to the empty string" — HumanTraitProfile's pattern
        # only accepts a real category or None.
        protected_info_type=protected_info_type or None,
        environment=EnvironmentProfile(
            camera_behavior=env["camera_behavior"],
            network_drops_at_minute=env["network_drops_at_minute"],
            background_noise=env["background_noise"],
            joins_late_minutes=env["joins_late_minutes"],
            mobile_or_driving=env["mobile_or_driving"],
            hard_stop_minute=env["hard_stop_minute"],
        ),
        seniority=seniority,
        function=function,
        region=region,
        gender_presentation=gender_presentation,
        age_band=age_band,
        notice_period=notice_period,
        offers_in_hand=offers_in_hand,
        fluency=lang["fluency"],
        literacy_level=lang["literacy_level"],
        native_speaker=lang["native_speaker"],
        accent_strength=lang["accent_strength"],
        code_switch_probability=lang["code_switch_probability"],
        vocabulary_ceiling=lang["vocabulary_ceiling"],
        clarification_rate=comp["clarification_rate"],
        misinterprets_question_rate=comp["misinterprets_question_rate"],
        needs_rephrasing=comp["needs_rephrasing"],
    )


def persona_key(spec: Mapping[str, object]) -> str:
    """Content-addressed key for a composed persona — same spec, same key.

    Deliberately derived rather than random: re-submitting an unchanged spec
    must resolve to the persona already enrolled instead of casting a second
    identical one.
    """
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()
    return f"dyn-{digest[:12]}"


def compose_custom_persona(
    *,
    label: str,
    verdict: str,
    competence: str,
    conscientiousness: str,
    communication: str,
    emotional_stance: str,
    honesty: str,
    affect: str,
    verbal_style: str,
    language: str,
    comprehension: str,
    motivation: str,
    negotiation_stance: str,
    environment: str,
    seniority: str,
    function: str,
    region: str,
    gender_presentation: str,
    age_band: str,
    notice_period: str,
    bias_trap: str | None = None,
    compliance_traps: list[str] | None = None,
    protected_info_type: str | None = None,
    integrity_red_flags: list[str] | None = None,
    offers_in_hand: int = 0,
) -> CustomPersona:
    """Compose both halves of one custom persona from a validated spec.

    The transport layer's whole job for a custom persona is to hand the request
    body here and pass the result to `VirtualCandidateAgent.generate` — deciding
    what a spec means is domain work, not routing.

    Raises `UnknownPresetError` for a preset that does not exist and
    `ValueError`/`ValidationError` for anything that fails the same checks a
    hand-written archetype faces. Nothing is registered: the returned archetype
    belongs to one cast, not to the catalog.
    """
    key = persona_key(
        {
            "label": label,
            "verdict": verdict,
            "competence": competence,
            "conscientiousness": conscientiousness,
            "communication": communication,
            "emotional_stance": emotional_stance,
            "honesty": honesty,
            "bias_trap": bias_trap,
            "affect": affect,
            "verbal_style": verbal_style,
            "language": language,
            "comprehension": comprehension,
            "motivation": motivation,
            "negotiation_stance": negotiation_stance,
            "environment": environment,
            "seniority": seniority,
            "function": function,
            "region": region,
            "gender_presentation": gender_presentation,
            "age_band": age_band,
            "notice_period": notice_period,
            "compliance_traps": sorted(compliance_traps or []),
            "protected_info_type": protected_info_type or None,
            "integrity_red_flags": sorted(integrity_red_flags or []),
            "offers_in_hand": offers_in_hand,
        }
    )
    archetype = compose_archetype(
        key=key,
        label=label,
        verdict=verdict,
        competence=competence,
        conscientiousness=conscientiousness,
        communication=communication,
        emotional_stance=emotional_stance,
        honesty=honesty,
        bias_trap=bias_trap,
    )
    human_traits = compose_human_traits(
        affect=affect,
        verbal_style=verbal_style,
        language=language,
        comprehension=comprehension,
        motivation=motivation,
        negotiation_stance=negotiation_stance,
        environment=environment,
        seniority=seniority,
        function=function,
        region=region,
        gender_presentation=gender_presentation,
        age_band=age_band,
        notice_period=notice_period,
        compliance_traps=compliance_traps,
        protected_info_type=protected_info_type,
        integrity_red_flags=integrity_red_flags,
        offers_in_hand=offers_in_hand,
    )
    return CustomPersona(key=key, archetype=archetype, human_traits=human_traits)
