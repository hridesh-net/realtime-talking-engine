---
type: Contract
title: InterviewExpectation
description: The deterministic document telling an interviewer what to cover, for how long, and how.
resource: /expectation_agent/schema.py
tags: [contract, expectation, rubric, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /expectation_agent/schema.py
  - resource: /expectation_agent/rubric.py
  - resource: /expectation_agent/agent.py
---
# InterviewExpectation

One per interview, `expectation_version = "v1.0"`, stored one-to-one and
regenerable (the save is an upsert on `interview_id`).

# Schema

```python
class InterviewExpectation(BaseModel):
    expectation_version: str = "v1.0"
    interview_id: str
    interview_type: str          # technical_coding|technical_discussion|behavioral|mixed
    structure: list[InterviewPhase]
    mandatory_skills: list[SkillExpectation]
    optional_skills: list[SkillExpectation] = []
    resume_probing: ResumeProbing
    behavioral_assessment: BehavioralAssessment
    red_flags: list[str]
    green_flags: list[str]
    evaluation_criteria: list[EvaluationCriterion]
    interviewer_guidance: InterviewerGuidance
    raw_model_output: dict | None = None      # not persisted

class InterviewPhase:      name, duration_minutes, mandatory, guidance
class SkillExpectation:    skill, priority(high|medium|low), min_duration_minutes,
                           assessment_method(live_coding|discussion|scenario|review),
                           evidence_to_look_for
class ResumeProbing:       required, focus_areas, sample_questions
class BehavioralAssessment: required, focus_areas, sample_questions
class EvaluationCriterion: name, weight, description
class InterviewerGuidance: dos, donts
```

`EXPECTATION_JSON_SCHEMA` in the same module is the JSON Schema handed to the
provider. **It and the Pydantic model must be edited together** — they are two
hand-maintained representations of one shape, with no test tying them.

## What the model cannot decide

Overwritten in `agent.generate` after the call
([determinism split](/concepts/determinism.md)):

| Field | Source |
|---|---|
| `interview_id` | passed in |
| `interview_type` | `determine_interview_type(experience_level, company_type)` |
| `evaluation_criteria` | the six fixed criteria, verbatim |
| `red_flags` / `green_flags` | baselines first, model additions appended without duplicates |
| `resume_probing.required` | `should_probe_resume(experience_level, has_resume)` |
| `interviewer_guidance` | `interviewer_guidance(experience_level, company_type)` |
| `structure` | replaced wholesale if the model's durations do not sum to `duration_minutes` |

## The six evaluation criteria

Fixed, weights summing to 1.00 (mirrors BRD §9):

| Criterion | Weight |
|---|---|
| `problem_solving` | 0.25 |
| `technical_depth` | 0.25 |
| `communication` | 0.15 |
| `system_design` | 0.15 |
| `cultural_fit` | 0.10 |
| `code_quality` | 0.10 |

## Gotchas

* `raw_model_output` is excluded on save and forced to `None` on load — do not rely on it surviving a round trip.
* `resume_probing.required` is currently always `False`, because the API passes `has_resume=False` unconditionally.
* Nothing validates that every `skills_required` entry appears in `mandatory_skills`/`optional_skills` — it is guardrail #3 in the prompt, checked only by the live scenario test, not by code.

## Related

[rubric.py](/concepts/modules/expectation-agent-rubric.md) — the tables ·
[agent.py](/concepts/modules/expectation-agent-agent.md) ·
`owner_handover/expectation_output_schema.json`
