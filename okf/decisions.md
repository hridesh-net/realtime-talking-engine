---
type: Decisions
title: Active coordination decisions
description: Cross-agent decisions that constrain the current work packages.
resource: /okf/decisions
tags: [decisions, agents, hygiene]
generated:
  by: codex
  at: "2026-09-12"
status: draft
---
# Active coordination decisions

* Use the existing lowercase `okf/` bundle as the common workspace; do not
  create a parallel `OKF/` tree.
* Treat independent ASR as optional and non-fatal. When present it is the
  canonical human transcript; the Speaker transcript is the fallback, not a
  second copy of the utterance.
* Harness context is actor-owned, bounded, revision-aware, and supplied to the
  Thinker as a replacement snapshot. A late revision or note must not rewind
  or answer a newer conversation state.
* The snapshot is history only and its version is content-derived. The
  current question reaches the Thinker through `FeedPartial`; publishing it in
  the snapshot, or versioning interim revisions, makes every defer a cold call.
  Latency is the rule (the harness diagram): a republish of unchanged history
  must never disturb in-flight speculation.
* The Thinker is refreshed when the persona stops speaking (Window B), never
  while it speaks. `Reset` with the full ledger plus the new history snapshot
  happen there, so the next question streams into a Thinker already holding
  the right state.
* The Thinker's direction is requested on every turn, not only on DEFER: the
  speculation is already running, so the note is free. The verdict decides what
  the turn waits for — a confident turn waits at most its own pause and never
  stalls; a deferred turn waits a bounded grace, then buys time with a stall
  phrase, then falls back at the deadline. The stall phrase is the cover for a
  miss, not the path; this overrides the plan's "clip inside 50 ms of every
  defer".
* No fakes in production code. `internal/fakes` is the test-double set and
  nothing under `cmd/` or a production package imports it; a placeholder that
  ships is a placeholder nobody removes. The engine refuses to start without a
  real control-plane configuration rather than serving a sample persona.
* The engine's ingest is idempotent on the session id and the control plane
  replaces rather than appends; the portal passes its own session id to the
  engine so the recording and the transcript share one row.
* Vendor session shapes are verified live before they are believed. An offline
  WebSocket fake accepts whatever the adapter sends; only the vendor can reject
  a setup message, and it did.
* Keep runtime facts separate from repository facts. Global Headroom provider
  setup and persistent memory are operational state; tracked files document
  only the boundary and reproducible repository behavior.
* Never place secrets, raw environment values, recordings, transcripts, or
  identifying user data in OKF. Refer to variable names and sanitized behavior.
