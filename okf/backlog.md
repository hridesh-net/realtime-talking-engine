---
type: Backlog
title: Active coordination backlog
description: Verified follow-ups for the current cross-agent work packages.
resource: /okf/backlog
tags: [backlog, agents, verification]
generated:
  by: claude-fable-5-1
  at: "2026-09-12"
status: draft
---
# Active coordination backlog

* Run `engined` against a running control plane with
  `CONTROL_PLANE_SHARED_SECRET` set on both sides: create a session through
  the engine with a portal-opened `session_id`, stop it, and confirm the
  control plane's session shows the engine's transcript and `modality: voice`.
  Then take the control plane down mid-session and confirm the spool file
  appears and drains on the next `engined` start.
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
* Verify deployment configuration separately from local `.env`; never treat a
  local CORS fix as proof of deployed portal reachability.
* Decide whether global Headroom setup needs a reproducible, repository-owned
  bootstrap document. Do not copy machine credentials, persistent memory, or
  global configuration into the repository.
