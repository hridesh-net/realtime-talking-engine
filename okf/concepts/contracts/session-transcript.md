---
type: Contract
title: Session transcript
description: A live interview and its server-stamped turns — the artifact the evaluation layer will read and the voice engine will emit.
resource: /control_plane/schemas.py
tags: [contract, session, transcript, turn, evaluation]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T17:05:00Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /control_plane/schemas.py
  - resource: /control_plane/api.py
  - resource: /control_plane/database.py
---
# Session transcript

```python
class Turn(BaseModel):
    index: int          # ge=0, position in the transcript
    speaker: str        # ^(manager|candidate)$
    text: str
    at: datetime        # server-stamped
    elapsed_ms: int     # ge=0, since session start

class SessionCreateRequest(BaseModel):     # POST /api/v1/sessions
    interview_id: str
    archetype: str
    planned_minutes: int = 20              # ge=5, le=45
    modality: str = "text"                 # ^(text|voice)$

class TranscriptAppendRequest(BaseModel):  # POST /sessions/{id}/transcript
    speaker: str                           # ^(manager|candidate)$
    text: str                              # min_length=1

class RealtimeCredentialResponse(BaseModel):   # POST /sessions/{id}/realtime
    session_id, client_secret, expires_at, model, call_url, voice
    # NOTE: no `instructions` field, by design — see Realtime voice.

class TurnRequest(BaseModel):              # POST /api/v1/sessions/{id}/turns
    text: str                              # min_length=1

class SessionResponse(BaseModel):
    id, interview_id, candidate_id, persona_key, candidate_name
    status: str        # ^(live|completed|abandoned)$
    modality: str      # ^(text|voice)$ — "text" today
    planned_minutes: int
    started_at: datetime
    ended_at: datetime | None
    opening_line: str
    turns: list[Turn]
```

Exported to `owner_handover/session_create_schema.json`,
`session_output_schema.json`, `session_realtime_schema.json`, and
`session_transcript_append_schema.json`.

## `manager`, not `interviewer`

The speaker enum is `manager|candidate` even though Phase 1 still runs on the
old interview/job-spec domain model. Under
[BRD v3](/references/brd.md) the person being assessed is the **hiring
manager**; naming the speaker now means the evaluation layer, the report, and
every stored transcript never need a rename.

For the same reason `interview_id` is expected to become `role_id` when the job
card replaces the job spec (pivot plan Phase 2). Everything else on this page —
turns, timestamps, modality, status — is already the final shape.

## Why the clock is server-side

`at` and `elapsed_ms` are assigned by the repository from the session's stored
`started_at`; no client supplies them. The transcript is evidence — the
evaluation layer counts time-to-first-question, longest monologue, and abrupt
endings off these numbers, and two managers' sessions are only comparable if one
clock produced both.

`elapsed_ms` is clamped at 0, so a backwards system clock degrades to a
zero-offset turn rather than a negative one.

## Turn 0 is always the persona's opening line

`create_session` writes the session row and turn 0 in the same transaction, with
`elapsed_ms = 0`, using `EngineContract.opening_line`. The opening line is
contract data, chosen when the persona was cast — not generated at session
start. A transcript that did not begin with what the persona actually said would
misreport time-to-first-question for every manager.

## `modality`

`"text"` or `"voice"`, chosen at `POST /sessions` and fixed for the session's
life. It changes two things about the record:

| | `text` | `voice` |
|---|---|---|
| Turn 0 | written by the repository from `opening_line` | **absent** — the persona says it, and the browser reports it back |
| Who writes turns | `POST /turns` (server generates the reply) | `POST /transcript` (browser reports what was said) |

Both produce the same `Turn` shape with the same server-stamped clock, which is
the point — the evaluation layer reads one transcript format.

The voice-only signals the pivot plan §5 names (WPM, interruptions, silence
handling, filler density) are **not yet extracted** even in voice sessions: what
lands here is the transcript, not the timing telemetry the Go
[live-session engine](/concepts/subsystems/engine.md) will emit. The report is
expected to say "not measurable" rather than record a fake zero — for now that
applies to both modalities.

## `status`

`live` → `completed` via `POST /sessions/{id}/end`. `abandoned` exists in the
enum and the CHECK constraint but nothing sets it yet; there is no timeout
sweep. The `end_session` update is guarded on `status = 'live'`, so re-ending is
idempotent and does not move `ended_at`.

## Related

[REST API § Sessions](/concepts/contracts/rest-api.md) ·
[Realtime voice](/concepts/contracts/realtime-voice.md) ·
[Storage ports](/concepts/contracts/storage-ports.md) ·
[Database schema](/concepts/contracts/database-schema.md) ·
[Run an interview](/concepts/runbooks/run-an-interview.md)
