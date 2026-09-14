---
type: Subsystem
title: Expectation agent
description: Turns a job spec into a deterministic interviewer plan — structure, skills, flags, criteria, guidance.
resource: /expectation_agent
tags: [expectation, agent, rubric, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: superseded
sources:
  - resource: /expectation_agent/agent.py
  - resource: /expectation_agent/rubric.py
  - resource: /expectation_agent/prompts.py
  - resource: /expectation_agent/schema.py
---
# Expectation agent

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


`expectation_agent/` — one model call turns a job spec into the document an
interviewer works from. Imports only `llm`.

| Module | Role |
|---|---|
| `agent.py` | [`InterviewExpectationAgent.generate(...)`](/concepts/modules/expectation-agent-agent.md) — pre-compute, call, overwrite |
| `rubric.py` | [The deterministic tables](/concepts/modules/expectation-agent-rubric.md) — phases, criteria, flags, guidance |
| `prompts.py` | `PERSONA`, `SYSTEM_GUARDRAILS` (10 numbered hard rules), `USER_PROMPT_TEMPLATE`, `build_user_prompt(...)` |
| `schema.py` | [`InterviewExpectation` + `EXPECTATION_JSON_SCHEMA`](/concepts/contracts/interview-expectation.md) |

## The shape of a call

1. **Pre-compute** — interview type, phase durations, the six criteria, baseline flags, resume-probing policy.
2. **Prompt** — all of the above is embedded in the user prompt as JSON, so the model is filling a form, not inventing one.
3. **Call** — `system = PERSONA + SYSTEM_GUARDRAILS`, schema-constrained, temperature 0.1.
4. **Overwrite** — every deterministic field is reassigned onto the raw dict, and the structure is replaced wholesale if durations do not sum correctly.
5. **Validate** — `InterviewExpectation.model_validate(raw)`, with `raw_model_output` attached for debugging (never persisted).

Steps 1 and 4 are the point: the guardrails tell the model what to do, and the
code makes it true regardless. See [the determinism split](/concepts/determinism.md).

## The persona and guardrails

Persona: a senior technical interview designer, *"pedantic about structure,
allergic to hallucination"*, who never invents skills not in the input.

Ten numbered hard rules, the load-bearing ones being: use only the provided
skills (no invented technologies or certifications); every `skills_required`
entry must appear in mandatory or optional skills; phase durations must sum to
the requested total; the six criteria must be exactly the provided ones with
exact weights; baseline flags must be included; no companies or brands absent
from the JD.

Note that rules 3 and 5 (skill coverage, `min_duration_minutes` ceiling) are
**not** re-enforced in code — unlike the others, they are checked only by the
live scenario test. If a model reliably drops skills, that is where to add a
code-side fix.

## What the model actually writes

Phase `guidance` text, the mandatory/optional skill split with priorities,
assessment methods and evidence-to-look-for, resume and behavioural focus areas
and sample questions, and role-specific additions to the flag lists.

## Testing

Offline: nothing directly — the agent has no unit test. The architecture suite
covers its injection and layering properties.
Live: `tests/test_expectation_agent.py`, five job-spec scenarios, run with
`scripts/check.sh --live`.
