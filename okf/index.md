---
okf_version: "0.2"
---
# interview-watcher Knowledge Bundle

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
v0.2 bundle describing the **interview-watcher** repository: the interview
control plane. It creates interviews from a job spec — with the checklist the
interviewer will be measured against and the link takers arrive on — casts
virtual candidates that hiring managers practise against, and runs the live
interview against them, typed or spoken.

**This bundle is the primary code reference for agents working in this repo.**
Read it instead of re-reading the source. When code changes, update the affected
concept and append to [log.md](/log.md) — see
[Keeping this bundle current](/concepts/runbooks/okf-maintenance.md).

## Start here

* [Project Overview](/concepts/project-overview.md) - what this service is, what it is not, current state.
* [Determinism split](/concepts/determinism.md) - **the central idea**: what code owns vs. what the model may author.
* [The interview as a fixture](/concepts/interview-fixture.md) - **the 2026-09-13 direction**: one interview, its checklist, report shape and link, many takers joined on email; what is built and what is not.
* [Architecture](/concepts/architecture.md) - the four layers, the one-way dependency rule, and how it is enforced.
* [Repo Map](/concepts/repo-map.md) - path → concept routing table.
* [Conventions](/concepts/conventions.md) - the explicit lint/type rule set and the executable architecture rules.
* [Glossary](/concepts/glossary.md) - archetype, verdict, expectation, scorecard, fingerprint, ceiling.

## Sections

* [Subsystems](/concepts/subsystems/index.md) - one page per package.
* [Contracts](/concepts/contracts/index.md) - API, persona, expectations, links and participants, engine handoff, storage.
* [Modules](/concepts/modules/index.md) - one reference card per significant source file.
* [Runbooks](/concepts/runbooks/index.md) - setup, checks, using the API, **running an interview**, maintaining this bundle.
* [References](/references/index.md) - the BRD, providers, the sibling repo, the OKF spec.

## Shared agent workspace

* [Current State](/current-state.md) - concise handoff of active implementation and runtime state.
* [Decisions](/decisions.md) - decisions that constrain current cross-agent work.
* [Work Log](/work-log.md) - short append-only handoffs for work in progress.
* [Backlog](/backlog.md) - verified follow-ups and open validation work.

Before changing code, read Current State and the affected concept page. After a
change, update the affected concept, append the detailed change to
[log.md](/log.md), and leave a short handoff in Work Log. Record only facts
verified from repository state or an explicitly identified runtime; label plans
and external runtime observations as such. Never copy credentials, tokens,
private prompts, recordings, transcripts, personal data, or raw `.env` values
into this bundle.

## Freshness

Curated 2026-08-21 against commit `802c8426` by reading every documented source
file, and kept current since — see [log.md](/log.md) for what has changed.
**Last full audit 2026-09-13 against commit `4280481`** (every bundle link,
every Repo Map path, every route, table, env var, check gate, test file and UI
file cross-checked against the tree — see the 2026-09-13 entry in log.md and
the audit checklist in [Keeping this bundle current](/concepts/runbooks/okf-maintenance.md)).

Most recent substantive change (2026-09-13, staged at time of writing; see
[The interview as a fixture](/concepts/interview-fixture.md) for the direction it serves):
**an interview now carries the checklist the interviewer is measured against,
and the link people take it on.** The four competencies stay fixed in code; what
varies per interview is the granular list under them (`interviews.expectations`,
toggleable, with drafted and custom items), `report_sections` is re-keyed to the
eight sections the renderer actually has, and `participants` + `interview_links`
replace the never-written `interview_assignments`. `expectation_agent/` is
deleted; its pages are marked superseded. See
[Interview record](/concepts/contracts/interview-record.md),
[Links and participants](/concepts/contracts/links-and-participants.md) and
[evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md).
**Scoring an item and honouring a section toggle is WP2 and is not built.**

Before that (2026-09-12, commit `4280481`): **the Go engine
talks to the control plane, and only to the control plane.** `internal/controlplane`
fetches every persona over the shared secret and reports each finished session
to the new `POST /sessions/{id}/ingest`; the sample-contract fake is gone from
the binary, the unit and Terraform. The same day: the harness context and the
independent OpenAI transcriber (live-verified), the stall path and Window A on
every turn, video riding in the browser recording, and the session clock bound
lifted to the interview's own length. See [Session ingest](/concepts/contracts/session-ingest.md),
[Live-session engine](/concepts/subsystems/engine.md) and
[Session recording](/concepts/contracts/session-recording.md).

Earlier history (Postgres and the object store on 2026-09-10; the report a manager
can read and the analysis agent in August) is summarised at the top of
[log.md](/log.md), which was compressed again on 2026-09-13.

⚠️ Read `docs/BRD_Interviewer_Upskilling_v3.html` before changing anything about
what is scored or who is scored. The **hiring manager** is the assessed subject
and the report engine already scores them. The JD-driven interviewer plan is
gone (pivot task 7, 2026-09-13), but the persona catalog still carries a
candidate `verdict` as *ground truth for the persona*, not as an assessment of
anyone. Pivot-plan Phase 2 (role cards replacing job specs) has not happened,
so pages describing the job-spec domain model are current, not stale.
