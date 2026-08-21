---
type: Subsystem
title: Control plane
description: The FastAPI service, its storage ports, the SQLite adapter, and the legacy persona generator.
resource: /control_plane
tags: [control-plane, fastapi, sqlite, api]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
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

`control_plane/` — the top layer. Composes both agents and owns all storage. The
only package allowed to import `sqlite3`.

| Module | Role |
|---|---|
| `main.py` | `build_app(db_path=None)` factory + `main()` uvicorn runner; `GET /healthz` |
| `api.py` | [Routes and DI](/concepts/modules/control-plane-api.md) — the `/api/v1` router |
| `ports.py` | [Three storage protocols + two compositions](/concepts/contracts/storage-ports.md) |
| `repository.py` | [`InterviewRepository`](/concepts/modules/control-plane-repository.md) — the SQLite adapter |
| `database.py` | [Schema and connection](/concepts/contracts/database-schema.md) |
| `schemas.py` | [Request/response models](/concepts/contracts/interview-record.md) |
| `persona.py` | Legacy seeded persona (below) |

## Startup

`build_app()` configures logging, calls `load_dotenv()` so provider keys are
available, applies the database schema once, registers `/healthz`, and includes
the router. `main()` runs uvicorn against `control_plane.main:build_app` with
`factory=True` on `0.0.0.0:${CONTROL_PLANE_PORT:-8081}`.

## Dependency injection

Three provider functions — `get_repo()`, `get_expectation_agent()`,
`get_candidate_agent()` — wired with `Depends(...)`. Override these in tests
rather than patching modules.

`get_repo()` calls `init_db()` **per request**, opening a fresh SQLite
connection every time. The source flags it: *"In production this should be a
connection-pool dependency."* It is the clearest thing to fix before this serves
real load.

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
auth, and pagination.
