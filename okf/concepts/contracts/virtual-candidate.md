---
type: Contract
title: VirtualCandidate
description: The full persona document — who they are, what they know, how they talk, and how to grade the interviewer.
resource: /candidate_agent/schema.py
tags: [contract, persona, candidate, scorecard]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /candidate_agent/schema.py
  - resource: /candidate_agent/agent.py
---
# VirtualCandidate

`PERSONA_VERSION = "v1.0"`. Stored as one JSON document per
`(interview_id, archetype)`, with indexed columns alongside.

# Schema

```python
class VirtualCandidate(BaseModel):
    persona_version: str
    candidate_id: str            # "vc-" + sha256(seed)[:12]
    interview_id: str
    archetype: str
    archetype_label: str
    catalog_version: str

    name: str
    headline: str
    background: str
    years_experience: int        # 0..40

    verdict: str                 # select | reject | borderline
    verdict_rationale: str

    speech_profile: SpeechProfile
    aptitude: AptitudeProfile
    knowledge_map: list[SkillKnowledge]
    resume_claims: list[ResumeClaim] = []
    answer_policy: AnswerPolicy
    interviewer_scorecard: InterviewerScorecard
    engine_contract: EngineContract
    human_traits: HumanTraitProfile | None = None   # §3.2 taxonomy layer, optional

    fingerprint: str             # integrity — moves on every re-cast
    seed_fingerprint: str        # reproducibility — stable across re-casts
    seed: str
    raw_model_output: dict | None = None    # not persisted
```

## Sub-documents

**`SpeechProfile`** — how they talk. `pace` (slow|measured|fast), `verbosity`
(terse|balanced|verbose), `filler_frequency` and `hesitation_frequency` (0–10),
`formality` (casual|neutral|formal), `interrupts_interviewer`, `tone`,
`verbal_tics` (≤6), `sample_phrases` (≤8). The first seven come from the
archetype; the last two are model-authored.

**`AptitudeProfile`** — eight 0–10 axes plus a derived ratio: `smartness`,
`dumbness`, `smartness_ratio` (= smart/(smart+dumb), 2dp), `seriousness`,
`effort`, `interest`, `honesty`, `preparedness`, `nervousness`. **Entirely
code-derived** from the archetype's bounds by a seeded RNG. The axes are fixed
across all personas so reports can compare interviewers across candidates.

**`SkillKnowledge`** — per skill: `level` (0–10, clamped into the archetype's
band), `stance` (solid|shallow|bluffs|absent), `talking_points` (≤5),
`breaking_point` (the depth at which they fail), `wrong_beliefs` (≤4, empty
unless they bluff).

**`ResumeClaim`** — `claim`, `truthfulness` (true|exaggerated|false),
`probe_that_exposes_it`. Capped at 6; out-of-enum truthfulness degrades to
`true`.

**`AnswerPolicy`** — `default_answer_depth` (minimal|adequate|thorough),
`reveals_depth_when` (the unlock condition), `on_unknown_question`,
`on_pressure`, `on_silence`, `always_does` (≤6), `never_does` (≤6).

**`InterviewerScorecard`** — the ground-truth key for grading **the
interviewer**: `expected_verdict`, `interviewer_challenge`, `must_discover`
(weighted `ScorecardItem`s whose weights always total 1.0, enforced at archetype
registration), `interviewer_failure_modes`, `pass_condition` (≥ 0.70 discovery
weight **and** the right verdict). Never expose this to the model playing the
persona.

**`EngineContract`** — see [its own page](/concepts/contracts/engine-contract.md).

## What the model may author

Only `CANDIDATE_DRAFT_JSON_SCHEMA`: name, headline, background,
years_experience, verdict_rationale, verbal_tics, sample_phrases,
reveals_depth_when, always_does, never_does, opening_line, knowledge_map,
resume_claims, must_discover (re-wording only — ids and weights are ignored).

Everything else is computed. See [the determinism split](/concepts/determinism.md).

## Invariants the assembly enforces

* Every `skills_required` entry appears in `knowledge_map` exactly once, with the original spelling, even if the model dropped or renamed it.
* Levels for required skills are clamped into `archetype.knowledge_band`.
* Extra skills survive **only** when `archetype.allows_adjacent_strength` (today: `comp_first` alone), and then unclamped within 0–10.
* Scorecard items iterate the archetype, so invented ids vanish and weights are always the catalog's.
* Falsy model output falls back to archetype text rather than empty strings.

## `HumanTraitProfile` — the §3.2 taxonomy layer (`PERSONA_VERSION` "v1.1")

Optional, `None` on every persona cast before this layer existed. Orthogonal
to everything above: the archetype decides whether the candidate can do the
job; this decides how realistically, and how dangerously for an unprepared
interviewer. Entirely code-derived — composed by
`trait_dimensions.compose_human_traits(...)` from fixed presets, never
authored or seen by the model. Ten dimensions, matching the taxonomy exactly:

* `affect`, `verbal_style` — closed vocabularies validated by a `pattern=` on the field itself (e.g. affect: hostile/defensive/anxious/apathetic/over_eager/arrogant/cooperative/flirtatious_inappropriate/grieving_distressed).
* `fluency`, `literacy_level`, `native_speaker`, `accent_strength`, `code_switch_probability`, `vocabulary_ceiling` — language & literacy.
* `clarification_rate`, `misinterprets_question_rate`, `needs_rephrasing` — comprehension.
* `integrity_red_flags` — subset of resume_inflation/concealed_termination/ghost_employer/dual_employment/proxy_candidate/ai_assisted_answers, each validated against that vocabulary (a plain `list[str]` would silently accept typos — caught by `tests/test_trait_dimensions.py` and fixed with `Annotated[str, StringConstraints(pattern=...)]` list items).
* `motivation`, `negotiation_stance` — closed vocabularies.
* `compliance_traps` — subset of volunteers_protected_info/requests_off_policy_favour/asks_illegal_question_back, same list-item validation. `protected_info_type` (pregnancy/age/religion/caste/disability/marital_status) is **required** when `volunteers_protected_info` is present — `compose_human_traits` raises `ValueError` otherwise, because the compliance line silently drops from the compiled prompt without it.
* `environment: EnvironmentProfile` — camera_behavior, network_drops_at_minute, background_noise, joins_late_minutes, mobile_or_driving, hard_stop_minute.
* `seniority`, `function`, `region`, `gender_presentation`, `age_band`, `notice_period`, `offers_in_hand` — profile/identity fields, free text except `offers_in_hand` (int).

When present, it renders as a "REALISM & COMPLIANCE LAYER" section appended to
the compiled system prompt — see
[EngineContract](/concepts/contracts/engine-contract.md). When absent, the
compiled prompt is byte-identical to a persona cast before this field existed.

## Related

[agent.py](/concepts/modules/candidate-agent-agent.md) ·
[archetypes.py](/concepts/modules/candidate-agent-archetypes.md) ·
[Candidate agent § composing personas from presets](/concepts/subsystems/candidate-agent.md) ·
`owner_handover/candidate_output_schema.json`
