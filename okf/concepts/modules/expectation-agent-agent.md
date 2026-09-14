---
type: Module
title: expectation_agent/agent.py
description: Pre-compute, call the model, overwrite — how the expectation stays deterministic.
resource: /expectation_agent/agent.py
tags: [expectation, agent, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: superseded
sources:
  - resource: /expectation_agent/agent.py
---
# expectation_agent/agent.py

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


157 lines.

# Schema

```python
class InterviewExpectationAgent:
    DEFAULT_TEMPERATURE = 0.1
    def __init__(self, model: StructuredModel | None = None)   # built from config if None
    @property def model(self) -> str                            # model_id, recorded on output
    async def generate(self, interview_id, job_title, jd, skills_required,
                       job_location_type, experience_level, company_type,
                       duration_minutes, mode="live_interview",
                       has_resume=True) -> InterviewExpectation
    async def _call_model(self, prompt) -> dict
```

Note `generate` takes **positional** arguments (unlike the candidate agent's
keyword-only signature) and `has_resume` defaults to `True` — but the API passes
`False` explicitly.

## The three phases of `generate`

**1. Pre-compute** (L64–70) — `interview_type`, `phases`, `criteria`,
`red_flags`, `green_flags`, `resume_required`. All from
[`rubric.py`](/concepts/modules/expectation-agent-rubric.md).

**2. Prompt and call** (L72–104) — the computed values are serialized into the
user prompt as indented JSON, so the model sees the criteria, flags and phase
skeleton it must reproduce. System turn is `PERSONA + SYSTEM_GUARDRAILS`; schema
is `EXPECTATION_JSON_SCHEMA`.

**3. Overwrite** (L106–145) — the deterministic fields are written back onto the
raw dict:

```python
raw["interview_id"]  = interview_id
raw["interview_type"] = interview_type
raw["evaluation_criteria"] = criteria
raw["red_flags"]   = red_flags   + [f for f in raw.get("red_flags", [])   if f not in red_flags]
raw["green_flags"] = green_flags + [f for f in raw.get("green_flags", []) if f not in green_flags]
raw["resume_probing"]["required"] = resume_required
raw["interviewer_guidance"] = interviewer_guidance(...)
```

Then: if the model's `structure` durations do not sum to `duration_minutes`, the
entire structure is replaced with a template carrying fixed guidance strings.

Finally `InterviewExpectation.model_validate(raw)`, with `raw_model_output`
attached afterwards for debugging.

## Gotchas

* **`raw["resume_probing"]["required"] = ...` assumes the key exists.** A model that omits `resume_probing` raises `KeyError`, not a validation error. It is in the schema's `required` list, so this holds in practice — but it is an unguarded assumption, unlike every other line in the block.
* The flag merge preserves order (baselines first) and de-duplicates by identity — a model rephrasing a baseline flag adds a near-duplicate rather than replacing it.
* Guardrails #3 (every required skill appears) and #5 (`min_duration_minutes` ceiling) are **not** re-imposed in code; only the live scenario test checks them.
* `mode` is passed into the prompt but never used in any deterministic decision.
* The agent has no offline unit test — its overwrite logic, which is where the determinism guarantee actually lives, is only exercised live.
