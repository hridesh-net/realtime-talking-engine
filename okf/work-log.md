---
type: WorkLog
title: Cross-agent work log
description: Short append-only handoffs for active work; detailed history remains in log.md.
resource: /okf/work-log
tags: [work-log, handoff, agents]
generated:
  by: codex
  at: "2026-09-12"
verified:
  - by: claude-fable-5-1
    at: "2026-09-13"
status: draft
---
# Cross-agent work log

Use one dated bullet per handoff: scope, files or subsystem affected, checks
run, and remaining risk. Keep durable implementation history in
[log.md](/log.md); this page is deliberately concise.

## 2026-09-12

* Established the shared coordination pages inside the existing `okf/` bundle.
  Captured the visible CORS, context-harness, independent-ASR, and Thinker
  snapshot/version-guard work without claiming that dirty-tree changes are
  committed or deployed. Recorded global Headroom provider/memory setup only as
  external runtime state and copied no configuration values or memory content.
* Took over the harness work from Codex. Live-tested `vendors/openaitx`: the
  beta session shape was rejected outright, moved it to the GA `session.update`
  form and it transcribes (setup ~1 s, verbatim final, stable item id). Fixed
  the context guard so interim revisions no longer abandon the Thinker's
  speculation or discard its note; added Window B (`refreshThinker` on persona
  close — `Reset` had no caller); cleared the utterance at end-of-turn on the
  degraded path. gofmt/vet/build/`go test -race`/arch/golangci-lint clean.
  Remaining risk: no end-to-end `engined` run with ASR configured yet. Updated
  [engine](/concepts/subsystems/engine.md), [test-suite](/concepts/subsystems/test-suite.md),
  [checks](/concepts/runbooks/checks.md), [project-overview](/concepts/project-overview.md).
* Second pass against `docs/LIVE_TALKING_ENGINE_HARNESS.drawio`: the stall
  clip was never played (no `PickStall` caller, STALLING never entered) and the
  Thinker was consulted only on DEFER. Added the stall path with a bounded grace
  so a ready note needs no clip, Window A on confident turns inside the
  persona's pause, the Speaker-transcript feed to pre-gate/Thinker on the
  degraded path, and `claims_made` from the spoken history. Race suite, arch
  and lint clean. Updated [engine](/concepts/subsystems/engine.md),
  [test-suite](/concepts/subsystems/test-suite.md), [decisions](/decisions.md).
* Third pass, "no fakes in the final code": built `internal/controlplane`
  (fetch + ingest client with retry, idempotency key, spool/drain), removed
  the sample-contract fake and flag from `engined`, systemd and Terraform,
  added the control plane's `POST /sessions/{id}/ingest` with the
  `IngestStore` port, table and migration, and a shared-secret gate on both
  engine routes. Gates green. Not yet exercised engine-to-control-plane over
  the network. Updated [engine](/concepts/subsystems/engine.md),
  [session-ingest](/concepts/contracts/session-ingest.md) (new),
  [rest-api](/concepts/contracts/rest-api.md), [storage-ports](/concepts/contracts/storage-ports.md).

## 2026-09-13

* OKF wrap-up before new requirements. Audited the bundle against commit
  `4280481`: every bundle link, Repo Map path, API route, DDL table, `.env`
  variable, `check.sh` gate, test file and `ui/src` file cross-checked against
  the tree. Fixed what had drifted (stale "uncommitted" state, the evaluation
  agent and subsystem index describing the report as unbuilt, the storage-port
  count, `session_ingests` missing from the schema page, five test files and
  four UI files with no card, the engine's configuration undocumented, six
  links that pointed outside the bundle) and recorded the remaining code-side
  discrepancies in [Backlog](/backlog.md) rather than fixing code. No code
  changed. Details in [log.md](/log.md), 2026-09-13.
* Four approved cleanups after the audit, all offline-verified (28 gates PASS
  incl. `migrations (postgres)` and `object store (minio)` on Apple
  `container`): removed the inert `SESSION_COST_CAP_USD` end to end with a
  new migration `0003` (fixtures in `test_migrations.py` moved to `0004`);
  corrected the `.env.example` database comment; ignored and untracked
  `graphify-out/`, ignored `.serena/`; deleted `control_plane/README.md`.
  Staged, not committed. Remaining risk unchanged: the live runs in
  [Backlog](/backlog.md).

* **2026-09-13 — WP1 of `docs/INTERVIEW_EXPECTATIONS_PLAN.md`** (expectations,
  links, participants). An interview now stores the checklist the interviewer
  is measured against (`interviews.expectations`, four fixed competencies in
  code, granular items toggleable) and a `report_sections` map re-keyed to the
  eight sections the renderer actually has; `participants` + `interview_links`
  land, `interview_expectations` and `interview_assignments` are dropped, and
  `expectation_agent/` is deleted (pivot task 7). New Postgres `0004`; new
  SQLite one-off `scripts/upgrade_sqlite_expectations.py`. `require_engine_secret`
  is now `require_shared_secret` and gates the link minter and the participant
  routes too. 30 gates PASS including `migrations (postgres)` and
  `object store (minio)` on Apple `container`; `owner_handover/` regenerated.
  Staged, not committed.
  **Remaining risk / what is deliberately not done**: WP2 is what makes the
  report engine score an enabled item and the renderer honour a section toggle
  — until then both are stored and passed around, not consumed, so a manager
  toggling `transcript` on sees no change. WP3 (the console screens) and WP4
  (end-to-end verification against a real link and two participants) are open.
  While fixing four test fixtures that were writing to the developer's own
  `control_plane.db`, note that `get_repo()` still opens a connection per
  request from `CONTROL_PLANE_DB` — unchanged, and still the first thing to fix
  before real load.
* **2026-09-13 — WP1 reviewed, bundle compacted, direction recorded.** Gate
  re-run independently (30 PASS). Two stale rows fixed. New concept page
  [The interview as a fixture](/concepts/interview-fixture.md) is now the
  entry point for the 2026-09-13 direction; `log.md` August–September-1
  history compressed a second time. Everything staged, nothing committed.
  Next: WP2 (report engine honours items and toggles), then WP3, WP4.

