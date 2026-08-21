---
type: Subsystem
title: Test suite
description: Offline checks that enforce architecture and determinism, plus live scenario scripts that call the model.
resource: /tests
tags: [tests, pytest, architecture, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /tests/test_architecture.py
  - resource: /tests/test_candidate_rubric.py
  - resource: /tests/test_candidate_agent.py
  - resource: /tests/test_expectation_agent.py
---
# Test suite

Two kinds of test, and the distinction matters: the offline ones defend rules,
the live ones check model behaviour and cost money.

## Offline — run always

### `tests/test_architecture.py` (331 ln)

SOLID and layering as failing tests (BRD NFR-003). AST-based, parametrized over
every module. Full breakdown in [Architecture](/concepts/architecture.md).

The standout is `test_ocp_new_provider_needs_no_agent_change` /
`test_ocp_new_archetype_needs_no_agent_change`: they *register* a new provider
and archetype at runtime and prove the system absorbs them, rather than asserting
that extension is theoretically possible.

### `tests/test_candidate_rubric.py` (279 ln)

The real safety net for the persona pipeline. Groups:

* **Catalog integrity** — scorecard weights sum to 1.0 per archetype; archetypes are well-formed; exactly two defaults, one of each verdict; the catalog covers the intended space; the payload is serializable.
* **Determinism** — traits land inside archetype bounds; the same seed reproduces the same person; different interviews produce different people; `smartness_ratio` points the same direction as the verdict.
* **Clamping and repair** — the model cannot exceed the knowledge band; missing and renamed skills are restored; adjacent strength survives only where allowed.
* **Scorecard** — catalog ids and weights survive; model wording is used only when ids match.
* **Engine contract** — self-consistency (`min ≤ target ≤ max`, ceilings present); the system prompt carries the behavioural contract; **the system prompt is byte-stable**.
* **Validation** — resume claims reject bad truthfulness values.

## Live — `scripts/check.sh --live`

Run as scripts, not through pytest:

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

The candidate suite asserts verdicts and traits come from the catalog, knowledge
stays under the ceiling, every required skill is covered, names are unique within
a training set, and the same seed reproduces the same person. The expectation
suite validates each generated document against the guardrails — including the
two (skill coverage, `min_duration_minutes` ceiling) that code does *not*
re-impose.

## Gaps

* **No test touches `control_plane/api.py` or `repository.py` directly.** Routing, status codes, the 422 on unknown archetypes, the skip-unless-regenerate branch, and every SQL statement are uncovered. FastAPI's `TestClient` plus a `Depends` override would cover most of it cheaply.
* Nothing checks that `EXPECTATION_JSON_SCHEMA` matches `InterviewExpectation` — two hand-maintained representations of one shape.
* `expectation_agent/agent.py` has no offline test of its overwrite logic, which is where its determinism guarantee actually lives.
* No JS tests for `ui/`.
