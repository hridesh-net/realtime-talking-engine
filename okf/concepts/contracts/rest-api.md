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
    at: "2026-08-22T17:05:00Z"
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
| `GET` | `/api/v1/candidate-archetypes` | — | 200 | `{catalog_version, defaults, rubric_criteria[], stress_labels[], archetypes[]}`. Pure data, no I/O. |
| `GET` | `/api/v1/trait-dimensions` | — | 200 | `trait_dimensions.dimension_catalog()` — every preset/vocabulary a `custom_persona` value can come from. Pure data, no I/O. |
| `POST` | `/api/v1/interviews/{id}/candidates` | `EnrollmentStore` | **201** / 404 / 422 | **Calls the model, once per archetype or custom persona.** Body optional. |
| `GET` | `/api/v1/interviews/{id}/candidates` | `CandidateStore` | 200 | |
| `GET` | `/api/v1/candidates/{cid}` | `CandidateStore` | 200 / 404 | Full [persona](/concepts/contracts/virtual-candidate.md). |
| `GET` | `/api/v1/candidates/{cid}/engine-contract` | `CandidateStore` | 200 / 404 | [Runtime slice](/concepts/contracts/engine-contract.md). |
| `GET` | `/api/v1/candidates/{cid}/scorecard` | `CandidateStore` | 200 / 404 | Ground-truth key. **Never give this to the persona's model.** |
| `DELETE` | `/api/v1/candidates/{cid}` | `CandidateStore` | **204** / 404 | |

### Enrollment body

```json
{"archetypes": ["cooperative_trap", "rambler"],
 "custom_personas": [{
   "label": "Custom guarded network tech", "verdict": "borderline",
   "competence": "developing", "conscientiousness": "adequate",
   "communication": "guarded", "emotional_stance": "defensive", "honesty": "embellishing",
   "bias_trap": "regional_or_accent",
   "affect": "defensive", "verbal_style": "monosyllabic",
   "language": "hinglish_code_switcher", "comprehension": "frequent_clarifier",
   "motivation": "family_pressured", "negotiation_stance": "refuses_to_disclose_ctc",
   "environment": "spotty_home_network",
   "seniority": "junior", "function": "network", "region": "UP",
   "gender_presentation": "woman", "age_band": "25-34", "notice_period": "30_days",
   "compliance_traps": ["volunteers_protected_info"], "protected_info_type": "marital_status"
 }],
 "regenerate": false,
 "seed_prefix": null}
```

All fields optional. Omitting both `archetypes` and `custom_personas` enrolls
the two defaults (`cooperative_trap`, `evasive`); the two lists can be mixed in
one call. Unknown archetype keys or unknown/out-of-vocabulary `custom_personas`
values → **422** (see [`HumanTraitProfile`](/concepts/contracts/virtual-candidate.md),
the taxonomy layer `CustomPersonaSpec` composes into — its fields mirror
`GET /api/v1/trait-dimensions`).

Behavior worth knowing:

* An archetype already enrolled is **returned as-is** unless `regenerate: true`. A `custom_persona` spec is composed into a content-addressed archetype key (`dyn-<hash of the spec>`) first, so re-submitting an identical spec is likewise idempotent.
* The interview's expectation is fetched and passed to the agent when present — it grounds personas in the flags the interviewer is watching for. **Optional by design**: enrollment must not require an expectation.
* Names already used in the interview are passed as `avoid_names`, because independent casts converge on the same names and a training set full of "Alex Chen" is confusing.
* Personas are generated **sequentially**, one model call each, and saved as they land. Enrolling six archetypes is six serial calls.
* A malformed `custom_persona` (unknown preset, out-of-vocabulary value, or `volunteers_protected_info` without `protected_info_type`) is rejected by `_register_custom_persona` **before** any model call — see [control_plane/api.py](/concepts/modules/control-plane-api.md).

## Sessions

The live text interview. See
[Session transcript](/concepts/contracts/session-transcript.md) for the bodies.

| Method | Path | Port used | Status | Notes |
|---|---|---|---|---|
| `POST` | `/api/v1/sessions` | `SessionWorkflowStore` | **201** / 404 / 422 | Body `{interview_id, archetype, planned_minutes, modality}`. **Calls the model only when that archetype is not yet enrolled** — then it casts one and saves it. |
| `POST` | `/api/v1/sessions/{id}/turns` | `TurnWorkflowStore` | **201** / 404 / 409 / 410 | Body `{text}` — what the manager said. **Calls the model every time.** Returns the persona's `Turn`. |
| `POST` | `/api/v1/sessions/{id}/end` | `SessionStore` | 200 / 404 | No body. Idempotent. |
| `GET` | `/api/v1/sessions/{id}` | `SessionStore` | 200 / 404 | Session plus full transcript. |
| `GET` | `/api/v1/interviews/{id}/sessions` | `SessionStore` | 200 | `list[SessionSummary]`, newest first. **No transcripts.** |

### Voice

| Method | Path | Port used | Status | Notes |
|---|---|---|---|---|
| `GET` | `/api/v1/voice-capability` | — | 200 | `{available, providers, detail}`. **Never 4xx** — no realtime key is a configuration answer, and the UI needs it to decide whether to offer a Voice button. |
| `POST` | `/api/v1/sessions/{id}/realtime` | `TurnWorkflowStore` | **201** / 404 / 409 / 410 / **502** | Mints the browser's ephemeral credential. 502 when the *vendor* refuses — that is their answer, not a bug here. |
| `POST` | `/api/v1/sessions/{id}/transcript` | `SessionStore` | **201** / 404 / 409 / 422 | Records a turn **without** generating a reply. `{speaker, text}`. |

The audio never passes through this service — see
[Realtime voice](/concepts/contracts/realtime-voice.md). Two consequences visible
in the API:

* **A voice session has no pre-written turn 0.** `POST /sessions` with `modality: "voice"` returns `turns: []`; the persona *speaks* its opening line and the browser reports it back through `/transcript` like any other turn. Writing it server-side too would duplicate turn 0 and shift every `elapsed_ms` the report reads.
* **`/transcript` still stamps the clock here.** The browser knows when it *received* a transcript, which is not when it was said and is not comparable across two managers on two networks.

`GET /interviews/{id}/sessions` returns `[]` for an unknown interview rather
than 404. It is a list endpoint, and "what has been run here" is answered by
"nothing" as well as by an error — the same convention as
`GET /interviews/{id}/candidates`. It deliberately omits `turns`: the table
needs a count, and shipping every transcript to render a row count would put the
evaluation layer's evidence on the wire for a UI convenience.

The archetype catalog ships the **rubric vocabulary** alongside the personas
(`rubric_criteria`, `stress_labels`) so the picker can label a persona's stress
bars without keeping its own copy of the five criteria — a UI-side copy would
drift the moment the rubric is retuned.

Behavior worth knowing:

* **`POST /turns` writes both turns before it returns.** The manager's turn is persisted, the model is called, the reply is persisted, and only then does the response go out. A client that disconnects mid-call still leaves an honest transcript — which matters because the transcript is the evaluation layer's evidence, not a UI convenience.
* **409, not 200, on a finished session.** Ending an interview is itself a signal the report will read; silently reopening one would corrupt it.
* **410 when the persona was deleted** underneath a live session. The session row survives (its transcript is still evidence); the turn cannot be generated.
* `POST /sessions` on an already-enrolled archetype makes **no model call** and reuses the cast persona, so the same person shows up across repeated practice runs.
* Every timestamp is stamped **server-side**. The request body carries no clock.

## Cross-cutting

* Errors are FastAPI's `{"detail": ...}`; the UI's fetch wrapper unwraps `detail` when it is a string.
* No authentication, rate limiting, or pagination anywhere.
* `get_repo()` opens a **new SQLite connection per request** via `init_db()`. The source notes this should be a pooled dependency in production.
* Dependency injection is `Depends(get_repo)` / `Depends(get_expectation_agent)` / `Depends(get_candidate_agent)` / `Depends(get_session_agent)` / `Depends(get_realtime_broker)` — override these in tests rather than patching modules. `tests/test_session.py` does exactly that.

## Related

[Create an interview](/concepts/runbooks/create-an-interview.md) — worked
end-to-end example · [Run an interview](/concepts/runbooks/run-an-interview.md) —
the session loop · [api.py module card](/concepts/modules/control-plane-api.md)
