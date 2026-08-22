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
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /control_plane/api.py
---
# control_plane/api.py

480 lines. Endpoint reference lives in [REST API](/concepts/contracts/rest-api.md);
this card is about the code.

# Schema

```python
def get_repo() -> InterviewRepository          # L28 — init_db() per request
def get_expectation_agent() -> InterviewExpectationAgent   # L34
def get_candidate_agent() -> VirtualCandidateAgent
def get_session_agent() -> CandidateSessionAgent
def get_realtime_broker() -> RealtimeBroker
REALTIME_TTL_SECONDS = 600
router = APIRouter(prefix="/api/v1", tags=["interviews"])
```

Handlers, in order: `create_interview`, `get_interview`, `list_interviews`,
`generate_expectation`, `get_expectation`, `list_archetypes`,
`list_trait_dimensions`, `enroll_candidates`, `list_candidates`, `get_candidate`,
`get_engine_contract`, `get_scorecard`, `delete_candidate`, `start_session`,
`take_turn`, `end_session`, `get_session`, `voice_capability`,
`mint_realtime_credential`, `append_transcript_turn`.

Two module-level helpers back `enroll_candidates`'s `custom_personas` path:

```python
def _dynamic_archetype_key(spec: CustomPersonaSpec) -> str      # sha256(spec)[:12], "dyn-" prefixed
def _register_custom_persona(spec) -> tuple[str, HumanTraitProfile | None]
```

`_register_custom_persona` composes a spec via
`trait_dimensions.compose_archetype`/`register_dynamic` and
`compose_human_traits`, catching `UnknownPresetError` and `ValueError`
(pydantic's `ValidationError` is a `ValueError` subclass) and re-raising as
`HTTPException(422)` — a malformed custom persona never reaches
`agent.generate`, and therefore never costs a model call.

## Dependency injection

Each handler annotates the **narrowest port it needs** —
`InterviewStore`, `ExpectationStore`, `ExpectationWorkflowStore`,
`CandidateStore`, `EnrollmentStore`, `SessionStore`, `SessionWorkflowStore`,
`TurnWorkflowStore` — while `Depends(get_repo)` supplies the one
concrete `InterviewRepository`. That split is the DIP/ISP discipline, and
`test_dip_handlers_depend_on_ports_not_the_sqlite_adapter` fails if a handler
annotates the adapter directly.

Override these four providers in tests rather than patching modules — `tests/test_session.py` overrides `get_repo` and `get_session_agent` and never touches the network.

## `enroll_candidates` — the one with logic

```python
keys = archetype_catalog.default_keys() if (req.archetypes is None and not req.custom_personas) else (req.archetypes or [])
unknown = [k for k in keys if k not in archetype_catalog.ARCHETYPES]   # -> 422
casts = [(k, None) for k in keys] + [_register_custom_persona(s) for s in req.custom_personas or []]
expectation = repo.get_expectation(interview_id)                       # optional
taken = [c.name for c in repo.list_candidates(interview_id)]
for key, human_traits in casts:
    existing = repo.get_candidate_by_archetype(interview_id, key)
    if existing and not req.regenerate:
        results.append(existing); continue
    candidate = await agent.generate(..., avoid_names=taken, human_traits=human_traits)
    repo.save_candidate(candidate, model_used=agent.model)
    taken.append(candidate.name)
```

Four decisions worth knowing:

* **Defaults only apply when both `archetypes` and `custom_personas` are omitted** — a body with only `custom_personas` does not also enroll the two defaults.
* **Skip-unless-regenerate** — an already-enrolled archetype (or previously-cast custom-persona key) is returned untouched, so the endpoint is safe to re-POST.
* **`avoid_names` accumulates within the loop** — independent casts converge on the same names, and a training set of identical names is confusing.
* **The expectation is optional** — fetched if present to ground personas in the flags the interviewer is watching for, but enrollment must not require it. `interview_type` falls back to `"mixed"`.

Generation is **sequential** — one awaited model call per archetype. Enrolling
six is six serial round trips; there is no `asyncio.gather`, and adding one would
break `avoid_names`.

## `take_turn` — the ordering that matters

```python
session = repo.get_session(session_id)          # 404
if session.status != "live": ... 409
candidate = repo.get_candidate(session.candidate_id)   # 410
manager_turn = repo.append_turn(session_id, MANAGER, req.text)   # persisted first
transcript = [*(t.model_dump() for t in session.turns), manager_turn.model_dump()]
reply = await agent.reply(candidate.engine_contract, transcript)
return repo.append_turn(session_id, CANDIDATE, reply)
```

The manager's turn is written **before** the model call, not after. If the model
call fails or the client disconnects, the transcript still records what the
manager asked — an interview where the human's questions vanish because the
persona errored is worse than one with a missing answer.

`session.turns` is the transcript as it was read at the top of the handler; the
new manager turn is appended in memory rather than re-fetched, which is one
round trip saved and correct because this handler is the only writer.

`start_session` casts the persona when `get_candidate_by_archetype` returns
`None`, passing `expectation=None` and `interview_type="mixed"` — the session
path deliberately does not require an expectation document, matching enrollment.

## `mint_realtime_credential` — what is deliberately not returned

Same 404/409/410 ladder as `take_turn`, then:

```python
config = build_realtime_session(candidate.engine_contract, voices=broker.voices)
credential = await broker.mint(session=config, ttl_seconds=REALTIME_TTL_SECONDS)
```

The response carries the secret, the URL, the model, and the voice — **never
`config["instructions"]`**. A browser that could read the persona prompt could
also edit it, and the interviewer would be practising against a persona of their
own making. `test_minting_seals_the_persona_and_never_leaks_it` asserts the
system prompt does not appear anywhere in the serialized response.

`broker.voices` rather than an import from `llm.openai_realtime`: the voice list
reaches this handler through the port, so `api.py` names no vendor module and the
DIP scan stays quiet.

A `ModelError` from the broker becomes **502**, not 500 — the vendor refused, and
saying so lets the UI show something truthful.

## Gotchas

* `get_repo()` calls `init_db()` per request, opening a new SQLite connection and re-running the whole schema. The source flags it as needing a pool.
* `req: CandidateEnrollRequest | None = None` then `req = req or CandidateEnrollRequest()` — a body-less POST is valid and enrolls the defaults.
* Route order matters for the FastAPI matcher: `/candidates/{cid}` sits under the router alongside `/interviews/{id}/candidates`; they do not collide, but adding `/candidates/search` would need to precede `/candidates/{cid}`.
* `B008` is ignored for this file — `Depends()` in a default is the framework's calling convention.
* `tests/test_session.py` and `tests/test_voice.py` cover the session and voice handlers (201/404/409/410/422/502 and the full round trips) with `TestClient` and `Depends` overrides. The interview, expectation, and enrollment handlers still have no test.
* `voice_capability` is the one route that answers rather than fails when misconfigured. Resist making it 503: the UI's question is "should I show the button", and an exception is a worse answer than `false`.
