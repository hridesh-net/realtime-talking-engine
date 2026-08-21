# Interview Control Plane

Python control-plane for creating and scheduling interviews. The main interview engine stays in Go/Rust; this service handles the "what" of interviews and hands off the "when/how" to the runtime.

## Why Python?

Per BRD §1.4 and your instruction, interview creation and management are kept in Python for iteration speed. The Go/Rust engine consumes the resulting interview records.

## What is captured at creation

At interview creation we capture the job specification:

- `job_title`
- `jd` (job description)
- `skills_required` (list)
- `job_location_type` (`remote` / `onsite` / `hybrid`)
- `experience_level` (`junior` / `mid` / `senior`)
- `company_type` (`startup` / `mnc`)
- `mode` (`live_interview` / `training_interviewer`)
- `config` (duration, question mode, interview mode)
- `scheduled_at`
- `metadata`

Candidate and interviewer are **not** captured at creation. They are assigned later through separate endpoints (not yet implemented).

## Storage

Default: SQLite (`control_plane.db` in project root). Swap to PostgreSQL by replacing `control_plane/database.py` — the repository layer is storage-agnostic.

### Tables

- `interviews` — one row per interview request. Contains job spec, config, schedule, status.
- `interview_assignments` — interviewer task tracking (pending/accepted/rejected/completed). Reserved for future assignment endpoint.
- `ai_personas` — full persona snapshot for training mode (name, background, attributes, fingerprint).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/interviews` | Create one interview request |
| GET | `/api/v1/interviews/{id}` | Get interview by ID |
| GET | `/api/v1/interviews?status=scheduled` | List interviews |

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic
python -m control_plane.main
# or: uvicorn control_plane.main:build_app --factory --host 0.0.0.0 --port 8081
```

## Example: Create Live Interview

```bash
curl -X POST http://localhost:8081/api/v1/interviews \
  -H "Content-Type: application/json" \
  -d '{
    "job_title": "Senior Backend Engineer",
    "jd": "Looking for a senior backend engineer with strong Go, distributed systems, Redis, and microservices experience. Must design scalable services and mentor junior engineers.",
    "skills_required": ["Go", "distributed systems", "Redis", "microservices", "system design"],
    "job_location_type": "remote",
    "experience_level": "senior",
    "company_type": "startup"
  }'
```

## Example: Create Training Interview

```bash
curl -X POST http://localhost:8081/api/v1/interviews \
  -H "Content-Type: application/json" \
  -d '{
    "job_title": "Junior Frontend Developer",
    "jd": "Entry-level React role",
    "skills_required": ["React", "JavaScript"],
    "job_location_type": "hybrid",
    "experience_level": "junior",
    "company_type": "mnc",
    "mode": "training_interviewer"
  }'
```

## Handoff to Go/Rust Engine

The Python service writes interview requests to the DB. The Go/Rust engine reads them by ID and builds runtime state from the job spec + config + candidate/persona fields. The `start_url` in the response points to the engine's start endpoint (to be wired next).
