"""Offline tests for candidate_agent.trait_dimensions.

Pure composition — no model calls. Verifies that composing from presets is
held to the same guarantees as a hand-written archetype (trait coverage,
legal verdict, must_discover weights summing to 1.0), that unknown presets
fail loudly, and that the §3.2 taxonomy vocabulary is enforced by
HumanTraitProfile's own validation.
"""

from __future__ import annotations

import pydantic
import pytest

from candidate_agent import archetypes as catalog
from candidate_agent import trait_dimensions as td

# ---------------------------------------------------------------------------
# compose_archetype / register_dynamic
# ---------------------------------------------------------------------------


def test_compose_archetype_produces_a_valid_archetype():
    a = td.compose_archetype(
        key="test-compose-1",
        label="Test compose",
        verdict="borderline",
        competence="developing",
        conscientiousness="adequate",
        communication="guarded",
        emotional_stance="defensive",
        honesty="embellishing",
        bias_trap="career_gap",
    )
    assert a.verdict == "borderline"
    assert set(a.traits) == set(catalog.TRAIT_NAMES)
    assert round(sum(s.weight for s in a.must_discover), 4) == 1.0
    assert len(a.must_discover) == 4
    assert "dynamic" in a.tags


def test_compose_archetype_without_bias_trap_falls_back_to_generic_signal():
    a = td.compose_archetype(
        key="test-compose-2",
        label="No trap",
        verdict="reject",
        competence="weak",
        conscientiousness="low_effort",
        communication="direct",
        emotional_stance="composed",
        honesty="bluffing",
    )
    ids = {s.id for s in a.must_discover}
    assert "structured_probing" in ids
    assert "bias_free_handling" not in ids


@pytest.mark.parametrize(
    "verdict",
    ["select", "reject", "borderline"],
)
def test_register_dynamic_registers_into_the_shared_catalog(verdict):
    key = f"test-register-{verdict}"
    td.register_dynamic(
        key=key,
        label="Registered",
        verdict=verdict,
        competence="solid",
        conscientiousness="diligent",
        communication="formal",
        emotional_stance="composed",
        honesty="transparent",
    )
    assert key in catalog.ARCHETYPES
    assert catalog.get(key).verdict == verdict


@pytest.mark.parametrize(
    "bad_field",
    [
        "competence",
        "conscientiousness",
        "communication",
        "emotional_stance",
        "honesty",
        "bias_trap",
    ],
)
def test_compose_archetype_rejects_unknown_presets(bad_field):
    kwargs = {
        "key": "test-bad",
        "label": "Bad",
        "verdict": "reject",
        "competence": "solid",
        "conscientiousness": "diligent",
        "communication": "formal",
        "emotional_stance": "composed",
        "honesty": "transparent",
    }
    kwargs[bad_field] = "not-a-real-preset"
    with pytest.raises(td.UnknownPresetError):
        td.compose_archetype(**kwargs)


# ---------------------------------------------------------------------------
# compose_human_traits
# ---------------------------------------------------------------------------

VALID_HUMAN_TRAIT_KWARGS = {
    "affect": "defensive",
    "verbal_style": "monosyllabic",
    "language": "hinglish_code_switcher",
    "comprehension": "frequent_clarifier",
    "motivation": "family_pressured",
    "negotiation_stance": "refuses_to_disclose_ctc",
    "environment": "spotty_home_network",
    "seniority": "junior",
    "function": "network",
    "region": "UP",
    "gender_presentation": "woman",
    "age_band": "25-34",
    "notice_period": "30_days",
}


def test_compose_human_traits_accepts_empty_string_protected_info_type():
    """Regression test for the UI's default form state.

    It sends protected_info_type="" (not None) whenever the field doesn't
    apply. "" must not 422 — it must be treated as "not set", same as
    omitting it.
    """
    traits = td.compose_human_traits(
        **VALID_HUMAN_TRAIT_KWARGS,
        compliance_traps=[],
        protected_info_type="",
    )
    assert traits.protected_info_type is None


def test_compose_human_traits_produces_a_valid_profile():
    traits = td.compose_human_traits(
        **VALID_HUMAN_TRAIT_KWARGS,
        compliance_traps=["volunteers_protected_info"],
        protected_info_type="marital_status",
        integrity_red_flags=["resume_inflation"],
    )
    assert traits.affect == "defensive"
    assert traits.fluency == td.LANGUAGE_PROFILE_PRESETS["hinglish_code_switcher"]["fluency"]
    assert traits.environment.camera_behavior == "toggling"


@pytest.mark.parametrize("bad_field", ["language", "comprehension", "environment"])
def test_compose_human_traits_rejects_unknown_presets(bad_field):
    kwargs = dict(VALID_HUMAN_TRAIT_KWARGS)
    kwargs[bad_field] = "not-a-real-preset"
    with pytest.raises(td.UnknownPresetError):
        td.compose_human_traits(**kwargs)


@pytest.mark.parametrize(
    "bad_field",
    ["affect", "verbal_style", "motivation", "negotiation_stance"],
)
def test_compose_human_traits_rejects_out_of_vocabulary_values(bad_field):
    kwargs = dict(VALID_HUMAN_TRAIT_KWARGS)
    kwargs[bad_field] = "not-in-the-taxonomy"
    with pytest.raises(pydantic.ValidationError):
        td.compose_human_traits(**kwargs)


def test_compose_human_traits_rejects_bad_compliance_trap_value():
    with pytest.raises(pydantic.ValidationError):
        td.compose_human_traits(**VALID_HUMAN_TRAIT_KWARGS, compliance_traps=["not-a-real-trap"])


def test_compose_human_traits_requires_protected_info_type_when_volunteered():
    with pytest.raises(ValueError, match="protected_info_type is required"):
        td.compose_human_traits(
            **VALID_HUMAN_TRAIT_KWARGS, compliance_traps=["volunteers_protected_info"]
        )
    # Providing it fixes the error.
    traits = td.compose_human_traits(
        **VALID_HUMAN_TRAIT_KWARGS,
        compliance_traps=["volunteers_protected_info"],
        protected_info_type="age",
    )
    assert traits.protected_info_type == "age"


def test_compose_human_traits_rejects_bad_protected_info_type():
    with pytest.raises(pydantic.ValidationError):
        td.compose_human_traits(
            **VALID_HUMAN_TRAIT_KWARGS,
            compliance_traps=["volunteers_protected_info"],
            protected_info_type="not-a-real-category",
        )


# ---------------------------------------------------------------------------
# dimension_catalog — the API's data source
# ---------------------------------------------------------------------------


def test_dimension_catalog_has_every_taxonomy_dimension():
    d = td.dimension_catalog()
    expected = {
        "competence",
        "conscientiousness",
        "communication",
        "emotional_stance",
        "honesty",
        "bias_trap",
        "affect",
        "verbal_style",
        "language",
        "comprehension",
        "motivation",
        "negotiation_stance",
        "compliance_traps",
        "protected_info_types",
        "integrity_red_flags",
        "environment",
    }
    assert expected <= set(d)
    # Every closed-vocabulary list must be non-empty, or a UI picker renders
    # an empty dropdown with no way to compose a valid persona.
    for key in ("affect", "verbal_style", "motivation", "negotiation_stance"):
        assert len(d[key]) > 0
    for key in ("language", "comprehension", "environment", "competence"):
        assert len(d[key]) > 0
