---
type: Backlog
title: Active coordination backlog
description: Verified follow-ups for the current cross-agent work packages.
resource: /okf/backlog
tags: [backlog, agents, verification]
generated:
  by: claude-fable-5-1
  at: "2026-09-12"
verified:
  - by: claude-fable-5-1
    at: "2026-09-13"
status: draft
---
# Active coordination backlog

Everything here was verified against the tree at commit `4280481` on
2026-09-13. Items are grouped by what unblocks them; none is speculative.

## Runtime verification still owed (the code exists, the run has not happened)

* Run `engined` against a running control plane with
  `CONTROL_PLANE_SHARED_SECRET` set on both sides: create a session through
  the engine with a portal-opened `session_id`, stop it, and confirm the
  control plane's session shows the engine's transcript and `modality: voice`.
  Then take the control plane down mid-session and confirm the spool file
  appears under `SPOOL_DIR/ingest` and drains on the next `engined` start.
* Run `engined` end to end with `ASR_MODEL_ID` and `OPENAI_API_KEY` set,
  against the portal's session tab, and confirm in the event log that
  `pumpTranscriberPartials` delivers revisions, `utterance_end` comes from the
  ASR final (no `degraded_end_of_turn`), `thinker_context_refreshed` fires after
  each persona turn, and a deferred turn's note is served by the speculative
  call rather than the stall-clip fallback. The adapter and the actor seams are
  each verified; the wiring between them across a real session is not.
* Listen to the stall grace (50–350 ms after the persona's pause) and the
  confident-path note window in a real session; the bounds are reasoned, not
  measured, and the diagram's "milliseconds" target is only checkable live.
* Tune the OpenAI `server_vad` boundary (silence duration) once real interviewer
  pauses have been observed; the vendor's default decides end-of-turn today.
* Re-verify the deployed instance (`infra/README.md`): `engined` has never
  started successfully there, and the mode it used to need is gone. Both env
  files need `CONTROL_PLANE_SHARED_SECRET` (bootstrap writes it). Never treat
  a local CORS fix as proof of deployed portal reachability.

## Code follow-ups the log already committed to

* **Wire the object store.** `control_plane/object_store.py` has no caller;
  `repository.py` still appends chunks straight to `RECORDINGS_DIR` and the
  chunk → spool → finalize state machine S3 needs is the "next work package"
  named on 2026-09-10. `SPOOL_DIR` is read by `database.spool_dir()` and used
  by nothing on the Python side.
* **Switch `repository.py` to Postgres.** The schema, pool and migration runner
  exist; the request path still runs on SQLite through `init_db`.
* **Drop the `proctoring` column** (interview config). Written, stored, read by
  nothing since the camera became unconditional on 2026-09-12. Needs a
  migration, a console change and a schema re-export — do it as one change.
* **Engine-side recording.** `record`, `store/s3` and `transcriptlog` are
  still `doc.go`; the actor writes to the `Recorder` port but `engined`
  constructs none, so nothing from an engine-run session is graded.
  `vendors/judgellm` is written and tested but unwired.

## Housekeeping

* *(2026-09-13: the `.env.example` comment, the stale package README, the
  tracked `graphify-out/`, the unignored `.serena/` and the inert cost cap
  were all resolved — see log.md. Only the item below remains.)*
* Decide whether global Headroom setup needs a reproducible, repository-owned
  bootstrap document. Do not copy machine credentials, persistent memory, or
  global configuration into the repository.
