---
type: Contract
title: Database schema
description: SQLite tables, CHECK constraints, indexes, and what is not yet used.
resource: /control_plane/database.py
tags: [contract, sqlite, storage, schema]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /control_plane/database.py
  - resource: /control_plane/repository.py
---
# Database schema

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

* **Foreign keys are not enforced.** SQLite requires `PRAGMA foreign_keys = ON` per connection, and it is never set — so the `ON DELETE CASCADE` clauses do nothing. Deleting an interview leaves orphaned personas and expectations.
* Timestamps are ISO strings via `datetime.now(UTC).isoformat()`; reads do `.replace("Z", "+00:00")` before `fromisoformat`.
* `raw_model_output` is excluded from both persona and expectation JSON on save.
* `updated_at` on a candidate upsert is set to the same value as `created_at` in the insert branch — on conflict only `updated_at` moves, so `created_at` correctly reflects the first cast.
* Porting to Postgres: types are all TEXT, the JSON columns become `jsonb`, and the upserts are already `ON CONFLICT ... DO UPDATE`. The FK-enforcement gap disappears on Postgres, which may surface previously-silent orphans.

## Related

[repository.py](/concepts/modules/control-plane-repository.md) ·
[Storage ports](/concepts/contracts/storage-ports.md)
