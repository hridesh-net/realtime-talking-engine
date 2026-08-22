# interview-watcher

Interview control plane. Three things, all in Python:

1. Create interviews from a job spec.
2. Generate a deterministic **interviewer expectation** for each one — what must
   be covered, for how long, and how a good interviewer should run the session.
3. Enroll **virtual candidates** — LLM-cast personas, stored in the database,
   that a human interviewer practises against. Each persona carries a
   ground-truth answer key used to grade the interviewer afterwards.

This project is **separate from `smart-Interview`** (the real-time voice
interviewer engine). Nothing here imports from it. The runtime engine stays in
Go/Rust; this service owns the "what" of an interview.

## Layout

```
llm/                 Provider port + Gemini/OpenAI adapters (the only vendor SDKs)
expectation_agent/   Expectation agent — persona, guardrails, fixed rubric
candidate_agent/     Virtual candidate agent — archetype catalog, engine contract
control_plane/       FastAPI service, storage ports, SQLite adapter
owner_handover/      JSON Schemas + samples for the API contract (deliverables)
ui/                  React + Vite test UI
tests/               Offline checks (fast) + live scenario scripts
scripts/             check.sh, export_schemas.py
docs/                BRD, engine contract spec
```

Dependencies point one way: `llm` ← agents ← `control_plane`. Nothing outside
`llm/` imports a vendor SDK; nothing outside `control_plane/` touches storage.
`tests/test_architecture.py` fails the build if that stops being true.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # then fill GEMINI_API_KEY (or OPENAI_API_KEY)
```

## Run

```bash
.venv/bin/python -m control_plane.main          # http://127.0.0.1:8081
cd ui && npm install && npm run dev             # http://localhost:3000
```

The UI proxies `/api` to `127.0.0.1:8081`, so start the API first.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/interviews` | Create an interview from a job spec |
| GET | `/api/v1/interviews` | List interviews (optional `?status=`) |
| GET | `/api/v1/interviews/{id}` | Fetch one interview |
| POST | `/api/v1/interviews/{id}/expectation` | Generate + persist the expectation (AI call) |
| GET | `/api/v1/interviews/{id}/expectation` | Fetch the stored expectation |
| GET | `/api/v1/candidate-archetypes` | The fixed persona catalog |
| POST | `/api/v1/interviews/{id}/candidates` | Cast + persist personas (AI call) |
| GET | `/api/v1/interviews/{id}/candidates` | List enrolled personas |
| GET | `/api/v1/candidates/{cid}` | Fetch one persona |
| GET | `/api/v1/candidates/{cid}/engine-contract` | Runtime slice for the interview engine |
| GET | `/api/v1/candidates/{cid}/scorecard` | Ground-truth key for grading the interviewer |
| DELETE | `/api/v1/candidates/{cid}` | Remove a persona |

Interview creation captures the job spec only — `job_title`, `jd`,
`skills_required`, `job_location_type`, `experience_level`, `company_type`.
Candidate and interviewer are assigned later, not at creation.

`POST /interviews/{id}/candidates` with **no body** enrolls the two defaults:
one candidate who should be selected and one who should be rejected. Pass
`{"archetypes": [...]}` to choose from the catalog, and `"regenerate": true` to
re-cast personas that are already enrolled.

Contracts live in `owner_handover/`, regenerated from the Pydantic models by
`scripts/export_schemas.py` so they cannot drift:

- `interview_create_schema.json` / `interview_create_sample.json`
- `interview_response_schema.json`
- `expectation_input_schema.json`
- `expectation_output_schema.json` / `expectation_output_sample.json`
- `candidate_enroll_schema.json`
- `candidate_output_schema.json` / `candidate_output_sample.json`
- `engine_contract_schema.json` / `engine_contract_sample.json`
- `candidate_archetypes.json` — the full catalog, readable without running anything

## Virtual candidates

Eleven archetypes, fixed in `candidate_agent/archetypes.py`. Each one exists to
test a different interviewer skill:

| Archetype | Verdict | Tests whether the interviewer… |
|---|---|---|
| `strong_hire` *(default)* | select | confirms strength with evidence, still finds the gap |
| `clear_reject` *(default)* | reject | reaches a defensible no-hire with quotable evidence |
| `lazy` | reject | separates low effort from low ability |
| `smart_but_lazy` | borderline | probes past a shallow first answer |
| `disengaged` | reject | names disinterest instead of scoring it as weak skill |
| `eager_underqualified` | borderline | discounts enthusiasm when scoring depth |
| `confident_bluffer` | reject | verifies claims instead of rewarding fluency |
| `resume_inflater` | reject | asks ownership questions, converts "we" to "I" |
| `nervous_but_capable` | select | separates presentation from ability |
| `rambler` | borderline | controls time and still covers the rubric |
| `specialist_mismatch` | borderline | assesses transferable depth, not keywords |

Every persona carries the same fixed axes:

- **Way of talking** — pace, verbosity, filler and hesitation frequency,
  formality, interruption behaviour, verbal tics, sample phrases.
- **Smartness / dumbness ratio with seriousness** — plus effort, interest,
  honesty, preparedness, nervousness, each 0–10.
- **Selectable or rejectable** — `select`, `reject`, or `borderline`, with the
  rationale written against the actual required skills.

Plus the parts the runtime needs: a per-skill knowledge ceiling with a named
breaking point, specific wrong beliefs for the personas that bluff, resume
claims graded by truthfulness, an unlock condition, and a compiled system prompt
the interview engine injects verbatim. See `docs/GO_ENGINE_CONTRACT.md`.

### What the model does and does not decide

Archetype, verdict, every trait score, scorecard weights and knowledge ceilings
are computed in code from `SHA256(interview_id + archetype)`. The model only
writes what has to be grounded in the specific job — who the person is, what
they can talk about, where they break down, how they sound. Levels outside the
archetype's band are clamped; scorecard ids the model invents are discarded.

`seed_fingerprint` is stable for a given `(interview, archetype)`, so two
interviewers can be measured against the same candidate. `fingerprint` also
covers the model-authored content and moves on every re-cast, so you can detect
a persona that changed underneath a training set.

## Storage

SQLite (`control_plane.db`, path via `CONTROL_PLANE_DB`) — tables `interviews`,
`ai_personas`, `interview_expectations`, `virtual_candidates`. Personas are
stored as the full JSON document plus indexed columns (archetype, verdict,
fingerprints), unique on `(interview_id, archetype)` so a re-cast replaces
rather than duplicates. The schema ports to PostgreSQL with minimal change;
Postgres is the intended bridge to the Go/Rust runtime.

## Determinism

The expectation agent is deliberately not free-form. Phase durations, the six
evaluation criteria and weights, interview type, baseline red/green flags,
resume-probing policy, and interviewer guidance are computed in
`expectation_agent/rubric.py` and **overwrite** the model output. The model only
fills in the role-specific text. Temperature is 0.1 and output is constrained by
`EXPECTATION_JSON_SCHEMA`.

## Checks

```bash
scripts/check.sh            # everything offline — lint, format, types, architecture
scripts/check.sh --live     # also the model scenario tests (costs money)
```

| Check | Enforces |
|---|---|
| `ruff check` | The explicit rule set in `pyproject.toml` — pyflakes, naming, py311 idioms, bugbear, docstrings, annotations |
| `ruff format --check` | One formatting standard, no debate |
| `mypy` | `disallow_untyped_defs`, no implicit Optional, pydantic plugin |
| `tests/test_architecture.py` | SOLID and layering (below) |
| `tests/test_candidate_rubric.py` | Determinism, clamping, scorecard integrity |
| `scripts/export_schemas.py --check` | `owner_handover/` matches the code |
| gofmt / go vet / golangci-lint | Skipped until Go source exists; standard recorded in `.golangci.yml` |

### SOLID checks (BRD NFR-003)

`tests/test_architecture.py` turns each principle into a failing test rather
than a code-review convention:

- **SRP** — agents never import `sqlite3` or `control_plane`; generation does
  not persist. Prompt modules perform no I/O. Schema modules hold no logic.
- **OCP** — registering a new archetype or provider flows through the system
  with no edit to any agent. The test registers one at runtime and proves it.
- **LSP** — every `StructuredModel` shares the base signature, implements the
  whole contract, and is constructible through one uniform call; every archetype
  honours the same shape.
- **ISP** — `InterviewStore` / `ExpectationStore` / `CandidateStore` stay small
  and non-overlapping; handlers depend on the one they need.
- **DIP** — vendor SDKs appear only inside `llm/`; agents take an injected
  model and never read API keys; handlers are typed against ports, not the
  SQLite adapter.

Plus a layering check that no package imports one above it, and no module uses
relative imports.

### Live scenario tests

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

These call the model. The candidate suite asserts verdicts and traits come from
the catalog, knowledge stays under the ceiling, every required skill is covered,
names are unique within a training set, and the same seed reproduces the same
person.

## Config

Resolution order per role: `<ROLE>_PROVIDER` / `<ROLE>_MODEL`, then
`LLM_PROVIDER` / `LLM_MODEL`, then the provider default.

| Var | Default | Meaning |
|---|---|---|
| `EXPECTATION_PROVIDER` / `CANDIDATE_PROVIDER` | — | `gemini` or `openai` |
| `EXPECTATION_MODEL` / `CANDIDATE_MODEL` | — | Model ID — config, never hardcoded |
| `LLM_PROVIDER` / `LLM_MODEL` | — | Fallback for both roles |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | — | At least one required |
| `CONTROL_PLANE_DB` | `control_plane.db` | SQLite path |
| `CONTROL_PLANE_PORT` | `8081` | Service port |

## License

Proprietary and confidential. Copyright (c) 2026 Hridesh Sharma. All rights
reserved. See [LICENSE](LICENSE) — access to this repository does not grant
permission to use the software.
