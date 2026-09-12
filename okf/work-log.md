---
type: WorkLog
title: Cross-agent work log
description: Short append-only handoffs for active work; detailed history remains in log.md.
resource: /okf/work-log
tags: [work-log, handoff, agents]
generated:
  by: codex
  at: "2026-09-12"
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
