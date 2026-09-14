---
type: Module
title: control_plane/api.py
description: The /api/v1 router — routes, dependency injection, and the enrollment orchestration.
resource: /control_plane/api.py
tags: [api, fastapi, routes, di]
generated:
  by: claude-opus-5
  at: "2026-09-14T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-14T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /control_plane/api.py
---
# control_plane/api.py

~1300 lines. Endpoint reference lives in [REST API](/concepts/contracts/rest-api.md);
this card is about the code.

# Schema

```python
def get_repo() -> InterviewRepository          # init_db() per request
def get_expectations_agent() -> ExpectationsAgent
def get_candidate_agent() -> VirtualCandidateAgent
def get_session_agent() -> CandidateSessionAgent
def get_role_facts_agent() -> RoleFactsAgent
def get_analysis_agent() -> AudioAnalysisAgent
def get_realtime_broker() -> RealtimeBroker
REALTIME_TTL_SECONDS = 600
router = APIRouter(prefix="/api/v1", tags=["interviews"])
```

Handlers, in order: `create_interview`, `get_interview`, `update_interview`,
`list_interviews`,
`draft_expectations`, `classify_expectation`, `draft_role_facts`,
`list_archetypes`, `list_trait_dimensions`, `enroll_candidates`,
`list_candidates`, `list_sessions`, `get_candidate`, `get_engine_contract`,
`ingest_session`, `get_scorecard`, `delete_candidate`, `create_link`,
`revoke_link`, `get_link`, `get_participant`, `list_participant_sessions`,
`start_session`, `take_turn`, `end_session`, `get_session`,
`voice_capability`, `mint_realtime_credential`, `append_transcript_turn`,
`append_recording_chunk`, `finalize_recording`, `get_recording`,
`start_analysis`, `get_analysis_status`, `get_analysis_body`,
`generate_session_report`, `get_session_report`, `get_session_report_html`.

The CORS switch and the error envelope are **not** here — they are applied to
the whole app in `control_plane/main.py`; see
[Control plane](/concepts/subsystems/control-plane.md).

Three module-level helpers:

```python
def _enabled_expectations(interview: InterviewResponse) -> list[dict[str, Any]]
def _compose_custom_persona(spec: CustomPersonaSpec) -> trait_dimensions.CustomPersona
def _interview_id_from_token(repo: LinkStore, req: SessionCreateRequest) -> str
```

`_enabled_expectations` is what both cast paths hand the casting model: enabled
items only, because an item the manager switched off is not something this
interview is measured on. `_interview_id_from_token` is where link expiry is
enforced — 404 unknown, 410 revoked, 410 expired, 422 on an `interview_id` that
disagrees — and it is the only place it is enforced anywhere.

It is deliberately thin. Content-addressing the spec and composing both trait
layers is domain work and lives in `candidate_agent.trait_dimensions`; this
handler only translates `UnknownPresetError` and `ValueError` (pydantic's
`ValidationError` is a `ValueError` subclass) into `HTTPException(422)` — a
malformed custom persona never reaches `agent.generate`, and therefore never
costs a model call.

`start_session` looks the persona up in the **database before the catalog**. A
composed archetype is never registered, so a catalog-first check made every
custom persona unusable the moment the process restarted — the candidate row
survived, the archetype did not, and the session returned 422. The catalog is
consulted only when nothing is enrolled and the persona has to be cast.

## Dependency injection

Each handler annotates the **narrowest port it needs** —
`InterviewStore`, `InterviewEditor`, `LinkStore`, `ParticipantStore`,
`CandidateStore`, `EnrollmentStore`, `SessionStore`, `LinkSessionStore`,
`TurnWorkflowStore` — while `Depends(get_repo)` supplies the one
concrete `InterviewRepository`. That split is the DIP/ISP discipline, and
`test_dip_handlers_depend_on_ports_not_the_sqlite_adapter` fails if a handler
annotates the adapter directly.

`update_interview` is the worked example of why the list keeps growing rather
than the ports: it takes `InterviewEditor`, so the twenty-odd handlers that read
an interview did not acquire the ability to rewrite one when the wizard needed
an update route (2026-09-14). It is four lines — call `repo.update`, 404 when it
returns `None` — because every checklist rule lives in
`control_plane.schemas.validate_expectations` /
`validate_report_sections` and reaches it as a 422 from pydantic.

Override these four providers in tests rather than patching modules — `tests/test_session.py` overrides `get_repo` and `get_session_agent` and never touches the network.

## `enroll_candidates` — the one with logic

```python
keys = archetype_catalog.default_keys() if (req.archetypes is None and not req.custom_personas) else (req.archetypes or [])
unknown = [k for k in keys if k not in archetype_catalog.ARCHETYPES]   # -> 422
casts = [(k, None) for k in keys] + [_register_custom_persona(s) for s in req.custom_personas or []]
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
* **The interview's enabled expectation items ground the cast**, and `interview_type` comes from `determine_interview_type(experience_level, company_type)` — a deterministic table that moved out of the retired `expectation_agent/rubric.py` into `evaluation_agent/rubric.py` on 2026-09-13, because it was the only thing that package computed which anything still read. The alternative was a hardcoded `"mixed"` on both cast paths.
* **The interview's `language` and `persona_notes` ride into every cast** — here and in `start_session`'s on-the-spot cast — so a Hinglish interview produces a Hinglish persona no matter which endpoint triggers the cast.

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

## `start_session` — two ways in, one handler

A console or portal caller names the `interview_id`. A link holder sends
`invite_token` and the interview is resolved from the link by
`_interview_id_from_token`, with the expiry enforced **at that moment**. The
participant is upserted *before* the persona is cast, so a taker whose provider
call then fails is still a known person the next time they try; everything after
that — the persona lookup, the on-the-spot cast, the session row — is the same
code on both paths. Two entry points that could disagree about how a session is
opened eventually would.

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

## `append_recording_chunk` — the one guard the adapter cannot own

```python
session = repo.get_session(session_id)               # 404
if session.modality != "voice": ... 409               # handler-owned, not the adapter's
data, mime_type = await _read_chunk(request)
if not data: ... 422
try:
    return repo.append_recording_chunk(session_id, seq, mime_type, data)
except ValueError as exc:
    raise HTTPException(409, str(exc)) from exc         # wrong seq, or already finalized
```

The modality check lives here, not in `InterviewRepository.append_recording_chunk` —
same split as `take_turn` checking `session.status` before calling `append_turn`.
`request: Request` reads the body directly rather than through a Pydantic model,
since this is audio, not JSON; the content type becomes the recording's stored
`mime_type`, read once, on `seq=0`.

```python
async def _read_chunk(request: Request) -> tuple[bytes, str]
```

The one module-level helper on this path, and the reason the endpoint takes two
body shapes without the console noticing. It branches on the request's own
`Content-Type`: anything but `multipart/form-data` is the original
`await request.body()` with that header as the mime type; a multipart body is
read through `await request.form()` and the file field named `chunk` supplies
both the bytes and — from the *part's* content type — the mime type. A missing
or non-file `chunk` field is a **422**, and an empty part falls through to the
same empty-body 422 as before.

Two things this deliberately does **not** do. It does not declare an
`UploadFile` parameter: FastAPI would then require a form on every request and
422 the console's raw `audio/webm` body, which is the one regression this change
could not afford. And the `isinstance` check is against
`starlette.datastructures.UploadFile`, not `fastapi.UploadFile` — the latter is
a subclass FastAPI builds for declared parameters, and checking against it
rejects every part a hand-read form produces. (This is also why
`python-multipart` is now in `requirements.txt`: Starlette imports it lazily and
`request.form()` raises without it.)

`finalize_recording` and `get_recording` take the narrower `RecordingStore` —
neither needs the session, only the recording, which either exists or does
not. `get_recording` returns a **`FileResponse`** (not a Pydantic model) so it
can set `media_type` from the stored `mime_type` rather than being forced to
JSON, stream the file instead of loading it, and answer a `Range` request with a
206. `content_disposition_type="inline"` is passed explicitly: Starlette's
default is `attachment`, and this endpoint has always served inline.

`start_analysis` hands the agent the recording's own path, from
`repo.open_recording`. It used to copy the bytes to a scratch file under
`tempfile.gettempdir()` that nothing deleted; that copy is gone (2026-09-12).
See [Session recording](/concepts/contracts/session-recording.md) for the full
chunk protocol and the retention decision that makes handing out the live path
safe.

## `ingest_session` — the engine's write-back, and `require_shared_secret`

`require_shared_secret` (named `require_engine_secret` until 2026-09-13) is a
dependency on six routes now: the engine contract, the ingest, the link minter,
the revoke, and the two participant routes. It was renamed when the engine
stopped being its only caller — a gate named after one of its users invites the
next author to decide their route is "not an engine route" and leave it open. It
reads `CONTROL_PLANE_SHARED_SECRET` at request time (so a test can set it per
case), answers **503** when unset — refusing beats admitting on a deploy that
forgot the secret — and compares the bearer token with `secrets.compare_digest`.

`get_link` is the one **public** route and uses `compare_digest` for its own
final accept, so the decision to admit never branches on how much of the token
matched.

`ingest_session` validates before it writes: path and body `session_id` must
agree (422), the interview and persona must exist (404), and the persona must
belong to that interview (409). Then one repository call does everything
(see [storage ports](/concepts/contracts/storage-ports.md)); `IngestConflictError`
from it is a 409. The status is chosen from the receipt: 201 first time, 200 on
a repeat. Full contract: [Session ingest](/concepts/contracts/session-ingest.md).

## Gotchas

* `get_repo()` calls `init_db()` per request, opening a new SQLite connection and re-running the whole schema. The source flags it as needing a pool.
* `req: CandidateEnrollRequest | None = None` then `req = req or CandidateEnrollRequest()` — a body-less POST is valid and enrolls the defaults.
* Route order matters for the FastAPI matcher: `/candidates/{cid}` sits under the router alongside `/interviews/{id}/candidates`; they do not collide, but adding `/candidates/search` would need to precede `/candidates/{cid}`.
* `B008` is ignored for this file — `Depends()` in a default is the framework's calling convention.
* `tests/test_session.py` and `tests/test_voice.py` cover the session and voice handlers (201/404/409/410/422/502 and the full round trips) with `TestClient` and `Depends` overrides. `tests/test_recording.py` covers the recording handlers the same way, plus the adapter directly against `:memory:` with `recordings_dir=tmp_path`; `tests/test_portal_compat.py` covers the multipart chunk door against the raw one. `tests/test_expectations.py` covers creation validation and the two expectation routes; `tests/test_links_participants.py` covers the link and participant routes and the token path through `POST /sessions`.
* `voice_capability` is the one route that answers rather than fails when misconfigured. Resist making it 503: the UI's question is "should I show the button", and an exception is a worse answer than `false`.
