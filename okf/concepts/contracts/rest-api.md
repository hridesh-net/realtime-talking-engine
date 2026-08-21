---
type: Contract
title: REST API
description: Every control-plane endpoint — paths, bodies, responses, and status codes.
resource: /control_plane/api.py
tags: [contract, api, fastapi, rest]
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
  - resource: /ui/src/api.js
---
# REST API

FastAPI, router prefix `/api/v1`, tag `interviews`. Served by
`control_plane.main:build_app` (factory), default port **8081**
(`CONTROL_PLANE_PORT`). `GET /healthz` sits outside the router.

# Schema

## Interviews

| Method | Path | Port used | Status | Notes |
|---|---|---|---|---|
| `POST` | `/api/v1/interviews` | `InterviewStore` | **201** | Body: [`InterviewCreateRequest`](/concepts/contracts/interview-record.md). Sync, no model call. |
| `GET` | `/api/v1/interviews/{id}` | `InterviewStore` | 200 / 404 | |
| `GET` | `/api/v1/interviews?status=` | `InterviewStore` | 200 | Newest first. |

## Expectation

| Method | Path | Port used | Status | Notes |
|---|---|---|---|---|
| `POST` | `/api/v1/interviews/{id}/expectation` | `ExpectationWorkflowStore` | **201** / 404 | **Calls the model.** No body. Generates and upserts. |
| `GET` | `/api/v1/interviews/{id}/expectation` | `ExpectationStore` | 200 / 404 | 404 until generated. |

`POST` passes `has_resume=False` unconditionally — the resume is attached later
when a candidate is assigned, so `resume_probing.required` is currently always
`False`. That is a known simplification, marked in the source.

## Candidates

| Method | Path | Port used | Status | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/candidate-archetypes` | — | 200 | `{catalog_version, defaults, archetypes[]}`. Pure data, no I/O. |
| `POST` | `/api/v1/interviews/{id}/candidates` | `EnrollmentStore` | **201** / 404 / 422 | **Calls the model, once per archetype.** Body optional. |
| `GET` | `/api/v1/interviews/{id}/candidates` | `CandidateStore` | 200 | |
| `GET` | `/api/v1/candidates/{cid}` | `CandidateStore` | 200 / 404 | Full [persona](/concepts/contracts/virtual-candidate.md). |
| `GET` | `/api/v1/candidates/{cid}/engine-contract` | `CandidateStore` | 200 / 404 | [Runtime slice](/concepts/contracts/engine-contract.md). |
| `GET` | `/api/v1/candidates/{cid}/scorecard` | `CandidateStore` | 200 / 404 | Ground-truth key. **Never give this to the persona's model.** |
| `DELETE` | `/api/v1/candidates/{cid}` | `CandidateStore` | **204** / 404 | |

### Enrollment body

```json
{"archetypes": ["strong_hire", "confident_bluffer"],
 "regenerate": false,
 "seed_prefix": null}
```

All fields optional. Omitting `archetypes` enrolls the two defaults
(`strong_hire`, `clear_reject`). Unknown keys → **422** listing them.

Behavior worth knowing:

* An archetype already enrolled is **returned as-is** unless `regenerate: true`.
* The interview's expectation is fetched and passed to the agent when present — it grounds personas in the flags the interviewer is watching for. **Optional by design**: enrollment must not require an expectation.
* Names already used in the interview are passed as `avoid_names`, because independent casts converge on the same names and a training set full of "Alex Chen" is confusing.
* Personas are generated **sequentially**, one model call each, and saved as they land. Enrolling six archetypes is six serial calls.

## Cross-cutting

* Errors are FastAPI's `{"detail": ...}`; the UI's fetch wrapper unwraps `detail` when it is a string.
* No authentication, rate limiting, or pagination anywhere.
* `get_repo()` opens a **new SQLite connection per request** via `init_db()`. The source notes this should be a pooled dependency in production.
* Dependency injection is `Depends(get_repo)` / `Depends(get_expectation_agent)` / `Depends(get_candidate_agent)` — override these in tests rather than patching modules.

## Related

[Create an interview](/concepts/runbooks/create-an-interview.md) — worked
end-to-end example · [api.py module card](/concepts/modules/control-plane-api.md)
