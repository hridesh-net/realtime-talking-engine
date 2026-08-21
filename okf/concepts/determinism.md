---
type: Principle
title: The determinism split
description: What code owns and what the model may author — the organizing rule of this repository.
resource: /
tags: [determinism, reproducibility, guardrails, core-idea]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /candidate_agent/agent.py
  - resource: /expectation_agent/agent.py
  - resource: /candidate_agent/archetypes.py
  - resource: /expectation_agent/rubric.py
---
# The determinism split

Read this before changing either agent. Both are built the same way, and the
split is the reason the output is trustworthy.

> The model fills in the blanks. It cannot move the walls.

## Why

Two independent requirements force it:

1. **Comparability.** Training reports only mean something if two interviewers can be measured against *the same candidate*. If the persona drifts between sessions, the comparison is noise.
2. **Fairness / auditability.** An expectation whose criteria and weights the model can rewrite per run is not a rubric — it is a suggestion. Fixed criteria applied identically to every interview for a role is the defensible position.

## Candidate agent

| Owned by code | Owned by the model |
|---|---|
| Which archetype | The person's name, headline, background, years |
| The verdict (`select`/`reject`/`borderline`) | `verdict_rationale`, written against the real skills |
| Every trait score, drawn from the archetype's bounds by a seeded RNG | Talking points, breaking points, wrong beliefs |
| The knowledge band (skill-level ceiling) | Where inside the band each skill sits (then clamped) |
| Scorecard signal ids and weights | The wording of each signal, grounded in this job |
| Speech spec (pace, verbosity, filler/hesitation, formality, interrupts) | Verbal tics and sample phrases |
| Answer policy defaults (depth, on-unknown, on-pressure, on-silence) | `reveals_depth_when`, `always_does`, `never_does` |
| The compiled engine contract and system prompt | `opening_line` |
| Resume-claim truthfulness enum validation | The claims themselves |

Enforcement is not by prompt alone — the agent **re-imposes** the code side after
the call:

* `_build_knowledge_map` clamps every level into `archetype.knowledge_band` and restores any required skill the model dropped or renamed.
* `_build_scorecard` iterates `archetype.must_discover`, so invented ids are silently discarded and weights always come from the catalog.
* `_stance` and `ResumeClaim.truthfulness` reject out-of-enum values.
* Trait scores never touch the model at all — `derive_traits` seeds `random.Random` from `SHA256(seed)`.

## Expectation agent

Computed before the call and **overwritten after** it in `agent.generate`:

* `interview_type` — from `(experience_level, company_type)`.
* `evaluation_criteria` — the six fixed criteria and weights, verbatim.
* `red_flags` / `green_flags` — baselines first, model additions appended (deduped).
* `resume_probing.required` — from `(experience_level, has_resume)`.
* `interviewer_guidance` — from `(experience_level, company_type)`.
* `structure` — if the model's phase durations do not sum to the requested total, the whole structure is replaced with the template.

Temperature is **0.1**; the candidate agent runs at **0.35** because personas
need texture and everything reproducible is computed outside the model anyway.

## The two fingerprints

Both are SHA256 over a sorted-key JSON payload, and they answer different
questions:

| | `seed_fingerprint` | `fingerprint` |
|---|---|---|
| Covers | seed, archetype, catalog/persona versions, traits, verdict | all of the above **plus** name, background, knowledge levels, stances, system prompt |
| Stable across a re-cast? | **Yes** | No |
| Answers | "is this the same person?" — the reproducibility claim | "has this stored persona changed underneath my training set?" — the integrity claim |

`candidate_id` is `vc-<sha256(seed)[:12]>`, so the same `(interview, archetype)`
always yields the same id — which is what makes the storage upsert idempotent.

## When you change something here

Bump the version constant that covers it — `CATALOG_VERSION`,
`PERSONA_VERSION`, `ENGINE_CONTRACT_VERSION`, or `expectation_version` — because
both fingerprints include the version fields, and the Go engine pins the
contract version. Changing the compiled prompt text without bumping
`ENGINE_CONTRACT_VERSION` silently invalidates every stored persona's byte
stability, which `tests/test_candidate_rubric.py::test_system_prompt_is_byte_stable`
exists to catch.
