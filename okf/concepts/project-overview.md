---
type: Project
title: interview-watcher
description: The interview control plane — job specs in, interviewer expectations and virtual candidate personas out.
resource: /
tags: [project, control-plane, fastapi, interviewer-training]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /README.md
  - resource: /docs/BRD_AI_Interview_Platform_v2.md
  - resource: /pyproject.toml
---
# interview-watcher

The interview **control plane**. Python, FastAPI, SQLite. It owns the *what* of
an interview; the runtime engine that actually holds the conversation is a
separate Go/Rust build and lives elsewhere.

Three jobs:

1. **Create interviews from a job spec** — title, JD, required skills, location type, experience level, company type. Candidate and interviewer are assigned later, not at creation.
2. **Generate a deterministic interviewer expectation** — what must be covered, for how long, and how a good interviewer runs the session.
3. **Enroll virtual candidates** — LLM-cast personas stored in the database that a *human* interviewer practises against. Each persona carries a ground-truth answer key used to grade the interviewer afterwards.

The third is the product's real point: this is a **training rig for
interviewers**, not an interviewing bot. The persona plays the candidate; the
human plays the interviewer; the scorecard grades the human.

## What makes it unusual

**Almost nothing important is left to the model.** Archetype, verdict, every
trait score, scorecard weights, knowledge ceilings, phase durations, evaluation
criteria and weights are all computed in code, seeded from
`SHA256(interview_id + archetype)`. The model writes only what has to be grounded
in the specific job. See [Determinism split](/concepts/determinism.md) — it is
the organizing principle of the whole repo.

**Architecture rules are executable.** `tests/test_architecture.py` turns SRP,
OCP, LSP, ISP, DIP and layering into failing tests rather than review
conventions. Adding a vendor SDK import outside `llm/` breaks the build.

## Relationship to smart-Interview

`smart-Interview` is the real-time **voice interviewer engine** — a separate
repo, split out from this one at commit `378a7b4`. **Nothing here imports from
it.** The boundary is deliberate: that repo owns the *how* of a live
conversation, this one owns the *what* of an interview. See
[the sibling-repo reference](/references/smart-interview-relationship.md).

## Build state (2026-08-21)

* **Working**: interview creation, expectation generation and storage, the full 11-archetype virtual candidate catalog, enrollment with re-cast and seeding, engine-contract and scorecard endpoints, the React test UI, the offline check suite, schema export.
* **Designed, not built**: the Go interview-candidate engine (`docs/GO_ENGINE_CONTRACT.md` specifies its side of the handoff); the post-session grading pipeline that consumes the scorecard; interviewer assignment (`interview_assignments` table exists and is unused).
* **Stand-in**: SQLite. The schema ports to PostgreSQL with minimal change, and Postgres is the intended bridge to the runtime engine.
* **Legacy**: `control_plane/persona.py` — the original BRD §4.3 seeded persona, attached at creation for `training_interviewer` mode. Superseded by [`candidate_agent`](/concepts/subsystems/candidate-agent.md) but still wired in.

## Layout

```
llm/                 Provider port + Gemini/OpenAI adapters — the only vendor SDKs
expectation_agent/   Expectation agent — persona, guardrails, fixed rubric
candidate_agent/     Virtual candidate agent — archetype catalog, engine contract
control_plane/       FastAPI service, storage ports, SQLite adapter
owner_handover/      JSON Schemas + samples, regenerated from the Pydantic models
ui/                  React + Vite test UI
tests/               Offline checks (fast) + live scenario scripts
scripts/             check.sh, export_schemas.py
docs/                BRD, Go engine contract spec
```
