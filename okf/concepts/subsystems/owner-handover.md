---
type: Subsystem
title: Owner handover
description: JSON Schema contracts and samples, regenerated from the Pydantic models so they cannot drift.
resource: /owner_handover
tags: [handover, schemas, deliverables, ci]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /scripts/export_schemas.py
  - resource: /owner_handover
---
# Owner handover

`owner_handover/` — the API contract as files, so a consumer (notably the Go
engine team) can generate types without running the service.

```bash
.venv/bin/python scripts/export_schemas.py            # regenerate
.venv/bin/python scripts/export_schemas.py --check    # CI: fail if stale
```

## Generated from Pydantic

| File | Model |
|---|---|
| `candidate_enroll_schema.json` | `CandidateEnrollRequest` |
| `candidate_output_schema.json` | `VirtualCandidate` |
| `engine_contract_schema.json` | `EngineContract` |
| `interview_response_schema.json` | `InterviewResponse` |
| `expectation_output_schema.json` | `InterviewExpectation` |

Each gets `$schema` (draft 2020-12) and a `description` explaining which endpoint
serves it. `candidate_archetypes.json` is exported too — the full catalog as
*data*, so the owner can read every persona option without running anything.

## Hand-maintained

Samples are written by hand and left alone by the exporter:
`interview_create_sample.json`, `expectation_output_sample.json`,
`candidate_output_sample.json`, `engine_contract_sample.json`, plus
`interview_create_schema.json` and `expectation_input_schema.json`.

## The rule

`scripts/check.sh` runs `--check`, so **any change to one of those five Pydantic
models fails the build until the schemas are regenerated.** That is the whole
point: the handover cannot drift from the code.

## ⚠️ These files are gitignored

`.gitignore` lines 22–23 ignore `owner_handover/` and `docs/`, directly above a
comment reading *"Owner deliverables are hand-maintained, not generated —
tracked on purpose."* The comment describes the intent; the lines do the
opposite.

Consequence today: six older files are tracked (committed before the ignore was
added), and **eight are not in git at all** —
`candidate_archetypes.json`, `candidate_enroll_schema.json`,
`candidate_output_schema.json`, `candidate_output_sample.json`,
`engine_contract_schema.json`, `engine_contract_sample.json`,
`interview_response_schema.json`, and `docs/GO_ENGINE_CONTRACT.md`.

The deliverables meant for the owner, and the spec the Go team needs, do not
travel with the repository. Removing those two lines is the fix.
