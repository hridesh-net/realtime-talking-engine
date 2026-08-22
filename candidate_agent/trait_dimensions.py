"""Compose archetypes from generic human-trait dimensions, on demand.

The fixed catalog in `archetypes.py` stays the source of truth for the eleven
curated personas — this module does not replace it. It gives a second, dynamic
path to the same destination: an `Archetype`, built by picking one preset from
each of a small set of orthogonal, reusable trait dimensions instead of hand
authoring every field. The determinism split still holds — every value a
composed archetype carries is code-owned, drawn from a fixed preset table, and
`_register` still validates it (trait bounds present, verdict legal, weights
sum to 1.0) before it can be cast. Nothing here lets the model choose a trait
or a weight; it only changes how many *engineer* keystrokes a new persona
costs.

Five dimensions, each a closed set of presets:

* `COMPETENCE`       — smartness/dumbness/knowledge_band
* `CONSCIENTIOUSNESS` — effort/preparedness/seriousness
* `COMMUNICATION`    — speech spec (pace, verbosity, formality, tone)
* `EMOTIONAL_STANCE` — nervousness/interest, filler/hesitation, on_pressure
* `HONESTY`          — the honesty trait and how they handle being pressed
* `BIAS_TRAP`        — optional: a realistic, job-irrelevant detail a biased
  interviewer might latch onto, plus the scorecard signal that catches it

A composed archetype always carries exactly 4 `must_discover` signals —
depth-vs-effort, claim verification, tone-and-composure, and either the bias
trap or a generic structured-probing signal — at fixed weights, so every
composed persona plugs into the same scorecard shape as the hand-written ones.
"""

from __future__ import annotations

from typing import Any

from candidate_agent.archetypes import Archetype, ScorecardSignal, _register
from candidate_agent.schema import EnvironmentProfile, HumanTraitProfile


class UnknownPresetError(KeyError):
    """Raised when a dimension preset name is not in its table."""


COMPETENCE: dict[str, dict] = {
    "expert": {
        "traits": {"smartness": (8, 10), "dumbness": (0, 2)},
        "knowledge_band": (7, 9),
        "text": "genuinely strong in the required skills",
        "failure_mode": "keyword-checks instead of testing the real ceiling",
    },
    "solid": {
        "traits": {"smartness": (6, 8), "dumbness": (2, 4)},
        "knowledge_band": (5, 7),
        "text": "solidly competent, not exceptional",
        "failure_mode": "either overrates them as expert or underrates them as weak",
    },
    "developing": {
        "traits": {"smartness": (4, 6), "dumbness": (4, 6)},
        "knowledge_band": (3, 5),
        "text": "still developing in the required skills",
        "failure_mode": "does not distinguish a coachable gap from a hard ceiling",
    },
    "weak": {
        "traits": {"smartness": (2, 4), "dumbness": (6, 8)},
        "knowledge_band": (1, 3),
        "text": "genuinely below the bar on the required skills",
        "failure_mode": "gets talked out of a clear reject by confidence or rapport",
    },
}

CONSCIENTIOUSNESS: dict[str, dict] = {
    "diligent": {
        "traits": {"effort": (8, 10), "preparedness": (7, 9), "seriousness": (7, 9)},
        "answer_depth": "thorough",
        "text": "prepared and puts in real effort",
        "failure_mode": "spends the saved time selling the role instead of probing further",
    },
    "adequate": {
        "traits": {"effort": (5, 7), "preparedness": (4, 6), "seriousness": (5, 7)},
        "answer_depth": "adequate",
        "text": "average effort, no more and no less",
        "failure_mode": "never checks whether more depth is available on request",
    },
    "low_effort": {
        "traits": {"effort": (1, 3), "preparedness": (1, 3), "seriousness": (2, 4)},
        "answer_depth": "minimal",
        "text": "did little preparation and does not pretend otherwise",
        "failure_mode": "scores them as unskilled when the skill was never actually tested",
    },
}

COMMUNICATION: dict[str, dict] = {
    "direct": {
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

EMOTIONAL_STANCE: dict[str, dict] = {
    "composed": {
        "traits": {"nervousness": (1, 3), "interest": (7, 9)},
        "filler_frequency": 1,
        "hesitation_frequency": 1,
        "on_pressure": "stays steady and reasons it through out loud",
        "text": "composed under pressure",
    },
    "nervous": {
        "traits": {"nervousness": (7, 9), "interest": (5, 7)},
        "filler_frequency": 5,
        "hesitation_frequency": 6,
        "on_pressure": "stumbles, self-corrects mid-sentence, and needs room to settle",
        "text": "nervous, self-corrects constantly",
    },
    "disengaged": {
        "traits": {"nervousness": (2, 4), "interest": (1, 3)},
        "filler_frequency": 3,
        "hesitation_frequency": 3,
        "on_pressure": "gives a slightly longer answer, then stops again",
        "text": "visibly disengaged",
    },
    "defensive": {
        "traits": {"nervousness": (5, 7), "interest": (4, 6)},
        "filler_frequency": 3,
        "hesitation_frequency": 4,
        "on_pressure": "gets clipped and guarded rather than opening up",
        "text": "turns defensive under pressure",
    },
}

HONESTY: dict[str, dict] = {
    "transparent": {
        "traits": {"honesty": (8, 10)},
        "on_unknown_question": "admits the gap plainly and reasons about it out loud",
        "text": "straightforwardly honest about limits",
    },
    "embellishing": {
        "traits": {"honesty": (4, 6)},
        "on_unknown_question": (
            "reframes toward an adjacent win rather than admitting the gap outright"
        ),
        "text": "tends to embellish rather than lie outright",
    },
    "bluffing": {
        "traits": {"honesty": (1, 3)},
        "on_unknown_question": (
            "bluffs with confident, vague language rather than admitting the gap"
        ),
        "text": "bluffs when they don't know something",
    },
}

#: Optional. A realistic, job-irrelevant detail a biased interviewer might
#: latch onto instead of assessing the actual skill. `None` is a legal choice
#: — the fourth scorecard signal falls back to generic structured probing.
BIAS_TRAP: dict[str, dict] = {
    "career_gap": {
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
        "text": "speaks with a regional accent and comes from a non-metro background",
        "signal": "Interviewer assesses substance, not accent or regional background",
        "how_to_surface": (
            "Keep the accent/regional cues present; watch whether questions target skill or origin"
        ),
        "failure_mode": "reads the accent or regional background as a competence signal",
    },
    "caregiving": {
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


def _lookup(table: dict[str, dict], name: str, dimension: str) -> dict:
    if name not in table:
        known = ", ".join(sorted(table))
        raise UnknownPresetError(f"unknown {dimension} preset '{name}'; known: {known}")
    return table[name]


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

    All values come from the fixed preset tables above — this only chooses
    which combination to assemble, so `_register`'s validation (trait bounds
    present, verdict legal, weights summing to 1.0) still applies unchanged.
    """
    comp = _lookup(COMPETENCE, competence, "competence")
    cons = _lookup(CONSCIENTIOUSNESS, conscientiousness, "conscientiousness")
    comm = _lookup(COMMUNICATION, communication, "communication")
    emo = _lookup(EMOTIONAL_STANCE, emotional_stance, "emotional_stance")
    hon = _lookup(HONESTY, honesty, "honesty")
    trap = _lookup(BIAS_TRAP, bias_trap, "bias_trap") if bias_trap else None

    traits = _merge_traits(comp["traits"], cons["traits"], emo["traits"], hon["traits"])

    speech = {
        **comm["speech"],
        "filler_frequency": emo["filler_frequency"],
        "hesitation_frequency": emo["hesitation_frequency"],
    }

    answer_policy = {
        "default_answer_depth": cons["answer_depth"],
        "on_unknown_question": hon["on_unknown_question"],
        "on_pressure": emo["on_pressure"],
        "on_silence": (
            "stays silent and waits"
            if emotional_stance == "disengaged"
            else "waits for the interviewer to redirect"
        ),
    }

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
    # and stresses restricted to the five rubric criteria at weight 1-4. Both
    # derived from the same five dimensions the rest of this archetype uses —
    # composing from presets must satisfy exactly what a hand-written
    # archetype has to (see `_register`), not a relaxed subset of it.
    session_beats = [
        f"Is {comp['text']}",
        f"Is {cons['text']}",
        f"Speaks in a way that is {comm['text']}",
        f"Is {emo['text']}",
        f"Is {hon['text']}",
    ]
    if trap:
        session_beats.append(f"At some point, {trap['text']}")

    stresses = {
        "structure": 3,
        "communication": 3,
        "clarity": 2,
        "bias": 4 if trap else 1,
    }

    return Archetype(
        key=key,
        label=label,
        description=description,
        verdict=verdict,
        interviewer_challenge=default_challenge,
        traits=traits,
        knowledge_band=comp["knowledge_band"],
        speech=speech,  # type: ignore[arg-type]
        answer_policy=answer_policy,  # type: ignore[arg-type]
        must_discover=must_discover,
        interviewer_failure_modes=failure_modes,
        session_beats=session_beats,
        stresses=stresses,
        tags=(tags or []) + ["dynamic"],
    )


def register_dynamic(**kwargs: Any) -> Archetype:
    """Compose an archetype from trait-dimension presets and register it.

    Raises the same `ValueError` as any hand-written archetype if the result
    fails validation (verdict, trait coverage, weight sum) — composing from
    presets does not bypass the catalog's guarantees, it only avoids writing
    the ~100 lines by hand for each new persona.
    """
    return _register(compose_archetype(**kwargs))


# ---------------------------------------------------------------------------
# §3.2 taxonomy — realism, communication, and compliance-training dimensions.
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

LANGUAGE_PROFILE_PRESETS: dict[str, dict] = {
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

COMPREHENSION_PRESETS: dict[str, dict] = {
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

ENVIRONMENT_PRESETS: dict[str, dict] = {
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
AFFECT_VALUES = (
    "hostile",
    "defensive",
    "anxious",
    "apathetic",
    "over_eager",
    "arrogant",
    "cooperative",
    "flirtatious_inappropriate",
    "grieving_distressed",
)
VERBAL_STYLE_VALUES = (
    "rambling",
    "monosyllabic",
    "tangential",
    "interrupts",
    "long_silences",
    "jargon_flooder",
    "over_formal",
)
MOTIVATION_VALUES = (
    "comp_only",
    "counter_offer_risk",
    "not_really_looking",
    "location_blocked",
    "family_pressured",
    "passion_hire",
)
NEGOTIATION_STANCE_VALUES = (
    "anchors_high",
    "refuses_to_disclose_ctc",
    "lowballs_self",
    "demands_off_band",
    "offer_shopping",
)
COMPLIANCE_TRAP_VALUES = (
    "volunteers_protected_info",
    "requests_off_policy_favour",
    "asks_illegal_question_back",
)
PROTECTED_INFO_TYPES = ("pregnancy", "age", "religion", "caste", "disability", "marital_status")
INTEGRITY_RED_FLAG_VALUES = (
    "resume_inflation",
    "concealed_termination",
    "ghost_employer",
    "dual_employment",
    "proxy_candidate",
    "ai_assisted_answers",
)


def dimension_catalog() -> dict[str, object]:
    """Every dimension and preset this module knows, serializable for a UI.

    The archetype-side dimensions (competence, conscientiousness, ...) list
    their keys plus the descriptive `text` fallback (present on every entry
    in those tables) so a picker can show a hint. `language`, `comprehension`,
    and `environment` return their full preset dicts, including the numeric
    fields (fluency, accent_strength, code_switch_probability) a radar chart
    can plot directly without re-deriving them.
    """
    return {
        "competence": {k: v["text"] for k, v in COMPETENCE.items()},
        "conscientiousness": {k: v["text"] for k, v in CONSCIENTIOUSNESS.items()},
        "communication": {k: v["text"] for k, v in COMMUNICATION.items()},
        "emotional_stance": {k: v["text"] for k, v in EMOTIONAL_STANCE.items()},
        "honesty": {k: v["text"] for k, v in HONESTY.items()},
        "bias_trap": {k: v["text"] for k, v in BIAS_TRAP.items()},
        "affect": list(AFFECT_VALUES),
        "verbal_style": list(VERBAL_STYLE_VALUES),
        "language": LANGUAGE_PROFILE_PRESETS,
        "comprehension": COMPREHENSION_PRESETS,
        "motivation": list(MOTIVATION_VALUES),
        "negotiation_stance": list(NEGOTIATION_STANCE_VALUES),
        "compliance_traps": list(COMPLIANCE_TRAP_VALUES),
        "protected_info_types": list(PROTECTED_INFO_TYPES),
        "integrity_red_flags": list(INTEGRITY_RED_FLAG_VALUES),
        "environment": ENVIRONMENT_PRESETS,
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
    """Compose one `HumanTraitProfile` from the §3.2 taxonomy.

    `affect`, `verbal_style`, `motivation`, `negotiation_stance`, and each
    entry in `compliance_traps` must match the taxonomy's own vocabulary
    (e.g. affect: hostile/defensive/anxious/apathetic/over_eager/arrogant/
    cooperative/flirtatious_inappropriate/grieving_distressed) — `HumanTraitProfile`
    validates them and raises if not. `language`, `comprehension`, and
    `environment` are preset keys into the tables above.
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
        environment=EnvironmentProfile(**env),
        seniority=seniority,
        function=function,
        region=region,
        gender_presentation=gender_presentation,
        age_band=age_band,
        notice_period=notice_period,
        offers_in_hand=offers_in_hand,
        **lang,
        **comp,
    )
