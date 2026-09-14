---
type: CurrentState
title: Current implementation state
description: Concise cross-agent handoff for active repository and runtime work.
resource: /okf/current-state
tags: [handoff, current-state, agents]
generated:
  by: claude-fable-5-1
  at: "2026-09-13"
status: draft
---
# Current implementation state

This page is a short-lived coordination aid, not a replacement for [Project
Overview](/concepts/project-overview.md) or the subsystem pages. It describes
the tree at commit `4280481` (2026-09-12, "Engine build"); the worktree was
clean apart from untracked tool directories when this was written on
2026-09-13. **Staged, uncommitted, the same day**: the OKF audit and four
approved cleanups — the cost cap removed (variable, Go field, Python
vocabulary, migration `0003`), the `.env.example` database comment corrected,
`graphify-out/` and `.serena/` ignored, `control_plane/README.md` deleted.
`scripts/check.sh`: 28 gates PASS, live SKIP by design.

## Everything below is committed

The work packages that the 2026-09-12 entries in [log.md](/log.md) describe
as "uncommitted" landed in `4280481`. Nothing is staged or pending:

* **Context harness — Phase 1:** actor-owned, bounded, revision-keyed
  transcript context in `engine/internal/session/harness_context.go`. The
  snapshot published to the Thinker is history only and its version is
  content-derived, so interim ASR revisions do not move it.
* **Independent OpenAI ASR — Phase 2a (live-verified):** `vendors/openaitx`
  uses the GA `session.update` shape. Constructed in `engined` only when
  `ASR_MODEL_ID` and `OPENAI_API_KEY` are both set; failure is non-fatal and
  falls back to the Speaker transcript with `degraded:asr`.
* **Thinker context guard — Phase 2b:** speculation survives a republished,
  unchanged history and is abandoned when the history changed; a note is
  discarded on a stale turn or *history* version, never on an interim revision.
* **Window B:** `closePersonaTurn` refreshes the Thinker (`Reset` with the
  full ledger, then a fresh history snapshot) on `ResponseDone`, barge-in and
  clip playout.
* **Latency rule and Window A on every turn:** the stall path exists
  (`beginStall`, STALLING, `PickStall` returns the phrase); a deferred turn
  waits a bounded grace for a ready note before covering with a clip; a
  confident turn takes the note inside its own pause or answers alone. The
  Speaker's transcript feeds the pre-gate and Thinker live on the degraded path.
* **Control-plane seam:** `engine/internal/controlplane` is the real
  `ContractSource` (fetch + ingest with retry, idempotency key and disk
  spool); `engined` no longer imports `internal/fakes` and the
  `-dev-sample-contract` flag is gone from the binary, the systemd unit and
  Terraform. The control plane has `POST /sessions/{id}/ingest`, the
  `IngestStore` port, `session_ingests` (SQLite DDL + Postgres `0002`, narrowed by `0003`), and a
  bearer-token gate on both engine routes.
* **Video in the session recording (control-plane half):** the browser's
  camera rides in the same WebM, same chunk protocol, same row;
  `open_recording` replaced `read_recording`; the recording is served as a
  `FileResponse` with `Range` support; retention is indefinite by decision.
* **Session clock bound:** `MAX_INTERVIEW_MINUTES = 180` is the one ceiling
  for both `duration_minutes` and `planned_minutes`.

Verification on 2026-09-12: `scripts/check.sh` green (Python gates, the
Postgres and MinIO gates under Apple `container`, gofmt/vet/build/`go test
-race`/arch/golangci-lint); the `openaitx` live test passed against the vendor.

## Not yet verified — see the backlog

Nothing in the list above has been run **across the network** between the two
processes, nor end to end with ASR configured against a browser, nor on the
deployed instance since the sample-contract mode was removed. The exact
observations to make are in [Backlog](/backlog.md). Treat those as the first
task of any new requirement that touches a voice session.

## Runtime state outside this repository

Headroom is installed globally as a deployment provider for both Claude and
Codex, with persistent memory enabled. That is machine/runtime state, not an
artifact in this repository: no provider installation, global configuration,
or memory content should be inferred from a checkout or reproduced here. Only
repository-owned integration documentation belongs in this bundle.
