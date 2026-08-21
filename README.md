# interview-watcher

Interview control plane: create interviews from a job spec, and generate a
deterministic **interviewer expectation** document for each one — what must be
covered, for how long, and how a good interviewer should run the session.

This project is **separate from `smart-Interview`** (the real-time voice
interviewer engine). Nothing here imports from it. The runtime engine stays in
Go/Rust; this service owns the "what" of an interview.

## Layout

```
control_plane/       FastAPI service: interview CRUD + expectation endpoints
expectation_agent/   The expectation agent — persona, guardrails, fixed rubric
owner_handover/      JSON Schemas + samples for the API contract (deliverables)
ui/                  React + Vite test UI
tests/               Scenario tests (hit the live model)
docs/                BRD
```

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

Interview creation captures the job spec only — `job_title`, `jd`,
`skills_required`, `job_location_type`, `experience_level`, `company_type`.
Candidate and interviewer are assigned later, not at creation.

Contracts live in `owner_handover/`:

- `interview_create_schema.json` / `interview_create_sample.json`
- `expectation_input_schema.json`
- `expectation_output_schema.json` / `expectation_output_sample.json`

## Storage

SQLite (`control_plane.db`, path via `CONTROL_PLANE_DB`) — tables `interviews`,
`ai_personas`, `interview_expectations`. The schema ports to PostgreSQL with
minimal change; Postgres is the intended bridge to the Go/Rust runtime.

## Determinism

The expectation agent is deliberately not free-form. Phase durations, the six
evaluation criteria and weights, interview type, baseline red/green flags,
resume-probing policy, and interviewer guidance are computed in
`expectation_agent/rubric.py` and **overwrite** the model output. The model only
fills in the role-specific text. Temperature is 0.1 and output is constrained by
`EXPECTATION_JSON_SCHEMA`.

## Tests

```bash
.venv/bin/python tests/test_expectation_agent.py
```

Runs five job-spec scenarios end to end against the live model and asserts the
rubric invariants (phase durations sum to the total, every input skill appears,
criteria set and weights are exact, resume-probing rule holds).

## Config

| Var | Default | Meaning |
|---|---|---|
| `EXPECTATION_PROVIDER` | `gemini` | `gemini` or `openai` |
| `EXPECTATION_MODEL` | `gemini-2.5-flash` | Model ID — config, never hardcoded |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | — | At least one required |
| `CONTROL_PLANE_DB` | `control_plane.db` | SQLite path |
