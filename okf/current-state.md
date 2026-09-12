---
type: CurrentState
title: Current implementation state
description: Concise cross-agent handoff for active repository and runtime work.
resource: /okf/current-state
tags: [handoff, current-state, agents]
generated:
  by: claude-fable-5-1
  at: "2026-09-12"
status: draft
---
# Current implementation state

This page is a short-lived coordination aid, not a replacement for [Project
Overview](/concepts/project-overview.md) or the subsystem pages. Verify dirty
worktree facts before editing because several work packages are currently
uncommitted.

## Repository work in progress

* **Portal/CORS:** the control plane has opt-in `CORS_ALLOWED_ORIGINS`; the local
  environment has been configured to unblock the portal. The behavior is
  implemented and documented, while a developer's `.env` value is local runtime
  configuration and must not be copied into tracked documentation.
* **Context harness — Phase 1 (done, uncommitted):** actor-owned, bounded,
  revision-keyed transcript context in `session/harness_context.go`. The
  snapshot published to the Thinker is history only (finalized turns before the
  current one) and its version is content-derived, so interim ASR revisions do
  not move it.
* **Independent OpenAI ASR — Phase 2a (done, live-verified, uncommitted):**
  `vendors/openaitx` uses the GA `session.update` shape; the beta shape Codex
  first wrote is rejected by the vendor. Constructed in `engined` only when
  `ASR_MODEL_ID` and `OPENAI_API_KEY` are both set; failure is non-fatal and
  falls back to the Speaker transcript with `degraded:asr`.
* **Thinker context guard — Phase 2b (done, corrected, uncommitted):** the
  Thinker keeps its speculation when the republished history is unchanged and
  abandons it when the history changed. The actor discards notes whose turn or
  *history* version is stale — not whose interim revision counter is.
* **Window B (done, uncommitted):** `closePersonaTurn` now calls
  `refreshThinker` — `Reset` with the full ledger and a fresh history snapshot —
  on `ResponseDone`, barge-in and clip playout. `Reset` had never been called.
* **Latency rule and Window A on every turn (done, uncommitted):** the stall
  path exists now (`beginStall`, STALLING, `PickStall` returns the phrase);
  a deferred turn waits a bounded grace for a ready note before covering with a
  clip; a confident turn takes the note inside its own pause or answers alone.
  The Speaker's transcript feeds the pre-gate and Thinker live on the degraded
  path.
* **Control-plane seam (done, uncommitted):** `internal/controlplane` is the
  real `ContractSource` (fetch + ingest with retry, idempotency key and disk
  spool); `engined` no longer imports `internal/fakes` and the
  `-dev-sample-contract` flag is gone from the binary, the systemd unit and
  Terraform. The control plane gained `POST /sessions/{id}/ingest`, the
  `IngestStore` port, `session_ingests` (SQLite DDL + Postgres `0002`), and a
  bearer-token gate on both engine routes. Neither side has been run against
  the other over the network yet.
* **Degraded-path fix (done, uncommitted):** the interviewer's utterance is
  cleared once a turn ends; on the Speaker-transcript path nothing else ever
  cleared it, so every later question's record carried every earlier one.

Verification on 2026-09-12: gofmt, vet, build, `go test -race ./...`, the
layering test and golangci-lint are clean; the `openaitx` live test passed
against the vendor. **Not yet done**: `engined` run end to end with ASR
configured against a browser.

These bullets describe the visible working tree on 2026-09-12; they are not a
claim that the changes are committed, deployed, or fully verified.

## Runtime state outside this repository

Headroom is installed globally as a deployment provider for both Claude and
Codex, with persistent memory enabled. That is machine/runtime state, not an
artifact in this repository: no provider installation, global configuration,
or memory content should be inferred from a checkout or reproduced here. Only
repository-owned integration documentation belongs in this bundle.
