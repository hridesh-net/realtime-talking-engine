---
type: Contract
title: Storage ports
description: Five narrow persistence protocols and five compositions, depended on instead of the SQLite adapter.
resource: /control_plane/ports.py
tags: [contract, ports, isp, dip, protocol]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /control_plane/ports.py
  - resource: /control_plane/api.py
---
# Storage ports

> **Seven narrow ports now.** `AnalysisStore` joined them with the audio
> analysis; `AnalysisWorkflowStore` deliberately does **not** compose the report
> store, because a handler that can both analyse and report will eventually do
> both by accident.
>
> **Six narrow ports now, not five.** `ReportStore` joined them with the
> session report — see [Report engine](/concepts/subsystems/report-engine.md).

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

class SessionStore(Protocol):
    def create_session(self, *, interview_id: str, candidate_id: str, persona_key: str,
                       planned_minutes: int, opening_line: str,
                       modality: str = "text") -> SessionResponse
    def get_session(self, session_id: str) -> SessionResponse | None
    def append_turn(self, session_id: str, speaker: str, text: str) -> Turn
    def end_session(self, session_id: str, status: str = "completed") -> SessionResponse | None
    def list_sessions(self, interview_id: str) -> list[SessionSummary]

class RecordingStore(Protocol):
    def append_recording_chunk(self, session_id: str, seq: int, mime_type: str,
                               data: bytes) -> RecordingMeta
    def finalize_recording(self, session_id: str) -> RecordingMeta | None
    def get_recording_meta(self, session_id: str) -> RecordingMeta | None
    def read_recording(self, session_id: str) -> tuple[RecordingMeta, bytes] | None

class ExpectationWorkflowStore(InterviewStore, ExpectationStore, Protocol): ...
class EnrollmentStore(InterviewStore, ExpectationStore, CandidateStore, Protocol): ...
class SessionWorkflowStore(InterviewStore, ExpectationStore, CandidateStore,
                           SessionStore, Protocol): ...
class TurnWorkflowStore(CandidateStore, SessionStore, Protocol): ...
class RecordingWorkflowStore(SessionStore, RecordingStore, Protocol): ...
```

## Why `SessionStore` assigns the turn index and the clock

`append_turn` takes only `(session_id, speaker, text)`. The index, the wall
time, and the elapsed offset are computed inside the adapter, from the stored
`started_at`. That is deliberate: the transcript is the evaluation layer's
evidence, so its ordering and its time base belong to one place that cannot be
argued with by a caller — or by a client clock.

`TurnWorkflowStore` deliberately **excludes** `InterviewStore`. The busiest
endpoint in the system has no business depending on job-spec storage. It also
serves the voice credential-minting route, which needs exactly the same two
things: the persona's contract, and the session.

`list_sessions` lives on `SessionStore` even though its route is nested under
an interview. The handler never reads the interview — the session row already
carries `interview_id` — so widening to a composition would buy nothing and
break the ISP discipline. It returns `SessionSummary`, not `SessionResponse`:
the transcript is the evaluation layer's evidence and does not belong in a list
payload.

`modality` defaults to `"text"` so every existing caller is unchanged, and it
does more than label the row — `create_session` writes turn 0 only for text
sessions. See [Session transcript](/concepts/contracts/session-transcript.md).

## `RecordingStore` — the same ordering discipline as `SessionStore`

`append_recording_chunk` takes `seq` from the caller but enforces it against
the recording's own `next_seq`, the same shape as `append_turn`'s server-owned
index: the caller proposes, the adapter is the one place that can be trusted
not to reorder or duplicate. `RecordingWorkflowStore` composes `SessionStore`
in, not `InterviewStore` — the chunk handler needs the session (to check
`modality` before accepting bytes for a text session), never the interview.
See [Session recording](/concepts/contracts/session-recording.md) for the full
chunk protocol.

## Which route uses which

| Route | Port | Why |
|---|---|---|
| create / get / list interviews | `InterviewStore` | reads or writes interviews only |
| `GET .../expectation` | `ExpectationStore` | read only |
| `POST .../expectation` | `ExpectationWorkflowStore` | reads the interview, writes the expectation |
| `POST .../candidates` | `EnrollmentStore` | reads interview + expectation, reads and writes candidates |
| candidate reads / delete | `CandidateStore` | |
| `POST /sessions` | `SessionWorkflowStore` | reads the interview and its expectation, reads-or-writes the persona, opens the session |
| `POST /sessions/{id}/turns` | `TurnWorkflowStore` | reads the persona's contract, writes turns |
| `POST /sessions/{id}/end`, `GET /sessions/{id}` | `SessionStore` | sessions only |
| `POST /sessions/{id}/realtime` | `TurnWorkflowStore` | reads the persona's contract to compile the voice session |
| `POST /sessions/{id}/transcript` | `SessionStore` | writes a turn; generates nothing |
| `GET /interviews/{id}/sessions` | `SessionStore` | lists sessions; despite the path it never touches interview storage |
| `POST /sessions/{id}/recording/chunks` | `RecordingWorkflowStore` | checks the session's `modality`, then appends a chunk |
| `POST /sessions/{id}/recording/finalize`, `GET /sessions/{id}/recording` | `RecordingStore` | recording only — no session check, the recording either exists or does not |

Depending on the narrowest port is the ISP discipline, and it is tested: ports
must stay small and **non-overlapping** (no shared method names), and the SQLite
adapter must satisfy every one of them via `isinstance` against an in-memory
connection.

## Rules when editing

* **Compose, never widen.** If a handler needs two ports, add a composition like `EnrollmentStore` — do not add candidate methods to `InterviewStore`. The overlap test will fail, and correctly.
* Return `None` for "not found"; only `delete_candidate` returns a bool. Handlers translate that into a 404.
* Keep methods synchronous. The adapter is `sqlite3`; async routes call it directly, which is fine at this scale but is the thing to revisit alongside the per-request connection.
* Ports import from `candidate_agent`, `expectation_agent`, and `control_plane.schemas` for type annotations — allowed, since `control_plane` sits above both agents.
