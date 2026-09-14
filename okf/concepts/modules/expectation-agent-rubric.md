---
type: Module
title: expectation_agent/rubric.py
description: The code-defined tables the expectation model may not override — phases, criteria, flags, guidance.
resource: /expectation_agent/rubric.py
tags: [rubric, determinism, expectation, tables]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: superseded
sources:
  - resource: /expectation_agent/rubric.py
---
# expectation_agent/rubric.py

> **SUPERSEDED 2026-09-13.** `expectation_agent/` was deleted from the tree,
> together with its two endpoints, its `interview_expectations` table, the
> `ExpectationStore` / `ExpectationWorkflowStore` ports and
> `tests/test_expectation_agent.py`. It existed to generate a *per-interview
> rubric from a JD*, which is exactly what BRD v3 forbids: the rubric is fixed
> configuration, not generated content (pivot plan Phase 2, task 7).
>
> This page is kept, not deleted, because the design decisions in it are the
> ones the replacement was argued against. **Read it as history.** What is live
> now: [evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md)
> for the four fixed competencies,
> [evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md)
> for the per-interview items and the agent that drafts them, and
> [Interview record](/concepts/contracts/interview-record.md) for where they are
> stored. `determine_interview_type` moved into `evaluation_agent/rubric.py`
> unchanged — it was the only thing this package computed that anything still
> read.


172 lines, no imports beyond `__future__`. Pure data and pure functions — this is
the file to edit when interview *policy* changes.

# Schema

```python
PHASE_TEMPLATE: dict[str, dict[int, list[int]]]   # level -> duration -> [intro, tech, q, close]
DEFAULT_PHASES = [5, 45, 5, 5]
EVALUATION_CRITERIA: list[dict]                   # the six fixed criteria
BASE_RED_FLAGS: list[str]                         # 4
BASE_GREEN_FLAGS: list[str]                       # 4

def phase_durations(experience_level, duration_minutes) -> list[int]
def determine_interview_type(experience_level, company_type) -> str
def should_probe_resume(experience_level, has_resume) -> bool
def skill_priority(skill, experience_level, company_type) -> str
def min_skill_duration(skill_count, technical_minutes) -> int
def interviewer_guidance(experience_level, company_type) -> dict[str, list[str]]
```

## Phase durations

Exact templates for 30 / 45 / 60 minutes per level. Junior and mid are identical;
senior differs only at 45 min (`[5,35,4,3]` vs `[5,33,4,3]`, i.e. 47 total vs 45
— **the senior 45-minute row does not sum to 45**). Any other duration scales
`DEFAULT_PHASES` linearly with `max(1, round(x * duration/60))`, which also does
not guarantee an exact sum.

This matters because `agent.generate` compares the model's structure total
against `duration_minutes` and replaces it with the template on mismatch — so a
template that itself mis-sums produces a document that fails its own guardrail #4.
An unknown `experience_level` silently falls back to the `mid` template.

## Interview type

```
junior                    -> technical_coding
mid    + startup          -> technical_coding
mid    + (anything else)  -> mixed
senior + startup          -> technical_discussion
senior + (anything else)  -> mixed
```

`behavioral` is allowed by the schema but this function never returns it.

## The six criteria

`problem_solving` .25, `technical_depth` .25, `communication` .15,
`system_design` .15, `cultural_fit` .10, `code_quality` .10. Sum 1.00. Mirrors
BRD §9. Changing a weight changes every future expectation and invalidates
comparisons with past ones.

## Resume probing

`has_resume and experience_level != "junior"`. The API currently passes
`has_resume=False` always, so this is always `False` in practice.

## Flags

Four baseline red, four baseline green — trade-off articulation, ownership,
testing discipline, scale estimation; and *why* not just *what*, observability,
clarifying questions, concrete incidents. The agent puts these first and appends
the model's role-specific additions.

## Unused

`skill_priority` and `min_skill_duration` are **defined but never called** — the
model assigns priorities and durations from the prompt instead. Either wire them
in (they are the deterministic version of what the model is guessing) or delete
them; leaving them looks like enforcement that is not happening.
