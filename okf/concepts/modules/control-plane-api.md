---
type: Module
title: control_plane/api.py
description: The /api/v1 router — routes, dependency injection, and the enrollment orchestration.
resource: /control_plane/api.py
tags: [api, fastapi, routes, di]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /control_plane/api.py
---
# control_plane/api.py

237 lines. Endpoint reference lives in [REST API](/concepts/contracts/rest-api.md);
this card is about the code.

# Schema

```python
def get_repo() -> InterviewRepository          # L28 — init_db() per request
def get_expectation_agent() -> InterviewExpectationAgent   # L34
def get_candidate_agent() -> VirtualCandidateAgent         # L114
router = APIRouter(prefix="/api/v1", tags=["interviews"])
```

Handlers, in order: `create_interview`, `get_interview`, `list_interviews`,
`generate_expectation`, `get_expectation`, `list_archetypes`,
`enroll_candidates`, `list_candidates`, `get_candidate`, `get_engine_contract`,
`get_scorecard`, `delete_candidate`.

## Dependency injection

Each handler annotates the **narrowest port it needs** —
`InterviewStore`, `ExpectationStore`, `ExpectationWorkflowStore`,
`CandidateStore`, `EnrollmentStore` — while `Depends(get_repo)` supplies the one
concrete `InterviewRepository`. That split is the DIP/ISP discipline, and
`test_dip_handlers_depend_on_ports_not_the_sqlite_adapter` fails if a handler
annotates the adapter directly.

Override these three providers in tests rather than patching modules.

## `enroll_candidates` — the one with logic

```python
keys = req.archetypes or archetype_catalog.default_keys()
unknown = [k for k in keys if k not in archetype_catalog.ARCHETYPES]   # -> 422
expectation = repo.get_expectation(interview_id)                       # optional
taken = [c.name for c in repo.list_candidates(interview_id)]
for key in keys:
    existing = repo.get_candidate_by_archetype(interview_id, key)
    if existing and not req.regenerate:
        results.append(existing); continue
    candidate = await agent.generate(..., avoid_names=taken)
    repo.save_candidate(candidate, model_used=agent.model)
    taken.append(candidate.name)
```

Three decisions worth knowing:

* **Skip-unless-regenerate** — an already-enrolled archetype is returned untouched, so the endpoint is safe to re-POST.
* **`avoid_names` accumulates within the loop** — independent casts converge on the same names, and a training set of identical names is confusing.
* **The expectation is optional** — fetched if present to ground personas in the flags the interviewer is watching for, but enrollment must not require it. `interview_type` falls back to `"mixed"`.

Generation is **sequential** — one awaited model call per archetype. Enrolling
six is six serial round trips; there is no `asyncio.gather`, and adding one would
break `avoid_names`.

## Gotchas

* `get_repo()` calls `init_db()` per request, opening a new SQLite connection and re-running the whole schema. The source flags it as needing a pool.
* `req: CandidateEnrollRequest | None = None` then `req = req or CandidateEnrollRequest()` — a body-less POST is valid and enrolls the defaults.
* Route order matters for the FastAPI matcher: `/candidates/{cid}` sits under the router alongside `/interviews/{id}/candidates`; they do not collide, but adding `/candidates/search` would need to precede `/candidates/{cid}`.
* `B008` is ignored for this file — `Depends()` in a default is the framework's calling convention.
* No test covers this file. `TestClient` + a `Depends` override would cover the 404/422 branches cheaply.
