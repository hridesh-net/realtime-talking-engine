"""Integration tests: a custom-composed persona actually enacts as defined.

Offline — no model calls. Two things distinguish these from
`tests/test_trait_dimensions.py` (which tests the composer functions in
isolation):

1. They drive the full `VirtualCandidateAgent.generate()` pipeline, the same
   path `control_plane/api.py` uses for `custom_personas`.
2. The fake model is *adversarial* — it deliberately returns a draft that
   violates every constraint a real archetype's re-imposition logic exists to
   catch (knowledge above the ceiling, a dropped required skill, an invented
   extra skill, invented scorecard ids, an out-of-enum stance/truthfulness).
   If a custom-composed archetype enforced these guarantees any less strictly
   than a hand-written one, these tests would catch it.
"""

from __future__ import annotations

from typing import Any

import pytest

from candidate_agent import trait_dimensions as td
from candidate_agent.agent import VirtualCandidateAgent, derive_traits
from llm.base import StructuredModel

JOB = {
    "job_title": "Frontline Network Technician",
    "jd": "Install and maintain fiber networks at customer premises.",
    "skills_required": ["Fiber splicing", "Customer handling"],
    "experience_level": "junior",
    "company_type": "mnc",
    "job_location_type": "onsite",
    "duration_minutes": 20,
}


class AdversarialModel(StructuredModel):
    """Always returns a draft that tries to break every re-imposition rule.

    - Inflates one required skill to level 99 (must clamp into the band).
    - Omits the other required skill entirely (must be auto-restored).
    - Invents an extra skill not in skills_required (must be dropped, since
      none of these test archetypes allow_adjacent_strength).
    - Uses an out-of-enum stance ("confident") and truthfulness ("maybe").
    - Invents must_discover ids that don't exist in the catalog.
    - Returns 10 verbal tics and 10 sample phrases (must truncate to 6/8).
    """

    @property
    def provider(self) -> str:
        return "adversarial"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        return {
            "name": "Adversarial Test Candidate",
            "headline": "Tries to break every guardrail",
            "background": "N/A",
            "years_experience": 3,
            "verdict_rationale": "N/A",
            "verbal_tics": [f"tic{i}" for i in range(10)],
            "sample_phrases": [f"phrase {i}" for i in range(10)],
            "reveals_depth_when": "never",
            "always_does": ["ignores the rubric"],
            "never_does": ["follows instructions"],
            "opening_line": "Hi.",
            "knowledge_map": [
                {
                    "skill": "Fiber splicing",
                    "level": 99,
                    "stance": "confident",
                    "talking_points": [],
                    "breaking_point": "never",
                    "wrong_beliefs": [],
                },
                {
                    "skill": "Invented Extra Skill",
                    "level": 10,
                    "stance": "solid",
                    "talking_points": [],
                    "breaking_point": "never",
                    "wrong_beliefs": [],
                },
                # "Customer handling" deliberately omitted.
            ],
            "resume_claims": [
                {
                    "claim": "Invented an unrelated claim",
                    "truthfulness": "maybe",
                    "probe_that_exposes_it": "N/A",
                }
            ],
            "must_discover": [
                {"id": "invented_id_1", "signal": "made up", "how_to_surface": "N/A"},
                {"id": "invented_id_2", "signal": "also made up", "how_to_surface": "N/A"},
            ],
        }


def _agent() -> VirtualCandidateAgent:
    return VirtualCandidateAgent(model=AdversarialModel("adversarial-1", 0.35))


async def _cast(archetype_key: str, **overrides: Any):
    kwargs = dict(JOB, interview_id="iv-test", archetype_key=archetype_key)
    kwargs.update(overrides)
    return await _agent().generate(**kwargs)


# ---------------------------------------------------------------------------
# Skill/verdict mechanics survive an adversarial model, for a composed
# archetype exactly as they do for a hand-written one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bias_trap",
    [None, "career_gap", "age_or_re_entry", "regional_or_accent", "caregiving"],
)
async def test_composed_persona_enforces_the_same_guarantees_as_hand_written(bias_trap):
    key = f"test-enact-{bias_trap or 'none'}"
    archetype = td.register_dynamic(
        key=key,
        label="Enactment test persona",
        verdict="borderline",
        competence="developing",
        conscientiousness="adequate",
        communication="guarded",
        emotional_stance="defensive",
        honesty="embellishing",
        bias_trap=bias_trap,
    )
    candidate = await _cast(key)

    # The archetype, not the model, decides the verdict.
    assert candidate.verdict == "borderline"
    assert candidate.interviewer_scorecard.expected_verdict == "borderline"

    # Every required skill appears exactly once, spelled as given.
    skills_seen = [k.skill for k in candidate.knowledge_map]
    assert sorted(skills_seen) == sorted(JOB["skills_required"])

    # The inflated skill was clamped into the band, not left at 99.
    low, high = archetype.knowledge_band
    fiber = next(k for k in candidate.knowledge_map if k.skill == "Fiber splicing")
    assert low <= fiber.level <= high

    # The omitted skill was restored with a level inside the band.
    customer = next(k for k in candidate.knowledge_map if k.skill == "Customer handling")
    assert low <= customer.level <= high

    # The invented extra skill never made it through (no adjacent-strength
    # exception on this archetype).
    assert "Invented Extra Skill" not in skills_seen

    # The out-of-enum stance fell back to a legal one.
    assert fiber.stance in ("solid", "shallow", "bluffs", "absent")

    # Scorecard ids and weights are the catalog's, not the model's.
    ids = {s.id for s in candidate.interviewer_scorecard.must_discover}
    assert "invented_id_1" not in ids
    assert "invented_id_2" not in ids
    assert round(sum(s.weight for s in candidate.interviewer_scorecard.must_discover), 4) == 1.0
    if bias_trap:
        assert "bias_free_handling" in ids
        trap_signal = td.BIAS_TRAP[bias_trap]["signal"]
        signal = next(
            s.signal
            for s in candidate.interviewer_scorecard.must_discover
            if s.id == "bias_free_handling"
        )
        # The model may reword it, but only via must_discover re-wording —
        # here the model didn't supply a matching id, so the catalog's own
        # text (grounded in the bias trap) must survive untouched.
        assert signal == trap_signal
    else:
        assert "structured_probing" in ids

    # Invalid resume-claim truthfulness fell back to "true".
    assert all(c.truthfulness in ("true", "exaggerated", "false") for c in candidate.resume_claims)

    # Verbal tics / sample phrases truncated to their caps.
    assert len(candidate.speech_profile.verbal_tics) <= 6
    assert len(candidate.speech_profile.sample_phrases) <= 8

    # Speech and answer-policy fixed fields come from the archetype, never
    # from the model, regardless of what "always_does"/"never_does" tried.
    assert candidate.speech_profile.pace == archetype.speech["pace"]
    assert candidate.speech_profile.formality == archetype.speech["formality"]
    assert candidate.answer_policy.on_pressure == archetype.answer_policy["on_pressure"]


# ---------------------------------------------------------------------------
# The human-traits layer enacts too — it reaches the compiled prompt exactly
# as specified, for every compliance-trap type individually.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trap", "expected_fragment"),
    [
        ("volunteers_protected_info", "protected personal information (age)"),
        ("requests_off_policy_favour", "off-policy favour"),
        ("asks_illegal_question_back", "inappropriate for them to have to answer"),
    ],
)
async def test_each_compliance_trap_reaches_the_compiled_prompt_distinctly(trap, expected_fragment):
    key = f"test-trap-{trap}"
    td.register_dynamic(
        key=key,
        label="Compliance trap test",
        verdict="reject",
        competence="solid",
        conscientiousness="adequate",
        communication="direct",
        emotional_stance="composed",
        honesty="transparent",
    )
    human_traits = td.compose_human_traits(
        affect="hostile",
        verbal_style="rambling",
        language="native_fluent",
        comprehension="sharp_listener",
        motivation="comp_only",
        negotiation_stance="anchors_high",
        environment="clean_professional_setup",
        seniority="junior",
        function="network",
        region="UP",
        gender_presentation="woman",
        age_band="25-34",
        notice_period="immediate",
        compliance_traps=[trap],
        protected_info_type="age" if trap == "volunteers_protected_info" else None,
    )
    candidate = await _cast(key, human_traits=human_traits)

    prompt = candidate.engine_contract.system_prompt
    assert "REALISM & COMPLIANCE LAYER" in prompt
    assert expected_fragment in prompt
    # The section header ("COMPLIANCE TRAPS") is a developer-facing label —
    # the persona is never told in-character that this is a trap. Check the
    # actual behavioral instruction line, not the whole prompt.
    trap_line = next(line for line in prompt.splitlines() if expected_fragment in line)
    assert "trap" not in trap_line.lower()


async def test_human_traits_values_land_verbatim_in_the_prompt():
    key = "test-human-traits-verbatim"
    td.register_dynamic(
        key=key,
        label="Verbatim test",
        verdict="select",
        competence="expert",
        conscientiousness="diligent",
        communication="expressive",
        emotional_stance="composed",
        honesty="transparent",
    )
    human_traits = td.compose_human_traits(
        affect="arrogant",
        verbal_style="jargon_flooder",
        language="developing_esl",
        comprehension="misreads_questions",
        motivation="not_really_looking",
        negotiation_stance="demands_off_band",
        environment="mobile_commuting",
        seniority="senior",
        function="sales",
        region="Karnataka",
        gender_presentation="man",
        age_band="40-49",
        notice_period="90_days",
    )
    candidate = await _cast(key, human_traits=human_traits)

    assert candidate.human_traits.affect == "arrogant"
    assert candidate.human_traits.verbal_style == "jargon_flooder"
    prompt = candidate.engine_contract.system_prompt
    assert "arrogant" in prompt
    assert "jargon_flooder" in prompt
    assert "Karnataka" in prompt
    assert "senior" in prompt
    assert "sales" in prompt
    assert "mobile or driving" in prompt.lower()


# ---------------------------------------------------------------------------
# Distinct compositions produce genuinely distinct, self-consistent personas
# — not just distinct labels on the same underlying values.
# ---------------------------------------------------------------------------


async def test_distinct_compositions_diverge_where_they_should():
    strong_key = "test-diverge-strong"
    weak_key = "test-diverge-weak"
    strong = td.register_dynamic(
        key=strong_key,
        label="Strong",
        verdict="select",
        competence="expert",
        conscientiousness="diligent",
        communication="direct",
        emotional_stance="composed",
        honesty="transparent",
    )
    weak = td.register_dynamic(
        key=weak_key,
        label="Weak",
        verdict="reject",
        competence="weak",
        conscientiousness="low_effort",
        communication="guarded",
        emotional_stance="disengaged",
        honesty="bluffing",
    )

    strong_candidate = await _cast(strong_key)
    weak_candidate = await _cast(weak_key)

    assert strong_candidate.verdict == "select"
    assert weak_candidate.verdict == "reject"

    strong_level = next(
        k.level for k in strong_candidate.knowledge_map if k.skill == "Fiber splicing"
    )
    weak_level = next(k.level for k in weak_candidate.knowledge_map if k.skill == "Fiber splicing")
    assert strong_level > weak_level
    assert strong.knowledge_band[0] > weak.knowledge_band[1]

    assert strong_candidate.candidate_id != weak_candidate.candidate_id
    assert (
        strong_candidate.engine_contract.system_prompt
        != weak_candidate.engine_contract.system_prompt
    )


# ---------------------------------------------------------------------------
# Determinism: the seed-derived half is identical across two casts of the
# same spec, independent of anything the model returns.
# ---------------------------------------------------------------------------


async def test_recasting_the_same_seed_reproduces_the_same_person():
    key = "test-determinism"
    td.register_dynamic(
        key=key,
        label="Determinism test",
        verdict="borderline",
        competence="solid",
        conscientiousness="adequate",
        communication="formal",
        emotional_stance="nervous",
        honesty="embellishing",
    )
    seed = "fixed-seed-for-determinism-test"
    first = await _cast(key, seed_override=seed)
    second = await _cast(key, seed_override=seed)

    assert first.seed_fingerprint == second.seed_fingerprint
    assert first.candidate_id == second.candidate_id
    assert [k.level for k in first.knowledge_map] == [k.level for k in second.knowledge_map]
    assert first.aptitude.model_dump() == second.aptitude.model_dump()


async def test_trait_bounds_are_respected_regardless_of_seed():
    """Confirm bounds hold across many seeds, not just one lucky draw.

    derive_traits must land inside the composed bounds for many seeds — not
    just the one this test suite happens to exercise elsewhere.
    """
    key = "test-trait-bounds-many-seeds"
    archetype = td.register_dynamic(
        key=key,
        label="Trait bounds test",
        verdict="borderline",
        competence="developing",
        conscientiousness="adequate",
        communication="guarded",
        emotional_stance="defensive",
        honesty="embellishing",
    )
    for i in range(25):
        traits = derive_traits(archetype, seed=f"seed-{i}")
        for name, value in traits.items():
            lo, hi = archetype.traits[name]
            assert lo <= value <= hi, f"{name}={value} outside [{lo},{hi}] for seed-{i}"
