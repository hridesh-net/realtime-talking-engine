---
type: Contract
title: Session ingest
description: POST /api/v1/sessions/{id}/ingest — the Go engine's single write-back for a finished voice session, its idempotency, and the shared secret both engine routes require.
resource: /control_plane/schemas.py#SessionIngest
tags: [contract, engine, ingest, session, auth]
generated:
  by: claude-fable-5-1
  at: "2026-09-12T23:00:00Z"
verified:
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
status: stable
sources:
  - resource: /control_plane/schemas.py
  - resource: /control_plane/api.py
  - resource: /control_plane/repository.py
  - resource: /engine/internal/controlplane
  - resource: /docs/ENGINE_IMPLEMENTATION_PLAN.md
---
# Session ingest

`POST /api/v1/sessions/{session_id}/ingest` is the Go engine's **single
write-back**: when a live voice session ends, for any reason, the engine posts
what happened. Schema: `owner_handover/session_ingest_schema.json`; receipt:
`owner_handover/session_ingest_receipt_schema.json`. Plan §8.2 is the origin.

## Who may call it

Only the engine. Both engine-facing routes — this one and
`GET /candidates/{id}/engine-contract` — require
`Authorization: Bearer <CONTROL_PLANE_SHARED_SECRET>`. The same secret sits in
both processes' environments (one SSM parameter in production; `bootstrap.sh`
writes it into `control-plane.env` **and** `engined.env`). An unset secret on
this side answers **503**, never open access: the contract is the persona's
entire runtime brief and the ingest rewrites a session's transcript.

## The payload

`session_id` (`[A-Za-z0-9_-]{1,120}`), `candidate_id`, `interview_id`,
`contract_fingerprint` (SHA-256 of the contract bytes the session ran on),
`engine_version`, `started_at`, `ended_at`, `end_reason` ∈
`interviewer_ended | abandoned | duration_cap | error`, `s3` object
keys (empty until the engine uploads bundles), `turns`, `ceiling_flags`,
`unlock_flip` or null, `suppressed_answers`, `metrics`, `degradations`.

Turns carry the engine's own vocabulary — speaker `human | persona`,
`start_ms`/`end_ms` from the engine's clock, `probed_skill`, `deferred`,
`fallback_used`, `trimmed`, `barged_in`, `heard_ms`. The repository maps
`human → manager`, `persona → candidate`, sets `elapsed_ms = start_ms`, and
derives each turn's `at` from `started_at`, so the engine's clock is the time
base. Turns with no text (a barge-in that produced no words) are skipped.

## What receipt does

One transaction:

1. **Session row.** If none exists, one is created: modality `voice`,
   `planned_minutes` from the interview, `archetype` and `opening_line` from
   the persona. If one exists — the portal opened it first and passed its id
   to the engine's `POST /v1/sessions` as `session_id`, so the recording and
   the transcript share a row — it is closed in place. A row under a
   *different* interview or persona is a **409**.
2. **Transcript.** `session_turns` for the session is deleted and rewritten
   from the payload.
3. **Payload.** `session_ingests` is upserted with the whole body, the engine
   version, the fingerprint, the end reason, `first_received_at` and
   `received_at`.

`status` becomes `completed` for `interviewer_ended | duration_cap`
and `abandoned` for `abandoned | error`.

Response: `IngestReceipt {session_id, status, turns_stored, duplicate,
received_at}` — **201** the first time, **200** on a repeat with
`duplicate=true`.

## Idempotency

The engine retries on 5xx and network failure with backoff, sends
`Idempotency-Key: <session_id>`, and treats **409** as delivered. When the
control plane stays down it spools the payload under `SPOOL_DIR/ingest` and
drains on its next start. A 4xx other than 409/429 is never retried: it will
not succeed on the second attempt either. So a repeat here must be safe, and
it is: everything is replaced, nothing appended.

## What it does not do

It does not run the analysis or the report. Those read the session through
the existing endpoints and, for the heard half, need the browser's recording;
the engine's own bundle upload (recording, transcript, event log) is not built
yet, so `s3` keys arrive empty. The session is listed and reportable as soon
as the ingest lands.
