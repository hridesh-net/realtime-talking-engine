"""Offline tests for the deterministic half of persona generation.

No model calls — these cover everything the LLM is not allowed to decide, so
they must stay fast and runnable without an API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_agent import archetypes as catalog
from candidate_agent.agent import VirtualCandidateAgent, derive_traits
from candidate_agent.archetypes import TRAIT_NAMES, VERDICTS
from candidate_agent.engine_contract import UNIVERSAL_FORBIDDEN, build_engine_contract
from candidate_agent.schema import AnswerPolicy, AptitudeProfile, SpeechProfile

ALL = list(catalog.ARCHETYPES.values())
SKILLS = ["Go", "distributed systems", "Redis"]


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_scorecard_weights_sum_to_one(a):
    assert round(sum(s.weight for s in a.must_discover), 4) == 1.0


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_archetype_is_well_formed(a):
    assert a.verdict in VERDICTS
    assert set(a.traits) == set(TRAIT_NAMES)
    assert all(lo <= hi for lo, hi in a.traits.values())
    lo, hi = a.knowledge_band
    assert 0 <= lo <= hi <= 10
    assert a.interviewer_challenge and a.interviewer_failure_modes
    assert len({s.id for s in a.must_discover}) == len(a.must_discover)


def test_exactly_two_defaults_one_of_each_verdict():
    """The enrollment UI promises one selectable and one rejectable by default."""
    defaults = catalog.default_keys()
    assert len(defaults) == 2
    verdicts = [catalog.get(k).verdict for k in defaults]
    assert verdicts == ["select", "reject"]


def test_catalog_covers_the_requested_archetype_space():
    keys = set(catalog.ARCHETYPES)
    for expected in ("lazy", "smart_but_lazy", "disengaged", "eager_underqualified"):
        assert expected in keys
    verdicts = {a.verdict for a in ALL}
    assert verdicts == {"select", "reject", "borderline"}


def test_catalog_payload_is_serializable():
    rows = catalog.catalog()
    assert len(rows) == len(catalog.ARCHETYPES)
    assert sum(1 for r in rows if r["is_default"]) == 2


# ---------------------------------------------------------------------------
# Seeded traits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_traits_land_inside_archetype_bounds(a):
    for i in range(25):
        traits = derive_traits(a, f"interview-{i}:{a.key}")
        for name, value in traits.items():
            lo, hi = a.traits[name]
            assert lo <= value <= hi, f"{name}={value} outside [{lo},{hi}]"


def test_same_seed_reproduces_the_same_person():
    a = catalog.get("smart_but_lazy")
    assert derive_traits(a, "int-1:smart_but_lazy") == derive_traits(a, "int-1:smart_but_lazy")


def test_different_interviews_produce_different_people():
    a = catalog.get("strong_hire")
    seen = {tuple(sorted(derive_traits(a, f"int-{i}:strong_hire").items())) for i in range(40)}
    assert len(seen) > 1, "trait derivation is not varying across interviews"


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_smartness_ratio_matches_the_verdict_direction(a):
    """Selectable personas must not read as dumber than rejectable ones."""
    from candidate_agent.agent import _aptitude

    ratio = _aptitude(derive_traits(a, f"x:{a.key}")).smartness_ratio
    assert 0.0 <= ratio <= 1.0
    if a.verdict == "select":
        assert ratio >= 0.7


# ---------------------------------------------------------------------------
# Knowledge clamping — the ceiling is ours, not the model's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_model_cannot_exceed_the_knowledge_band(a):
    lo, hi = a.knowledge_band
    draft = {
        "knowledge_map": [
            {
                "skill": s,
                "level": 10,
                "stance": "solid",
                "talking_points": [],
                "breaking_point": "never",
                "wrong_beliefs": [],
            }
            for s in SKILLS
        ]
    }
    entries = VirtualCandidateAgent._build_knowledge_map(draft, a, SKILLS)
    assert [e.skill for e in entries][: len(SKILLS)] == SKILLS
    for e in entries[: len(SKILLS)]:
        assert lo <= e.level <= hi


def test_missing_and_renamed_skills_are_restored():
    a = catalog.get("clear_reject")
    draft = {
        "knowledge_map": [
            {
                "skill": "GOLANG",
                "level": 2,
                "stance": "shallow",
                "talking_points": [],
                "breaking_point": "x",
                "wrong_beliefs": [],
            }
        ]
    }
    entries = VirtualCandidateAgent._build_knowledge_map(draft, a, SKILLS)
    assert [e.skill for e in entries] == SKILLS  # renamed entry dropped, all skills present


def test_adjacent_strength_survives_only_where_allowed():
    draft = {
        "knowledge_map": [
            {
                "skill": "Elixir",
                "level": 10,
                "stance": "solid",
                "talking_points": [],
                "breaking_point": "x",
                "wrong_beliefs": [],
            }
        ]
    }
    mismatch = VirtualCandidateAgent._build_knowledge_map(
        draft, catalog.get("specialist_mismatch"), SKILLS
    )
    assert any(e.skill == "Elixir" and e.level == 10 for e in mismatch)

    strict = VirtualCandidateAgent._build_knowledge_map(draft, catalog.get("lazy"), SKILLS)
    assert all(e.skill in SKILLS for e in strict)


# ---------------------------------------------------------------------------
# Scorecard assembly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_scorecard_keeps_catalog_ids_and_weights(a):
    """The model re-words signals; it cannot re-weight or drop them."""
    draft = {"must_discover": [{"id": "hallucinated", "signal": "x", "how_to_surface": "y"}]}
    card = VirtualCandidateAgent._build_scorecard(draft, a)
    assert [i.id for i in card.must_discover] == [s.id for s in a.must_discover]
    assert [i.weight for i in card.must_discover] == [s.weight for s in a.must_discover]
    assert card.expected_verdict == a.verdict


def test_scorecard_uses_model_wording_when_ids_match():
    a = catalog.get("strong_hire")
    target = a.must_discover[0].id
    draft = {
        "must_discover": [
            {"id": target, "signal": "job-specific signal", "how_to_surface": "job-specific probe"}
        ]
    }
    card = VirtualCandidateAgent._build_scorecard(draft, a)
    assert card.must_discover[0].signal == "job-specific signal"
    assert card.must_discover[1].signal == a.must_discover[1].signal  # falls back


# ---------------------------------------------------------------------------
# Engine contract — what the Go engine consumes
# ---------------------------------------------------------------------------


def _contract_for(a):
    speech = SpeechProfile(**a.speech, verbal_tics=["right"], sample_phrases=["so, yeah"])
    aptitude = AptitudeProfile(smartness_ratio=0.5, **derive_traits(a, f"c:{a.key}"))
    policy = AnswerPolicy(
        **a.answer_policy,
        reveals_depth_when="a specific follow-up",
        always_does=["nods"],
        never_does=["brags"],
    )
    knowledge = VirtualCandidateAgent._build_knowledge_map({"knowledge_map": []}, a, SKILLS)
    return build_engine_contract(
        candidate_id="vc-test",
        interview_id="int-test",
        name="Test Person",
        headline="h",
        background="b",
        years_experience=5,
        speech=speech,
        aptitude=aptitude,
        knowledge_map=knowledge,
        policy=policy,
        opening_line="Hi.",
    )


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_engine_contract_is_self_consistent(a):
    c = _contract_for(a)
    tp = c.turn_policy
    assert tp["min_sentences"] <= tp["target_sentences_per_answer"] <= tp["max_sentences"]
    assert set(c.knowledge_ceiling) == set(SKILLS)
    assert c.forbidden_behaviors == UNIVERSAL_FORBIDDEN
    assert c.unlock_condition


@pytest.mark.parametrize("a", ALL, ids=lambda a: a.key)
def test_system_prompt_carries_the_behavioural_contract(a):
    prompt = _contract_for(a).system_prompt
    assert "Test Person" in prompt
    for skill in SKILLS:
        assert skill in prompt, f"{skill} missing from the engine's system prompt"
    # The engine relies on these sections existing verbatim.
    for section in ("HOW YOU TALK", "WHAT YOU ACTUALLY KNOW", "HOW YOU ANSWER", "HARD RULES"):
        assert section in prompt
    assert "Never break character" in prompt
    # The persona must never be told its own verdict — it would play to it.
    assert a.verdict not in prompt.split("HARD RULES")[0].lower().split()


def test_system_prompt_is_byte_stable():
    a = catalog.get("rambler")
    assert _contract_for(a).system_prompt == _contract_for(a).system_prompt


# ---------------------------------------------------------------------------
# Resume claims
# ---------------------------------------------------------------------------


def test_resume_claims_reject_bad_truthfulness_values():
    claims = VirtualCandidateAgent._build_resume_claims(
        {
            "resume_claims": [
                {"claim": "led migration", "truthfulness": "mostly-true"},
                {"claim": "", "truthfulness": "false"},
                {
                    "claim": "built cache",
                    "truthfulness": "exaggerated",
                    "probe_that_exposes_it": "ask for the eviction policy",
                },
            ]
        }
    )
    assert [c.truthfulness for c in claims] == ["true", "exaggerated"]
    assert claims[0].probe_that_exposes_it  # default filled in
