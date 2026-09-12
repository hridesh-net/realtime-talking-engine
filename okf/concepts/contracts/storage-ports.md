---
type: Contract
title: Storage ports
description: Seven narrow row-storage protocols and their compositions, plus the object-store port for bytes — depended on instead of the adapters.
resource: /control_plane/ports.py
tags: [contract, ports, isp, dip, protocol, object-store, s3]
generated:
  by: claude-opus-5
  at: "2026-09-12T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-12T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T18:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /control_plane/ports.py
  - resource: /control_plane/api.py
  - resource: /control_plane/object_store.py
  - resource: /tests/test_object_store.py
---
# Storage ports

> **The object store is new (2026-09-10)** and is *not* one of these seven —
> it holds bytes, not rows, and lives in `control_plane/object_store.py`. It is
> documented at the bottom of this page. Nothing calls it yet: wiring it into
> `repository.py` and the recording routes is the next work package.
>
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
    def create_session(self, *, interview_id: str, candidate_id: str, archetype: str,
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
    def open_recording(self, session_id: str) -> tuple[RecordingMeta, Path] | None

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

**`open_recording` returns a path, not bytes (2026-09-12).** It replaced
`read_recording`, which returned `tuple[RecordingMeta, bytes]`; that method is
gone, not deprecated — after the change it had no caller and no test, and a port
method nobody calls is the kind of thing a future adapter dutifully implements
for nothing. The reason is the recording now carries the manager's camera,
roughly 190 MB a session-hour: `GET .../recording` streams it with a
`FileResponse` (which also answers `Range`) and the analyse endpoint hands the
path straight to ffmpeg, so neither pulls a whole recording through this
process's heap. Note the asymmetry with `append_recording_chunk`, which still
takes `bytes` — a 10 s chunk is ~500 KB and arrives as a request body already.

This is the one port method that will change shape again when recordings move to
`ObjectStore`: `open()` returns a `ByteSource` stream, not a path, and the range
answer moves to the store (a presigned or ranged GET). Named here so the next
change is a planned step and not a surprise.

## `IngestStore` — the one port that writes a transcript whole

`store_ingest(ingest, *, archetype, opening_line, planned_minutes)` is one
method on purpose. The Go engine's turn table is the time base of a voice
session the way `SessionStore` is for a text one, so the engine's `start_ms`
becomes `elapsed_ms` and its timestamps come from the engine's `started_at`,
not from this side's clock. One transaction creates the session row (engine-
minted id) or closes the one the portal opened (its id passed to the engine),
replaces `session_turns`, and upserts `session_ingests` with the raw payload.
A repeat with the same `session_id` replaces everything and reports
`duplicate=true`; a repeat naming a different interview or persona raises
`IngestConflictError`, which the handler turns into 409.

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
| `POST /sessions/{id}/ingest` | `IngestWorkflowStore` | reads the interview and the persona, then writes the whole session in one call — deliberately **not** `SessionStore`, whose turn indexing and clock belong to text sessions |
| `GET /interviews/{id}/sessions` | `SessionStore` | lists sessions; despite the path it never touches interview storage |
| `POST /sessions/{id}/recording/chunks` | `RecordingWorkflowStore` | checks the session's `modality`, then appends a chunk |
| `POST /sessions/{id}/recording/finalize`, `GET /sessions/{id}/recording` | `RecordingStore` | recording only — no session check, the recording either exists or does not |

Depending on the narrowest port is the ISP discipline, and it is tested: ports
must stay small and **non-overlapping** (no shared method names), and the SQLite
adapter must satisfy every one of them via `isinstance` against an in-memory
connection.

# The object store — the same discipline, for bytes

`control_plane/object_store.py`, added 2026-09-10. Rows have had a port since
the beginning; the recording's *bytes* did not, and `repository.py` wrote them
straight to `RECORDINGS_DIR` with an `open(...).write()`. This is the port that
replaces that, and the reason it is separate from `RecordingStore` is that the
two things fail differently: a row write is a transaction, a byte write is a
transfer that can be resumed, retried, or spooled.

```python
class ByteSource(Protocol):
    size: int
    content_type: str
    def read(self, start: int = 0, end: int | None = None) -> Iterator[bytes]: ...

@runtime_checkable
class ObjectStore(Protocol):
    def put(self, key: str, source: Path, *, content_type: str) -> None: ...
    def open(self, key: str) -> ByteSource | None: ...   # None == no such object
```

**`put` takes a filesystem path and `open` returns a stream — neither takes or
returns `bytes`.** An hour of stereo Opus is not something the API process
should be asked to hold, and the moment one method's signature says `bytes`
every caller downstream inherits that. `upload_file` streams parts from disk;
`shutil.copyfile` streams; `read` yields 1 MiB at a time.

`content_type` is on `ByteSource` as well as on `put` so the round trip is the
same on both adapters — the filesystem one records it in a sibling
`<name>.content-type` file, which is why keys ending in that suffix are refused
by **both** adapters.

**There is no `delete`.** Retention is manual by decision (see
[Session recording](/concepts/contracts/session-recording.md)), so a `delete`
would have no caller — and dead code in a storage adapter is the kind someone
wires up later without reading the retention decision.

## The two adapters

| | `FilesystemObjectStore(root)` | `S3ObjectStore(bucket, *, region, prefix, endpoint, force_path_style)` |
|---|---|---|
| When | `S3_BUCKET` unset — the dev default, **not** a test fake | `S3_BUCKET` set; `S3_ENDPOINT` + `S3_FORCE_PATH_STYLE` point it at MinIO |
| `put` | `shutil.copyfile` into `root/key`, parents created, plus the content-type sidecar | `upload_file` with `ContentType`; boto3 splits above its own 8 MiB threshold |
| `open` | `None` unless the file exists; ranges by `seek` | `head_object` for size and type; ranges by `get_object(Range=...)` + `iter_chunks` |
| Credentials | n/a | **boto3's default chain, never read here** — the same rule as an agent taking an injected model |

`object_store_from_env()` chooses between them. The *bucket* is the switch
rather than a separate `OBJECT_STORE_BACKEND`, so "S3 without a bucket" and
"disk with one" cannot be written down, let alone need a runtime error.

## Range semantics — decided once, identical in both

Both adapters go through one `_resolve_range`, because a port whose two
implementations disagree at the edges is worse than no port: the disagreement
only shows up in the environment you did not test.

* **Inclusive at both ends**, like HTTP Range. `read(4, 8)` is five bytes.
* **`end` past the last byte is clamped**, not an error — a caller asking for "a megabyte from here" at the tail of a recording wants the tail.
* **`start` at or beyond the end reads nothing** — an empty iterator, not an exception. HTTP would answer 416, but that is the *handler's* decision; the port's answer is "there are no bytes there". S3 really does raise `InvalidRange` for this, so the S3 adapter uses the size it already has and never sends the request.
* **A negative bound raises.** In HTTP's grammar a negative offset means "from the end"; nothing here needs suffix ranges, and quietly reading -1 as 0 would hide a caller's bug.
* Keys are validated identically: `/`-joined non-empty segments, no leading or trailing `/`, no `.`/`..` (which the filesystem adapter would resolve against the host and write outside its root), and nothing ending in the sidecar suffix.

## Key layout is shared with the Go engine

Callers pass `sessions/{session_id}/recording.webm`; the S3 adapter prepends
`S3_PREFIX`. That is deliberate: the engine's Finalizer writes `audio.wav`,
`transcript.jsonl` and `events.jsonl` under the same
`{prefix}/sessions/{session_id}/` (`docs/ENGINE_IMPLEMENTATION_PLAN.md` §9), so
one session's artifacts sit together whichever process produced them.

## Two facts worth not re-deriving

* **A `head_object` 404 does not prove the object is missing.** A HEAD reply has
  no body, so botocore has no error code and a missing *bucket* arrives as the
  same bare `404` as a missing key (measured against MinIO). `open` therefore
  confirms with `head_bucket` before returning `None` and raises otherwise —
  without that, a wrong or undeployed bucket reads as "no session has a
  recording", silently, for every session at once.
* **boto3's multipart threshold is 8 MiB, not S3's 5 MiB part minimum.** The
  suite uploads 9 MiB and asserts the ETag carries a part count (`<hex>-2`),
  which is the only evidence that `put` really took the multipart path rather
  than that a default was assumed.

`tests/test_object_store.py` is one behavioural set parametrized over both
adapters, with the S3 half against a **real MinIO** — never a stub, and never
skipped when MinIO is missing (the fixture raises, the suite goes red).

## Rules when editing

* **Compose, never widen.** If a handler needs two ports, add a composition like `EnrollmentStore` — do not add candidate methods to `InterviewStore`. The overlap test will fail, and correctly.
* Return `None` for "not found"; only `delete_candidate` returns a bool. Handlers translate that into a 404.
* Keep methods synchronous. The adapter is `sqlite3`; async routes call it directly, which is fine at this scale but is the thing to revisit alongside the per-request connection.
* Ports import from `candidate_agent`, `expectation_agent`, and `control_plane.schemas` for type annotations — allowed, since `control_plane` sits above both agents.
