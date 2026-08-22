---
type: Convention
title: Conventions
description: The explicit lint and type rule set, docstring style, and the rules that are tests rather than conventions.
resource: /pyproject.toml
tags: [conventions, ruff, mypy, style]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /pyproject.toml
  - resource: /tests/test_architecture.py
---
# Conventions

## Explicit, not default

`pyproject.toml` selects the ruff rule set by name rather than inheriting
whatever the default drifts to. Selected: `E`/`W` (pycodestyle), `F` (pyflakes),
`I` (import order), `N` (naming), `UP` (py311 idioms), `B` (bugbear), `C4`,
`SIM`, `RET`, `ARG`, `PTH` (pathlib over os.path), `TID` (bans relative
imports), `RUF`, `ANN` (public API must be typed), `D` (docstrings, Google
convention).

Ignored, each for a stated reason: `D203`/`D213` (conflict with `D211`/`D212`),
`D401` (imperative mood too rigid for domain docstrings), `ANN401` (`Any` is
legitimate for model payloads), `D107` (`__init__` documented on the class).

Per-file: `control_plane/api.py` allows `B008` (FastAPI's `Depends()` default is
the framework's calling convention); `tests/*` and `scripts/*` relax docstring
and annotation rules.

Line length **100**, target **py311**, `ui/` excluded.

## Types

mypy over `control_plane`, `expectation_agent`, `candidate_agent`,
`evaluation_agent`, `llm` with
`disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`,
`no_implicit_optional`, `warn_unreachable`, `warn_unused_ignores`, plus the
pydantic plugin. Only `google.*`, `openai.*`, `dotenv.*` are allowed missing
stubs.

## Style in practice

* `from __future__ import annotations` at the top of every module.
* Frozen dataclasses for the catalog, `TypedDict` for fixed spec blobs, Pydantic for anything crossing the API, `Protocol` for ports.
* Keyword-only arguments (`*`) on the wide constructor-like functions — `generate_json`, `agent.generate`, `build_engine_contract`.
* Docstrings explain the constraint, not the mechanics. Module docstrings carry the design rationale; that is where the reasoning for a file lives.
* Comments mark the load-bearing lines — `# clamp — the ceiling is ours`, `# The expectation grounds personas in the flags the interviewer is watching for.`

## Rules that are tests, not conventions

These will fail the build, not a review ([Architecture](/concepts/architecture.md)):

1. Vendor SDKs only inside `llm/`.
2. Agents take an injected model; they never read API keys.
3. Handlers depend on ports, never on `InterviewRepository`.
4. Agents never import `sqlite3` or `control_plane`, and never persist.
5. Prompt modules do no I/O; schema modules hold no logic.
6. Ports stay small and non-overlapping.
7. No package imports one above it; no relative imports anywhere.

## Determinism rules

Before touching either agent, read [the determinism split](/concepts/determinism.md).
The short version: if a field affects comparability between training sessions or
fairness between candidates, it belongs in code, and the agent must re-impose it
after the model call rather than trusting the prompt.

## Contract hygiene

Any change to `VirtualCandidate`, `EngineContract`, `InterviewExpectation`,
`InterviewResponse`, or `CandidateEnrollRequest` requires regenerating
`owner_handover/` (`scripts/export_schemas.py`). `check.sh` fails otherwise.
