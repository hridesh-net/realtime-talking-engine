---
type: Runbook
title: Create an interview
description: End to end — job spec, expectation, virtual candidates, engine contract, scorecard.
resource: /control_plane/api.py
tags: [runbook, e2e, api, curl]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /README.md
  - resource: /control_plane/api.py
  - resource: /docs/GO_ENGINE_CONTRACT.md
---
# Create an interview

Needs the API running and at least one provider key set
([dev setup](/concepts/runbooks/dev-setup.md)).

## 1. Create the interview

```bash
curl -s -X POST http://localhost:8081/api/v1/interviews \
  -H 'Content-Type: application/json' -d '{
    "job_title": "Senior Backend Engineer",
    "jd": "Go, distributed systems, Redis, microservices. Design scalable services and mentor juniors.",
    "skills_required": ["Go", "distributed systems", "Redis", "microservices", "system design"],
    "job_location_type": "remote",
    "experience_level": "senior",
    "company_type": "startup"
  }'
# -> {"id": "<uuid>", "status": "scheduled", "config": {"duration_minutes": 60, ...}, ...}
```

No model call, instant. Candidate and interviewer are **not** captured here.
Optional M1 fields ride on the same body: `location`, `department`,
`manager_level`, `language` (`english_indian`|`hinglish`|`hindi` — the persona
opens in it), `proctoring` (recorded, never enforced), `candidate_notes`
(colour layered on the archetype; cannot override it), `clarity_facts` (the
role-fact checklist — draft them first with `POST /role-facts`) and
`report_sections` (which report panels the manager sees; unknown keys are a
422). All default sensibly, so the minimal body above still works.

## 2. Generate the expectation

```bash
curl -s -X POST http://localhost:8081/api/v1/interviews/<id>/expectation
```

Calls the model (temperature 0.1). Returns the full
[expectation document](/concepts/contracts/interview-expectation.md): phase
structure, mandatory/optional skills with assessment methods, resume and
behavioural probing, red/green flags, the six fixed criteria, and interviewer
dos/don'ts. Upserts — safe to re-run.

For this input, `determine_interview_type("senior", "startup")` fixes
`interview_type` to `technical_discussion` before the model ever sees it.

## 3. Enroll virtual candidates

```bash
# the two defaults: the bias trap and the evasive candidate — chosen for
# rubric weight, not hiring outcome
curl -s -X POST http://localhost:8081/api/v1/interviews/<id>/candidates

# or choose from the catalog
curl -s http://localhost:8081/api/v1/candidate-archetypes
curl -s -X POST http://localhost:8081/api/v1/interviews/<id>/candidates \
  -H 'Content-Type: application/json' \
  -d '{"archetypes": ["inflated_resume", "nervous_fresher"]}'
```

One model call **per archetype**, sequential — expect it to be slow. Already-
enrolled archetypes are returned untouched unless you pass `"regenerate": true`.
Pass `"seed_prefix"` to reproduce a specific set of people.

If the expectation exists, it is fed to the agent to ground the personas in the
flags the interviewer will be watching for. It is optional.

## 4. Hand off to the engine

```bash
curl -s http://localhost:8081/api/v1/candidates/<cid>/engine-contract
```

Inject `system_prompt` **verbatim** as the realtime model's system instruction,
apply `voice_directives` and `turn_policy`, and enforce `knowledge_ceiling` as a
runtime guard. Full spec: `docs/GO_ENGINE_CONTRACT.md` and
[EngineContract](/concepts/contracts/engine-contract.md).

## 5. Grade the interviewer afterwards

```bash
curl -s http://localhost:8081/api/v1/candidates/<cid>/scorecard
```

**Never expose this to the model playing the persona** — a persona that knows
what it is being probed for will lead the interviewer to it.

Grading: decide from the transcript which `must_discover` signals the interviewer
surfaced, sum their weights (they total 1.0, so the sum is a 0–1 discovery
score), compare the recorded verdict against `expected_verdict`, and check which
`interviewer_failure_modes` occurred. The default bar is **≥ 0.70 discovery and
the right verdict** — both halves matter.

The grading pipeline itself is not built.

## Or use the UI

`cd ui && npm run dev` → http://localhost:3000. Covers steps 1–3 (the wizard
includes the role-fact auto-fill), deletion, and running the interview itself —
typed or spoken; not the engine-contract or scorecard endpoints.
