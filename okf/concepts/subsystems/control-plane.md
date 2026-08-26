---
type: Subsystem
title: Control plane
description: The FastAPI service, its storage ports, the SQLite adapter, and the legacy persona generator.
resource: /control_plane
tags: [control-plane, fastapi, sqlite, api]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /control_plane/api.py
  - resource: /control_plane/main.py
  - resource: /control_plane/ports.py
  - resource: /control_plane/repository.py
  - resource: /control_plane/database.py
  - resource: /control_plane/persona.py
  - resource: /control_plane/schemas.py
---
# Control plane

> **Six narrow ports now.** `ReportStore` and the `ReportWorkflowStore`
> composition landed with session reports; `control_plane/reporting.py` is the
> seam that assembles a `report_engine` bundle from stored rows.

`control_plane/` — the top layer. Composes the three agent packages
(`expectation_agent`, `candidate_agent`, `evaluation_agent`) and owns all
storage. The only package allowed to import `sqlite3`.

| Module | Role |
|---|---|
| `main.py` | `build_app(db_path=None)` factory + `main()` uvicorn runner; `GET /healthz` |
| `api.py` | [Routes and DI](/concepts/modules/control-plane-api.md) — the `/api/v1` router |
| `ports.py` | [Five storage protocols + five compositions](/concepts/contracts/storage-ports.md) |
| `repository.py` | [`InterviewRepository`](/concepts/modules/control-plane-repository.md) — the SQLite adapter |
| `database.py` | [Schema and connection](/concepts/contracts/database-schema.md) |
| `schemas.py` | [Interview record](/concepts/contracts/interview-record.md) + [session transcript](/concepts/contracts/session-transcript.md) models |
| `persona.py` | Legacy seeded persona (below) |

## Startup

`build_app()` configures logging, calls `load_dotenv()` so provider keys are
available, applies the database schema once, registers `/healthz`, and includes
the router. `main()` runs uvicorn against `control_plane.main:build_app` with
`factory=True` on `0.0.0.0:${CONTROL_PLANE_PORT:-8081}`.

## Dependency injection

Five provider functions — `get_repo()`, `get_expectation_agent()`,
`get_candidate_agent()`, `get_session_agent()`, `get_role_facts_agent()` — wired
with `Depends(...)`, plus `get_realtime_broker()` for the voice path.
Override these in tests rather than patching modules;
`tests/test_session.py` does exactly that.

`get_repo()` calls `init_db()` **per request**, opening a fresh SQLite
connection every time. The source flags it: *"In production this should be a
connection-pool dependency."* It is the clearest thing to fix before this serves
real load — and it now matters more, because a live session is one request per
turn rather than one per interview.

## The live session

`control_plane` owns everything about a session that
[`candidate_agent/session.py`](/concepts/modules/candidate-agent-session.md)
refuses to: the session record, the transcript, turn indexes, timestamps, and
when a turn happens. The agent is handed a contract and a list of turns and
returns a string. See [Session transcript](/concepts/contracts/session-transcript.md)
and [Run an interview](/concepts/runbooks/run-an-interview.md).

For a `voice` session it also owns the recorded audio artifact — chunk
ordering, finalization, and where the bytes land on disk — uploaded by the
browser, not generated here. See [Session recording](/concepts/contracts/session-recording.md).

## Legacy: `persona.py`

The original BRD §4.3 persona: a seeded `CandidatePersona` with five scored
attributes (`communication_style`, `technical_depth`, `confidence_level`,
`nervousness_level`, `problem_approach`), a name drawn from fixed first/last
name pools, and a template background. Generated in `repository.create()` when
`mode == "training_interviewer"`, stored on the interview row and in
`ai_personas`, and **never read back**.

Superseded by [`candidate_agent`](/concepts/subsystems/candidate-agent.md),
which does the same job with far more structure. Two persona systems coexist;
only one is used. Removing the old one is a clean, self-contained cleanup —
touching `repository.create`, `InterviewResponse.ai_persona`, the `ai_personas`
table, and `schemas.CandidatePersona`/`PersonaAttribute`.

## Not implemented

Interviewer assignment (`interview_assignments` is empty), interview status
transitions (everything stays `scheduled`), the `start_url` target endpoint,
auth, and pagination. On the session side: no report endpoint (Phase 4 of the
pivot plan), no session list, and no timeout sweep — so `status = "abandoned"`
is in the schema but never set.
