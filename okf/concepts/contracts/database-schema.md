---
type: Contract
title: Database schema
description: SQLite tables, CHECK constraints, indexes, and what is not yet used.
resource: /control_plane/database.py
tags: [contract, sqlite, storage, schema]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /control_plane/database.py
  - resource: /control_plane/repository.py
---
# Database schema

> **`session_reports`** — one row per session, `session_id` as the primary key,
> holding the report JSON plus denormalised headline and provenance columns
> (`readiness_index`, `band`, `scoring_version`, `rubric_version`,
> `english_weight`, `language_gate`). The report is **stored, not recomputed on
> read**: a threshold change must not silently move a score a trainer already
> discussed. See [Report engine](/concepts/subsystems/report-engine.md).

SQLite, path from `CONTROL_PLANE_DB` (default `control_plane.db`, gitignored via
`*.db`). `init_db()` runs the whole schema as `CREATE TABLE IF NOT EXISTS` on
every startup and every request — there are **no migrations**, so an added
column requires manual intervention on an existing database.

`check_same_thread=False`, `row_factory = sqlite3.Row`.

# Schema

## `interviews`
`id` PK, job spec columns, `mode`, `status`, `config` JSON, `ai_persona` JSON
(legacy), `scheduled_at`, `started_at`, `completed_at`, `recording_id`,
`metadata` JSON, `created_at`, `updated_at`.

The M1 configuration columns (2026-08-22): `location`, `department`,
`manager_level` (plain text, default `''`), `language` CHECK
`(english_indian,hinglish,hindi)` default `english_indian`, `proctoring` CHECK
`(off,identity,full)` default `off` (**recorded only — nothing in this service
accesses a camera at any setting**, says the column comment), `candidate_notes`
(default `''`), `clarity_facts` JSON (default `'[]'`), `report_sections` JSON
(default `'{}'`).

CHECK constraints mirror the Pydantic patterns: `job_location_type ∈
(remote,onsite,hybrid)`, `experience_level ∈ (junior,mid,senior)`, `company_type
∈ (startup,mnc)`, `mode ∈ (live_interview,training_interviewer)`, `status ∈
(scheduled,in_progress,completed,failed,cancelled)`.

Indexes on `status` and `experience_level`. `started_at`, `completed_at`,
`recording_id` are never written.

## `virtual_candidates`
`candidate_id` PK, `interview_id` FK (CASCADE), `archetype`, `archetype_label`,
`name`, `headline`, `verdict` CHECK, `persona_version`, `catalog_version`,
`persona_json`, `fingerprint`, `seed_fingerprint`, `seed`, `model_used`,
`created_at`, `updated_at`, **`UNIQUE (interview_id, archetype)`**.

The unique constraint is the design: re-casting an archetype **replaces** rather
than duplicating, via `ON CONFLICT(interview_id, archetype) DO UPDATE`. Reads
deserialize `persona_json` alone; the columns exist for indexing and inspection.
Indexes on `interview_id` and `verdict`.

## `interview_expectations`
`id` PK, `interview_id` **UNIQUE** FK (CASCADE), `expectation_version`,
`expectation_json`, `model_used`, `created_at`. Upsert on `interview_id`, so
regenerating replaces.

## `sessions`
`id` PK, `interview_id` FK (CASCADE), `candidate_id` FK (CASCADE),
`persona_key`, `status` CHECK `(live,completed,abandoned)`, `modality` CHECK
`(text,voice)` default `text`, `planned_minutes`, `opening_line`, `started_at`,
`ended_at`, `created_at`. Indexes on `interview_id` and `status`.

`opening_line` is denormalised onto the session on purpose: for a text session
it is also turn 0 of the transcript, and re-reading it from the persona later
would silently change the stored record if the persona were re-cast.

**A `modality='voice'` session has no turn 0 row.** The persona speaks its
opening line over the audio channel and the browser reports it back through
`POST /sessions/{id}/transcript`, so writing it here as well would duplicate the
turn and shift every `elapsed_ms` after it. `opening_line` is still stored, as
the record of what the persona was told to open with.

## `session_turns`
`session_id` FK (CASCADE), `idx`, `speaker` CHECK `(manager,candidate)`, `text`,
`at`, `elapsed_ms`, **`PRIMARY KEY (session_id, idx)`**.

The composite primary key replaces a surrogate id deliberately: turn order *is*
the conversation, so a duplicate index should be a constraint violation, not a
silently reordered replay. `append_turn` computes the next index as
`COALESCE(MAX(idx) + 1, 0)` inside the same transaction as the insert.

**Concurrency limit worth knowing:** two turns appended to one session at the
same instant race on that `MAX(idx)`; the loser hits the primary-key constraint
and raises. That is the correct failure for a single-manager interview, but it
is not a queue — a multi-writer session would need one.

## `session_recordings`
`session_id` **PK**, FK → `sessions(id)` (CASCADE, unenforced like every other
FK here), `status` CHECK `(recording,complete)` default `recording`, `producer`
CHECK `(browser,engine)` default `browser`, `mime_type`, `storage_key`,
`byte_size` default `0`, `next_seq` default `0`, `channel_layout` default
`manager_left_candidate_right`, `created_at`, `updated_at`.

`session_id` as the primary key, not a surrogate id, is the design: there is
exactly one recording per session, ever, whoever produces it — see
[Session recording](/concepts/contracts/session-recording.md) for the full
chunk protocol, why `producer` exists, and why `storage_key` never reaches the
`RecordingMeta` Pydantic model that clients see. The row is written by the
browser today (`POST /sessions/{id}/recording/chunks`); no code path sets
`producer='engine'` yet — that is the seam the Go engine's `Recorder`/
`Finalizer` will use once it exists.

Bytes are **not** in SQLite. `storage_key` (today, `"{session_id}.webm"`)
names a file under `RECORDINGS_DIR` (default `recordings`, gitignored, see
[Dev setup](/concepts/runbooks/dev-setup.md)).

## `ai_personas` (legacy)
`candidate_id` PK, `interview_id` FK, `name`, `background`, `attributes` JSON,
`fingerprint`, `created_at`. Written only at creation when `mode ==
"training_interviewer"`, by `control_plane/persona.py`. Superseded by
`virtual_candidates`; never read back.

## `interview_assignments` (unused)
Interviewer task tracking — `interviewer_type ∈ (human,ai)`, `task_status ∈
(pending,accepted,rejected,completed)`. Reserved for the assignment endpoint
that does not exist yet. Nothing writes to it.

## Gotchas

* **Foreign keys are not enforced.** SQLite requires `PRAGMA foreign_keys = ON` per connection, and it is never set — so the `ON DELETE CASCADE` clauses do nothing. Deleting an interview leaves orphaned personas, expectations, sessions, and turns. Deleting a persona out from under a live session is the case the API handles explicitly: `POST /turns` returns **410**.
* Timestamps are ISO strings via `datetime.now(UTC).isoformat()`; reads do `.replace("Z", "+00:00")` before `fromisoformat`.
* `raw_model_output` is excluded from both persona and expectation JSON on save.
* `updated_at` on a candidate upsert is set to the same value as `created_at` in the insert branch — on conflict only `updated_at` moves, so `created_at` correctly reflects the first cast.
* Porting to Postgres: types are all TEXT, the JSON columns become `jsonb`, and the upserts are already `ON CONFLICT ... DO UPDATE`. The FK-enforcement gap disappears on Postgres, which may surface previously-silent orphans.

## Related

[repository.py](/concepts/modules/control-plane-repository.md) ·
[Storage ports](/concepts/contracts/storage-ports.md) ·
[Session recording](/concepts/contracts/session-recording.md)
