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
        ┌──────────────────────────────────────────────┐
        │ control_plane/   FastAPI routes, storage      │
        │   api.py → ports.py ← repository.py (SQLite)  │
        └───────┬───────────────────────┬───────────────┘
                │ imports               │ imports
        ┌───────▼──────────┐   ┌────────▼─────────┐
        │ expectation_     │   │ candidate_agent/ │
        │ agent/           │   │                  │
        └───────┬──────────┘   └────────┬─────────┘
                │ imports               │ imports
        ┌───────▼───────────────────────▼───────────────┐
        │ llm/ Structured + Chat + Realtime + adapters   │
        │         ← the ONLY place a vendor SDK appears  │
        └───────────────────────────────────────────────┘
```

`ALLOWED_IMPORTS` in `tests/test_architecture.py` is the machine-readable form:

```python
{"llm": set(),
 "expectation_agent": {"llm"},
 "candidate_agent": {"llm"},
 "control_plane": {"llm", "expectation_agent", "candidate_agent"}}
```

The two agents are **siblings, not peers in a chain** — neither imports the
other. `control_plane` composes them.

## The rules, and where each is enforced

Every principle below is a *failing test*, not a review convention. All of them
run offline in `tests/test_architecture.py` (331 lines, AST-based).

| Principle | Rule | How it fails |
|---|---|---|
| **DIP** | Vendor SDKs (`google`, `openai`, `google.genai`) only inside `llm/` | AST import scan over every module in every package |
| **DIP** | Agents accept an injected model and never read provider credentials | Signature inspection + source scan for `os.getenv`/`API_KEY` |
| **DIP** | Handlers type against ports, not `InterviewRepository` | `control_plane/api.py` must not annotate the SQLite adapter |
| **ISP** | `InterviewStore` / `ExpectationStore` / `CandidateStore` / `SessionStore` stay small and non-overlapping | Method-count and set-intersection checks per protocol |
| **ISP** | `StructuredModel`, `ChatModel` and `RealtimeBroker` stay separate ports | None subclasses another; none exposes another's method |
| **ISP** | The SQLite adapter satisfies every port | `runtime_checkable` isinstance against an in-memory connection |
| **LSP** | Every `StructuredModel`, `ChatModel` and `RealtimeBroker` shares its base signature, implements the whole contract, and constructs identically | Signature comparison across all five adapters |
| **LSP** | Every archetype honours the same shape | Parametrized over the whole catalog |
| **OCP** | A new archetype or provider flows through with no agent edit | The test **registers one at runtime** and proves it works |
| **OCP** | `REALTIME_PROVIDERS` names only known providers, each with a realtime model id — a *documented subset*, not a mirror of the text tables | Subset assertion, with the reason in the docstring |
| **SRP** | Agents never import `sqlite3` or `control_plane`; generation does not persist | Import scan |
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
