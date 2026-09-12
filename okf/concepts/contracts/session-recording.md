---
type: Contract
title: Session recording
description: The browser-captured audio-and-video artifact for voice sessions — chunk protocol, channel layout, retention, and the seam to the Go engine's future Recorder.
resource: /control_plane/database.py
tags: [contract, recording, audio, video, voice, storage, consent, retention]
generated:
  by: claude-opus-5
  at: "2026-09-12T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-12T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T18:00:00Z"
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
  - resource: /tests/test_portal_compat.py
---
# Session recording

> **In flight (2026-09-10): the bytes are moving to an object store.**
> `control_plane/object_store.py` now exists — a port with a filesystem adapter
> (the no-S3 default) and an S3 adapter, tested against a real MinIO. See
> [Storage ports](/concepts/contracts/storage-ports.md).
>
> **Nothing on this page has changed yet.** `repository.py` still writes chunks
> straight to `RECORDINGS_DIR` with an append. (Reading is no longer the way it
> was: `open_recording` returns the spool **path**, and nothing loads a whole
> recording into memory any more — see below.) The chunk → spool → finalize state
> machine that S3 needs — S3 objects cannot be appended to, so chunks must land
> in `SPOOL_DIR` and be uploaded once at finalize — is **designed, not built**,
> and lands with the next work package. Read the chunk protocol below as what
> runs today, not as what will run after the switch.

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

## The container may carry a video track (2026-09-12)

The manager's **camera** rides in the same recording. The producer is the
SkillBrew portal's session screen (a separate repo); the `ui/` console described
below stays audio-only, and the control plane accepts either without knowing
which it got. There is no second artifact, no second endpoint and no schema
change: one `MediaRecorder` is fed
the camera track plus the existing merged stereo audio, so the stored
`mime_type` becomes **`video/webm;codecs=vp8,opus`** instead of
`audio/webm;codecs=opus`, and everything else — the row, the chunk protocol, the
`seq` discipline, `RecordingMeta` — is untouched. `seq == 0` storing whatever
`Content-Type` arrived is what makes this a client-side change; the control
plane has never validated it and still does not.

**Channel semantics are unchanged.** Measured, not assumed: a VP8+Opus WebM from
a single `MediaRecorder` keeps **two Opus channels** with the left/right split
intact, and `pan=mono|c0=cN` separates them cleanly four minutes into a 400 s
clip (440 Hz left vs 880 Hz right, nine orders of magnitude apart). Manager left,
persona right, exactly as `channel_layout` claims. **The camera never enters Web
Audio** — it is a track handed to the recorder, not a node in the merger graph.

**What the analysis path does with it.** Nothing, deliberately. `cut()` transcodes
each window to WAV (`-ac 2 -ar 16000`), and the WAV muxer selects no video
stream, so the video is dropped without anyone asking. The one place it mattered
is `duration_ms`'s decode fallback, which now passes **`-vn`**: it skips decoding
45 minutes of camera footage, and it pins the reported length to the *audio* by
construction, so a camera that starts before the mic and stops after it cannot
stretch the window plan past the end of what the model is given. See
[Audio analysis agent](/concepts/subsystems/analysis-agent.md).

**Size.** About **190 MB per session-hour** (350 kbps VP8 plus the Opus), against
~30 MB/h for audio alone — a 6× jump, and the reason `GET .../recording` and the
analyse endpoint no longer read the file into memory (below). The API host's data
volume is 20 GB and also holds the SQLite database, so it takes roughly 100
session-hours to fill; see the note in `infra/README.md`.

**Playing it back** is decided from the stored mime: `video/…` renders a
`<video>`, anything else an `<audio>`. `SessionSummary.has_recording` is still a
bare boolean and carries no mime, so a *list* view cannot know which it is — it
offers a download, not a player.

## Serving it: a path, not bytes (2026-09-12)

`RecordingStore.read_recording` (returned `bytes`) has been **replaced** by
`open_recording(session_id) -> (RecordingMeta, Path) | None`. There was exactly
one reason it returned bytes — nothing needed anything better at ~30 MB an hour —
and video removed it.

* `GET /sessions/{id}/recording` is a Starlette **`FileResponse`**, streamed off
  disk, with `content_disposition_type="inline"` set explicitly because
  Starlette defaults to `attachment` and this endpoint has always served inline.
  `FileResponse` also answers a `Range` request with a **206** and a
  `Content-Range`, which is what lets a `<video>` probe and seek instead of
  downloading the whole session first. (Seeking stays imprecise: `MediaRecorder`
  WebM has no cues. Exact seeking would need a remux, which is not done.)
* The **analyse** endpoint hands the agent the spool path itself. It used to
  write a scratch copy to `tempfile.gettempdir()/analysis-{id}.webm` that nothing
  ever deleted — harmless at audio sizes, an hour of video written twice and
  leaked at these. Safe because nothing in this service moves, renames or prunes
  a recording (see the retention decision below), so the path stays valid for the
  length of the background task.

When recordings move to the object store, `ObjectStore.open()` returns a stream
rather than a path and the range handling moves with them; `open_recording`
changes shape then. That is the planned seam, named here so it is not a surprise.

## The chunk protocol

```
POST /sessions/{id}/recording/chunks?seq=N     raw bytes body        -> 201 RecordingMeta
POST /sessions/{id}/recording/chunks?seq=N     multipart, field "chunk" -> 201 RecordingMeta
POST /sessions/{id}/recording/finalize          no body                -> 200 RecordingMeta
GET  /sessions/{id}/recording                   -> the file, Content-Type: <stored mime_type>,
                                                   Content-Disposition: inline, Range-capable (206)
```

* **`seq` must equal the recording's `next_seq`.** Enforced in
  `InterviewRepository.append_recording_chunk`, the same discipline as
  `append_turn`'s `MAX(idx) + 1` — ordering is the adapter's job, not the
  caller's. A mismatch is a **409**, not silently reordered or dropped.
* **`seq == 0` creates the row.** The chunk's `Content-Type` becomes the
  stored `mime_type` for the whole recording — there is no separate "start
  recording" call.
* **Two body shapes, one protocol (2026-09-10).** The console posts the
  `MediaRecorder` blob as the raw body and the *request's* `Content-Type` is
  what seq 0 stores. A `multipart/form-data` body with a file field named
  `chunk` is accepted too, and then the *part's* content type is what is
  stored. The multipart door exists because the SkillBrew portal's shared axios
  layer can send JSON or multipart and nothing else; the handler branches on the
  request's content type only to read the bytes, so the seq ordering, the 409s
  and the 422 are one code path for both producers — two clients writing the
  same recording table must not be able to disagree about when a chunk is
  acceptable. An empty part is the same **422** as an empty raw body; a
  multipart body with no `chunk` field is a 422 as well.
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
  stored** — microphone *and*, on the portal, camera. Proceeding past that
  screen is the consent event for this practice-tool use case — there is no
  separate consent flow, dialog, or opt-out.
* **Retention is indefinite. Deletion is manual. This was re-decided on
  2026-09-12, with the camera in the frame, and it is the answer to the gate in
  [Interview record](/concepts/contracts/interview-record.md)** — *"do not wire a
  camera to it without a retention decision"*. The owner's decision: recordings,
  **now including video of a named employee's face**, are kept indefinitely and
  deleted by hand. This is not the pre-video policy carried over by inertia; it
  was put to the owner as a choice between saying so explicitly and setting a
  retention period (which would need a purge job), and "indefinite, manual" was
  chosen. Nothing purges `RECORDINGS_DIR` on a schedule or on session/interview
  deletion (and recall that FK cascades are not enforced in SQLite either — see
  [Database schema](/concepts/contracts/database-schema.md) — so a deleted
  session's recording row and file both survive it). `object_store.py`
  deliberately has no `delete` for the same reason. **If that ever changes, the
  purge job is the change** — there is no retention field, no expiry column and
  no lifecycle rule to flip.
* **The camera is unconditional on a voice session, and independent of
  `proctoring`.** It is not gated on a setting; the manager either grants the
  camera or the call proceeds audio-only. `proctoring` was never wired to it —
  see [Interview record](/concepts/contracts/interview-record.md).
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
