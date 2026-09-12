---
type: Architecture
title: Architecture
description: Four layers, a one-way dependency rule, and the executable tests that enforce both.
resource: /tests/test_architecture.py
tags: [architecture, layering, solid, ports-and-adapters]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: claude-opus-5/architecture-rules
    at: "2026-09-10T00:00:00Z"
status: stable
sources:
  - resource: /tests/test_architecture.py
  - resource: /control_plane/ports.py
  - resource: /llm/base.py
  - resource: /README.md
---
# Architecture

Ports and adapters, four packages, dependencies pointing one way.

```
        ┌────────────────────────────────────────────────────────┐
        │ control_plane/   FastAPI routes, storage                │
        │   api.py → ports.py ← repository.py (SQLite)            │
        └───┬──────────────┬───────────────────┬─────────────────┘
            │ imports      │ imports           │ imports
        ┌───▼──────────┐ ┌─▼────────────────┐ ┌▼─────────────────┐
        │ expectation_ │ │ candidate_agent/ │ │ evaluation_agent/│
        │ agent/       │ │                  │ │                  │
        └───┬──────────┘ └─┬────────────────┘ └┬─────────────────┘
            │ imports      │ imports           │ imports
        ┌───▼──────────────▼───────────────────▼─────────────────┐
        │ llm/ Structured + Chat + Realtime + adapters            │
        │          ← the ONLY place a vendor SDK appears          │
        └────────────────────────────────────────────────────────┘
```

`ALLOWED_IMPORTS` in `tests/test_architecture.py` is the machine-readable form:

```python
{"llm": set(),
 "expectation_agent": {"llm"},
 "candidate_agent": {"llm"},
 "evaluation_agent": {"llm"},
 "control_plane": {"llm", "expectation_agent", "candidate_agent", "evaluation_agent"}}
```

The three agents are **siblings, not peers in a chain** — none imports another.
`control_plane` composes them. This is why `candidate_agent.RUBRIC_CRITERIA`
re-declares the rubric criterion ids instead of importing them from
`evaluation_agent`: the archetypes need the vocabulary, and a sibling import to
get it would be the first crack in the rule. A control-plane test asserts the
two lists agree.

## The rules, and where each is enforced

Every principle below is a *failing test*, not a review convention. All of them
run offline in `tests/test_architecture.py` (704 lines, AST-based) — with no
database, no container and no network, so they are the checks that still run on
the machine where everything else is unavailable.

| Principle | Rule | How it fails |
|---|---|---|
| **DIP** | Vendor SDKs (`google`, `openai`, `google.genai`) only inside `llm/` | AST import scan over every module in every package |
| **DIP** | Agents accept an injected model and never read provider credentials | Signature inspection + source scan for `os.getenv`/`API_KEY` |
| **DIP** | Storage drivers (`psycopg`, `psycopg_pool`, `boto3`, `botocore`, `sqlite3`) only inside `control_plane/{database,repository,migrate,object_store}.py` | AST import scan over every module in every package, against a named adapter allowlist |
| **DIP** | Handlers type against ports, never `InterviewRepository` **or** an object store | Parameter annotations in `control_plane/api.py`, unparsed and matched against the banned concretions |
| **ISP** | Every narrow port — Interview, Expectation, Candidate, Session, Recording, Analysis, Report — stays small (≤ 5 methods) and non-overlapping | Method-count and set-intersection checks per protocol |
| **ISP** | `StructuredModel`, `ChatModel` and `RealtimeBroker` stay separate ports | None subclasses another; none exposes another's method |
| **ISP** | The repository adapter satisfies every port, narrow and composed | `runtime_checkable` isinstance against an uninitialised instance — conformance is a property of the class, so no connection is opened |
| **LSP** | Every `StructuredModel`, `ChatModel` and `RealtimeBroker` shares its base signature, implements the whole contract, and constructs identically | Signature comparison across all five adapters |
| **LSP** | Every archetype honours the same shape | Parametrized over the whole catalog |
| **OCP** | A new archetype or provider flows through with no agent edit | The test **registers one at runtime** and proves it works |
| **OCP** | `REALTIME_PROVIDERS` names only known providers, each with a realtime model id — a *documented subset*, not a mirror of the text tables | Subset assertion, with the reason in the docstring |
| **SRP** | An agent generates and never persists: no storage driver, no `control_plane` | The driver scan above plus `ALLOWED_IMPORTS` — the two together replaced a narrower check that named only `sqlite3` |
| **SRP** | Prompt modules perform no I/O; schema modules hold no logic | AST scan for calls / function defs |
| **Layering** | No package imports one above it | `ALLOWED_IMPORTS` |
| **Layering** | No relative imports anywhere | AST scan for `ImportFrom` with `level > 0` (also banned by ruff `TID`) |

The OCP test is the one worth reading — it does not assert that extension is
*possible*, it performs the extension and checks the system absorbed it.

## Storage ports

`control_plane/ports.py` defines `typing.Protocol` classes — structural, so
`InterviewRepository` neither imports nor subclasses them. Four narrow ports
plus two compositions:

* `InterviewStore` — `create`, `get`, `list`
* `ExpectationStore` — `save_expectation`, `get_expectation`
* `CandidateStore` — `save_candidate`, `list_candidates`, `get_candidate`, `get_candidate_by_archetype`, `delete_candidate`
* `ExpectationWorkflowStore` = Interview + Expectation
* `EnrollmentStore` = Interview + Expectation + Candidate

Compositions are built **from** the narrow ports rather than widening any of
them, so each stays independently implementable. Each route depends on the
smallest port it needs — see [Storage ports](/concepts/contracts/storage-ports.md).

## The model port

`llm.base.StructuredModel` is an ABC with one method, `generate_json(*, system,
prompt, schema) -> dict`, and three guarantees implementations must honour:
return a parsed dict (never a string, never None); apply `system` as a
system-level instruction rather than prepending it to the user turn; raise
`ModelError`, never a provider-specific exception. Substitutability depends on
all three — see [StructuredModel](/concepts/contracts/structured-model.md).

## Where the boundary is weakest

`control_plane/api.py`'s `get_repo()` calls `init_db()` per request, opening a
new SQLite connection each time. The code says so: *"In production this should
be a connection-pool dependency."* It is the one place the adapter leaks into
request handling.
