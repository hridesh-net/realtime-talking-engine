---
type: CurrentState
title: Current implementation state
description: Concise cross-agent handoff for active repository and runtime work.
resource: /okf/current-state
tags: [handoff, current-state, agents]
generated:
  by: claude-fable-5-1
  at: "2026-09-14"
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
`graphify-out/` and `.serena/` ignored, `control_plane/README.md` deleted —
and then **WP1 of `docs/INTERVIEW_EXPECTATIONS_PLAN.md`**.
`scripts/check.sh`: all gates PASS, live SKIP by design (re-run green
2026-09-14 with WP0 of the practice-wizard plan staged on top).

## Staged: the wizard's update route (WP0 of the practice-wizard plan, 2026-09-14)

`PATCH /api/v1/interviews/{id}` — the first write to an interview after
creation. The portal wizard in `skillbrew-organization` is becoming a three-step
flow that saves the interview on step 1 and draws the expectation toggles on
step 2, so step 2 needed something to write to.

* `control_plane/schemas.py`: the two `InterviewCreateRequest` field-validator
  bodies are now module functions `validate_expectations` /
  `validate_report_sections`, both returning `None` unchanged when given
  `None`; `InterviewUpdateRequest` (both fields optional, a `model_validator`
  refusing a body that edits nothing) reuses them. Create behaviour is
  unchanged and its existing tests prove it.
* `control_plane/ports.py`: `InterviewEditor`, one method, listed in
  `tests/test_architecture.py::NARROW_PORTS`. Not a fourth method on
  `InterviewStore` — that would hand every interview *reader* the ability to
  rewrite one.
* `control_plane/repository.py`: `update` — one `UPDATE` for the fields
  present plus `updated_at`, `rowcount == 0` → `None`, then `self.get`.
* 12 new tests in `tests/test_expectations.py`; `owner_handover/` gained
  `interview_update_schema.json`.

**The trap, written down because it is load-bearing for the client:** the
update validators are the *create* validators, so there is no merge with the
stored row. A short `expectations` list re-enables every fixed item it omits
and drops every drafted and custom one; a short `report_sections` map resets
the keys it omits. The wizard sends the whole list and all eight keys.

WP1–WP4 of `docs/INTERVIEWER_PRACTICE_WIZARD_PLAN.md` are portal work in
`skillbrew-organization`; nothing in this repo depends on them.

## Staged: interview expectations, links and participants (WP1)

An interview now carries the checklist the interviewer is measured against and
the link takers arrive on. The four competencies stay fixed in
`evaluation_agent/rubric.py`; `interviews.expectations` holds the granular
items under them (fixed, drafted, custom — each toggleable), `report_sections`
is re-keyed to the eight sections `render.py` actually has, `participants` and
`interview_links` land (Postgres `0004`, SQLite one-off
`scripts/upgrade_sqlite_expectations.py`), and `expectation_agent/` is deleted
along with `interview_expectations` and the never-written
`interview_assignments`. `require_engine_secret` is now `require_shared_secret`
and gates the link minter and the two participant routes as well.

**What this deliberately does not do: WP2.** Nothing yet *scores* an
expectation item or *honours* a section toggle — the report engine and the
renderer are untouched, so a manager switching `transcript` on sees no change
in the rendered page. WP3 (console screens) and WP4 (end-to-end verification
with a real link and two participants) are open. Details in
[log.md](/log.md), 2026-09-13, and
[Links and participants](/concepts/contracts/links-and-participants.md).

## Committed in `4280481` (2026-09-12) and `36e7bc5` (2026-09-13)

The engine work the 2026-09-12 log entries describe — harness context,
independent OpenAI ASR (live-verified), the Thinker context guard, Window B,
the stall path and Window A on every turn, the control-plane seam with ingest
and spool, video in the browser recording, the session clock bound — is all
committed. The engine page is the reference:
[Live-session engine](/concepts/subsystems/engine.md). The 2026-09-13 audit and
its four cleanups (cost cap removed with migration `0003`, `.env.example`
corrected, `graphify-out/` and `.serena/` ignored, the stale package README
deleted) are committed in `36e7bc5`.

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
