---
type: Contract
title: Storage ports
description: Three narrow persistence protocols and two compositions, depended on instead of the SQLite adapter.
resource: /control_plane/ports.py
tags: [contract, ports, isp, dip, protocol]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /control_plane/ports.py
  - resource: /control_plane/api.py
---
# Storage ports

`typing.Protocol`, `@runtime_checkable`, **structural** — `InterviewRepository`
neither imports nor subclasses them. Swapping SQLite for Postgres means writing
a class with matching methods; no route changes.

# Schema

```python
class InterviewStore(Protocol):
    def create(self, req: InterviewCreateRequest) -> InterviewResponse
    def get(self, interview_id: str) -> InterviewResponse | None
    def list(self, status: str | None = None) -> list[InterviewResponse]

class ExpectationStore(Protocol):
    def save_expectation(self, expectation: InterviewExpectation, model_used: str) -> None
    def get_expectation(self, interview_id: str) -> InterviewExpectation | None

class CandidateStore(Protocol):
    def save_candidate(self, candidate: VirtualCandidate, model_used: str) -> None
    def list_candidates(self, interview_id: str) -> list[VirtualCandidate]
    def get_candidate(self, candidate_id: str) -> VirtualCandidate | None
    def get_candidate_by_archetype(self, interview_id: str, archetype: str) -> VirtualCandidate | None
    def delete_candidate(self, candidate_id: str) -> bool

class ExpectationWorkflowStore(InterviewStore, ExpectationStore, Protocol): ...
class EnrollmentStore(InterviewStore, ExpectationStore, CandidateStore, Protocol): ...
```

## Which route uses which

| Route | Port | Why |
|---|---|---|
| create / get / list interviews | `InterviewStore` | reads or writes interviews only |
| `GET .../expectation` | `ExpectationStore` | read only |
| `POST .../expectation` | `ExpectationWorkflowStore` | reads the interview, writes the expectation |
| `POST .../candidates` | `EnrollmentStore` | reads interview + expectation, reads and writes candidates |
| candidate reads / delete | `CandidateStore` | |

Depending on the narrowest port is the ISP discipline, and it is tested: ports
must stay small and **non-overlapping** (no shared method names), and the SQLite
adapter must satisfy every one of them via `isinstance` against an in-memory
connection.

## Rules when editing

* **Compose, never widen.** If a handler needs two ports, add a composition like `EnrollmentStore` — do not add candidate methods to `InterviewStore`. The overlap test will fail, and correctly.
* Return `None` for "not found"; only `delete_candidate` returns a bool. Handlers translate that into a 404.
* Keep methods synchronous. The adapter is `sqlite3`; async routes call it directly, which is fine at this scale but is the thing to revisit alongside the per-request connection.
* Ports import from `candidate_agent`, `expectation_agent`, and `control_plane.schemas` for type annotations — allowed, since `control_plane` sits above both agents.
