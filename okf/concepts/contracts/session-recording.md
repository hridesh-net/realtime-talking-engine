---
type: Contract
title: Session recording
description: The browser-captured audio artifact for voice sessions — chunk protocol, channel layout, and the seam to the Go engine's future Recorder.
resource: /control_plane/database.py
tags: [contract, recording, audio, voice, storage, consent]
generated:
  by: claude-opus-5
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
status: stable
sources:
  - resource: /control_plane/database.py
  - resource: /control_plane/repository.py
  - resource: /control_plane/ports.py
  - resource: /control_plane/schemas.py
  - resource: /control_plane/api.py
  - resource: /ui/src/VoiceSessionView.jsx
  - resource: /ui/src/api.js
  - resource: /tests/test_recording.py
---
# Session recording

```python
class RecordingMeta(BaseModel):
    """The session's audio artifact. Bytes via GET /sessions/{id}/recording."""
    session_id: str
    status: str        # ^(recording|complete)$
    producer: str = "browser"    # ^(browser|engine)$
    mime_type: str
    byte_size: int      # ge=0
    next_seq: int        # ge=0
    channel_layout: str = "manager_left_candidate_right"
    created_at: datetime
    updated_at: datetime
    # NOTE: storage_key is deliberately NOT on this shape — see below.
```

`session_recordings` — one row per session, `session_id` **is** the primary key.
Bytes live outside SQLite: `RECORDINGS_DIR` on disk today (default `recordings`,
gitignored), an S3 object when the engine becomes a producer.

## Why the artifact's identity is the session, not the recording

There is exactly one recording per session, ever — no history of retakes, no
recording id of its own. `session_id PRIMARY KEY` on `session_recordings`
encodes that directly instead of leaving it to convention. This matters because
two producers will eventually write this table (see below): the identity has
to be stable across *who* produced the bytes, and "the session's recording" is
the stable thing, not "the browser's upload" or "the engine's file".

## Why the browser records this, not the Go engine

The obvious place for this to live is the Go engine's `Recorder`/`Finalizer`
ports (`engine/internal/ports/record.go`, `finalize.go`) — they exist for
exactly this. They were not used, because `engine/internal/record/` and
`engine/internal/store/s3/` are still `doc.go` stubs and **no audio flows
through `engined` today** (see [Live-session engine](/concepts/subsystems/engine.md)).
Wiring a recorder there would have recorded nothing — voice sessions run
entirely through the control plane's browser ↔ OpenAI Realtime path (see
[Realtime voice](/concepts/contracts/realtime-voice.md)), not through the engine.

The browser is the only place today where both halves of the call exist as
addressable audio: `ui/src/VoiceSessionView.jsx` already holds the manager's
mic `MediaStream` and the persona's remote WebRTC track (`pc.ontrack`), because
it has to route both to the `<audio>` element and the peer connection. Building
the recorder there means capturing audio that is actually flowing, at the cost
of trusting the browser to actually upload it — a trade made explicit in the
retry and partial-recording handling below.

## The forward seam: `producer`

`producer ∈ (browser, engine)`, default `browser`. This is not speculative — it
is the one column that makes today's shortcut not a dead end. When the engine's
`Finalizer` lands, it registers the **same row shape**, `producer='engine'`,
with an S3 `storage_key`. Same primary key, same `RecordingMeta` shape, same
`GET /sessions/{id}/recording` read path for the UI — nothing downstream of the
table needs to know which producer wrote it.

**Deliberately not built**: an engine-side registration endpoint for the
Finalizer to call. An endpoint with no caller is dead code, and nothing in
`engine/` writes audio yet. The seam is the table shape and the `producer`
column; the endpoint is the next producer's problem, not this change's.

## Channel layout is contract, not cosmetics

`channel_layout = 'manager_left_candidate_right'` (the only value written
today, but a real column rather than a hardcoded assumption because a second
producer might choose differently and the reader needs to know which it got).
`VoiceSessionView.jsx` builds it with a `ChannelMergerNode`: the manager's mic
feeds channel 0 (left), the persona's remote WebRTC track feeds channel 1
(right), merged into one `MediaStreamDestination` that `MediaRecorder` chunks.

This mirrors the engine `Recorder` port's own split, `WriteHuman` /
`WritePersona` — both producers keep the two speakers on fixed, well-known
channels rather than a single mixed-down track, so grading code that reads
"what did the manager say" versus "what did the persona say" from stereo
channels works the same regardless of which producer made the file.

A muted mic needs no special-casing: `track.enabled = false` renders silence
into Web Audio, so the recording honestly reflects the muted state rather than
needing a separate code path.

## The chunk protocol

```
POST /sessions/{id}/recording/chunks?seq=N     raw bytes body        -> 201 RecordingMeta
POST /sessions/{id}/recording/finalize          no body                -> 200 RecordingMeta
GET  /sessions/{id}/recording                   -> audio bytes, Content-Type: <stored mime_type>
```

* **`seq` must equal the recording's `next_seq`.** Enforced in
  `InterviewRepository.append_recording_chunk`, the same discipline as
  `append_turn`'s `MAX(idx) + 1` — ordering is the adapter's job, not the
  caller's. A mismatch is a **409**, not silently reordered or dropped.
* **`seq == 0` creates the row.** The chunk's `Content-Type` header becomes the
  stored `mime_type` for the whole recording — there is no separate "start
  recording" call.
* **Chunks are accepted while the recording is unfinalized, regardless of
  session status.** The last chunk legitimately lands around
  `POST /sessions/{id}/end`, as the browser flushes its `MediaRecorder` on
  hangup — gating on the *recording's* status keeps acceptance deterministic
  instead of racing session teardown.
* **No chunk lands once `status = 'complete'`** — also a 409. Same reasoning as
  `end_session`'s idempotency guard: a finalized artifact does not grow.
* **`finalize` is idempotent** — a second call returns the same `RecordingMeta`
  with `updated_at` unmoved (the `UPDATE` is `WHERE status = 'recording'`, so a
  no-op finalize is a true no-op, not a re-stamped one).
* **`GET .../recording` serves a partial recording too** — `status='recording'`
  is not a 404. A crashed or abandoned session leaves a real, playable partial
  file, and hiding it behind a 404 would make a crash look like "nothing was
  ever recorded" instead of "recording stopped partway", which is the honest
  and more useful answer.
* **Concurrency limit worth knowing** (same shape as `session_turns`): two
  chunks appended to one session at the same instant race on `next_seq`; the
  loser's `seq` no longer matches and raises. Correct for one browser tab
  uploading its own recording, not a design for multiple concurrent uploaders.

`RecordingStore` (narrow) and `RecordingWorkflowStore` (composed with
`SessionStore`, so the chunk handler can check `modality` before writing) are
the new ports — see [Storage ports](/concepts/contracts/storage-ports.md).

### Text sessions have no recording — by decision, not oversight

`POST .../chunks` on a `modality='text'` session is **409**, not silently
accepted and not a 404. There is no row and no empty file for a text session;
a recording never existed for it and the API says so the same way it says a
completed session cannot take new turns.

## Why `storage_key` is not on `RecordingMeta`

The row's `storage_key` (today, `"{session_id}.webm"` under `RECORDINGS_DIR`)
is server-internal — where the bytes happen to live is an implementation
detail of the current producer, not something a client should construct a path
from. Bytes are reached exactly one way, `GET /sessions/{id}/recording`, so the
public shape only needs to say a recording exists, at what size, and in what
state. This is why `owner_handover/session_recording_schema.json` also omits
it — `scripts/export_schemas.py` exports the Pydantic model, not the row.

## The browser upload path

`VoiceSessionView.jsx`: `MediaRecorder` on the merged stereo stream, `10s`
chunks (`recorder.start(10000)`), each `dataavailable` event chained onto a
dedicated promise queue (`chunkQueueRef`) so chunks POST in order even if one
is slow — the server's strict `seq` check would 409 the second of two
concurrent posts otherwise. Each POST retries **3×** with a short backoff
(`postChunkWithRetry`).

**On final failure, the client gives up deliberately** rather than drifting:
it stops the recorder, shows a one-time notice ("recording stopped early — the
part before the failure was saved"), and never posts again for that session.
The alternative — keep retrying against a `seq` the server has moved past — 
would only produce 409s and burn the recorder for nothing; what already landed
is a valid, playable partial, which is the better artifact to keep.

**Recording teardown never blocks the transcript.** `finish()` runs
`stopRecording().then(finalizeRecording)` as a fire-and-forget chain
alongside — not gating — the transcript-drain-then-`/end` sequence. A lost
recording must not cost the transcript; the transcript is the evaluation
layer's evidence, the recording is a nice-to-have review artifact.

Browsers without `MediaRecorder` support for `audio/webm;codecs=opus`
(`RECORDING_SUPPORTED` computed once at module load) skip all of this — the
interview proceeds, and the connecting screen says plainly that this browser
cannot record the call rather than silently producing nothing.

## Consent, retention, and where the bytes land — decisions, not defaults

* **The bytes never leave the control plane's own host.** `RECORDINGS_DIR`
  (default `./recordings`, gitignored) is local disk on the operator's machine.
  No new third party receives audio — the realtime vendor already carries the
  live call for the duration of the interview; the recorded copy is a second,
  separate upload that only ever reaches this service.
  See [Dev setup](/concepts/runbooks/dev-setup.md).
* **The connecting screen states plainly that the call is recorded and
  stored.** Proceeding past that screen is the consent event for this
  practice-tool use case — there is no separate consent flow, dialog, or
  opt-out.
* **Retention is indefinite. Deletion is manual.** Nothing purges
  `RECORDINGS_DIR` on a schedule or on session/interview deletion (and
  recall that FK cascades are not enforced in SQLite either — see
  [Database schema](/concepts/contracts/database-schema.md) — so a deleted
  session's recording row and file both survive it).
* **`GET /sessions/{id}/recording` has no auth**, like every other endpoint in
  this service. Gating one endpoint when the whole API is open would be
  theatre, not security — the fix, if this ever needs one, is auth on the API,
  not a special case here.

## Related

[Realtime voice](/concepts/contracts/realtime-voice.md) — the live media path
this recording is a side-channel to · [Storage ports](/concepts/contracts/storage-ports.md) ·
[Database schema](/concepts/contracts/database-schema.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[REST API](/concepts/contracts/rest-api.md) ·
[Live-session engine](/concepts/subsystems/engine.md) — where `producer='engine'`
will come from · [Test UI](/concepts/subsystems/ui.md)
