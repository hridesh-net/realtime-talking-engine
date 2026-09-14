---
type: Contract
title: Database schema
description: The tables, CHECK constraints and indexes — on SQLite today, and the Postgres schema and migration runner being built beside it.
resource: /control_plane/database.py
tags: [contract, sqlite, postgres, storage, schema, migrations]
generated:
  by: claude-opus-5
  at: "2026-09-13T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T12:00:00Z"
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
  - resource: /control_plane/database.py
  - resource: /control_plane/repository.py
  - resource: /control_plane/migrate.py
  - resource: /control_plane/migrations/0001_initial.sql
  - resource: /control_plane/migrations/0002_session_ingests.sql
  - resource: /control_plane/migrations/0003_end_reason_drop_cost_cap.sql
  - resource: /control_plane/migrations/0004_expectations_participants_links.sql
  - resource: /scripts/upgrade_sqlite_expectations.py
---
# Database schema

> **`session_analyses`** — one row per session, written **when analysis starts**
> rather than when it finishes, so a caller can tell "running" from "never
> asked": the job takes about a minute and the UI has to show something in
> between. A failure stores its reason rather than reducing to a status, because
> the logs live on the instance. See
> [Audio analysis agent](/concepts/subsystems/analysis-agent.md).

> **`session_reports`** — one row per session, `session_id` as the primary key,
> holding the report JSON plus denormalised headline and provenance columns
> (`readiness_index`, `band`, `scoring_version`, `rubric_version`,
> `english_weight`, `language_gate`). The report is **stored, not recomputed on
> read**: a threshold change must not silently move a score a trainer already
> discussed. See [Report engine](/concepts/subsystems/report-engine.md).

SQLite, path from `CONTROL_PLANE_DB` (default `control_plane.db`, gitignored via
`*.db`). `init_db()` runs the whole schema as `CREATE TABLE IF NOT EXISTS` on
every startup and every request — there are **no migrations**, so an added or
renamed column requires manual intervention on an existing database. A rename
in `_SCHEMA` is invisible to a database that already exists: `IF NOT EXISTS`
sees the table, leaves the old column in place, and the code then asks for a
name that is not there. `scripts/rename_columns_sqlite.py` is the one-off that
closed that gap for the 2026-09-10 naming cleanup — idempotent, `--dry-run`,
guards every destructive step, and plans the whole migration before writing
anything (Python's `sqlite3` does not wrap DDL in its implicit transaction, so
a guard firing halfway would otherwise leave a half-renamed database).
`scripts/upgrade_sqlite_expectations.py` (2026-09-13) is the second one-off, in
the same shape: it adds `interviews.expectations` and `sessions.participant_id`,
creates `participants` and `interview_links` if the DDL has not already, and
drops `interview_expectations` and `interview_assignments` **only when empty**.
A *new table* in `_SCHEMA` does appear on an existing database; a new **column**
never does, and a dropped table never leaves.

`check_same_thread=False`, `row_factory = sqlite3.Row`.

# Postgres — the second schema, built beside the first (2026-09-10)

**Both backends exist in the tree right now, and the service still runs on
SQLite.** `control_plane/migrations/0001_initial.sql` is the same schema in
Postgres DDL, `0002_session_ingests.sql` adds the engine's write-back table,
`0003_end_reason_drop_cost_cap.sql` narrows its `end_reason` vocabulary and
`0004_expectations_participants_links.sql` adds the expectation column, the
participants and links tables and `sessions.participant_id` while dropping
`interview_expectations` and `interview_assignments`, all
applied by `control_plane/migrate.py`; `repository.py` has not
been switched over, so nothing in the request path touches Postgres yet. That
switch is a later work package. `_SCHEMA` and `init_db` are still the live
definition and must not be deleted until then.

Configuration: `DATABASE_URL` (default `postgresql:///interview_watcher` — a
local socket connection as the current user, so `createdb interview_watcher` is
the whole local setup). `database.open_pool()` builds the `psycopg_pool`
`ConnectionPool` (`open=False`, 1–8 connections, 10 s checkout timeout,
`dict_row`, and a `configure` hook that runs `SET timezone TO 'UTC'`).

> **`autocommit=True` on the pool is deliberate, and is not "we don't use
> transactions".** With autocommit *off*, psycopg opens an implicit transaction
> on the first statement — a plain `SELECT` counts — so a later
> `with conn.transaction():` finds itself already inside one and degrades to a
> SAVEPOINT. The savepoint releases, nothing commits, and the pool rolls the
> connection back when the handler returns: **the write disappears with no
> error anywhere.** With autocommit *on*, a bare statement is its own
> transaction and `with conn.transaction():` emits a real BEGIN/COMMIT. Every
> multi-statement write must therefore wrap itself explicitly.

## The type mapping, applied uniformly

| SQLite | Postgres | Which columns |
|---|---|---|
| `TEXT` holding JSON | **`jsonb`** | `skills_required`, `role_facts`, `expectations`, `report_sections`, `config`, `ai_persona`, `metadata`, `persona_json`, `attributes`, `analysis_json`, `report_json` |
| `TEXT` holding an ISO timestamp | **`timestamptz`** | every `*_at`, plus `session_turns.at` |
| `INTEGER DEFAULT 1` | **`boolean`** | `session_reports.language_gate` |
| `INTEGER` | `bigint` | `session_recordings.byte_size` |
| `REAL` | `double precision` | `session_judgement`, `english_weight` |
| `TEXT` id | **`text`** | every id — candidate ids are `vc-<sha256[:12]>` and `ai-<interview>-<n>`, derived from a cast seed, **not** uuids |

Where a JSON column's shape is fixed, a `CHECK (jsonb_typeof(col) = 'array')` or
`'object'` says so — `skills_required`, `role_facts` and `expectations` are
arrays, the rest are objects. Non-negative CHECKs are added on `byte_size`, `next_seq`, `idx` and
`elapsed_ms`.

**`CHECK (x IN (...))` is kept in preference to native enum types.** The lists
mirror the Pydantic patterns and change with them, and `ALTER TYPE ... ADD
VALUE` cannot run in the same transaction that then reads the new value — which
is exactly what a migration in this runner would be doing.

## The one foreign key that must stay absent

**`sessions.candidate_id` carries no FOREIGN KEY on Postgres**, even though the
SQLite DDL declares one. SQLite never enforced it (`PRAGMA foreign_keys` is off
and is never set), so two shipped behaviours are built on the reference being
inert:

1. **Deleting a persona must leave its sessions readable.** `repository.py`
   renders the missing name as `"(deleted persona)"` and `api.py` answers
   **410** on `POST /turns`. A real `ON DELETE CASCADE` would instead delete the
   transcript — the evaluation layer's only evidence that the interview
   happened.
2. **Re-casting an archetype rewrites `virtual_candidates`' primary key**, via
   `ON CONFLICT (interview_id, archetype) DO UPDATE SET candidate_id =
   excluded.candidate_id`. A referencing row would block that update.

`sessions.participant_id` (2026-09-13) is the **opposite** decision on the same
table and worth reading beside it: it *is* a real FK. A participant row is never
rewritten in place the way a re-cast rewrites `candidate_id`, and deleting a
person is a deliberate manual act that should stop at their sessions rather than
silently orphan them. `tests/test_migrations.py` asserts both, plus the
behaviours they buy, because nothing else in the suite can notice a constraint
SQLite ignored.

**Every other `ON DELETE CASCADE` becomes real**, and that is intended:
deleting an interview now actually removes its personas, links, sessions,
turns, analyses, reports and recordings instead of orphaning them. A link
outliving the interview it opens would be a token that resolves to nothing — a
500 on the one public route rather than an honest 404.

## `schema_migrations` and the runner

```
schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    checksum text NOT NULL,          -- sha256 of the file's bytes, at apply time
    applied_at timestamptz NOT NULL DEFAULT now()
)
```

Created with `CREATE TABLE IF NOT EXISTS` before the first read, so a brand-new
database reports "everything pending" rather than raising `UndefinedTable`.

Files are `NNNN_name.sql` in `control_plane/migrations/`, applied in ascending
order. **Each file runs in one transaction that first takes
`pg_advisory_xact_lock`**, so two runners starting together serialise: the
loser waits, re-reads the ledger under the lock, and finds the work already
done. A file that raises halfway rolls back whole — including its own ledger
insert — while earlier versions stay applied.

**There are no down-migrations, and there will not be.** A down-migration is a
second, less-tested path that runs only in the worst hour of the year, and the
ones that matter cannot restore the data they discarded. The recovery path is a
**restore from backup** plus a new forward migration.

| Command | Meaning |
|---|---|
| `python -m control_plane.migrate` | apply everything pending |
| `python -m control_plane.migrate --check` | report only: exit **0** current, **1** pending, **2** drift |

**Drift** is an applied version whose file checksum no longer matches, or an
applied version with no file at all. It is never repaired automatically: both
causes mean the database and the tree disagree about history, and only a human
knows which is right. `migrate.assert_current(conn)` is the same check as a
raise, for the service to call at startup — booting behind an unapplied
migration means every request fails on a column that is not there.

One consequence of the one-transaction rule: a statement Postgres refuses to run
inside a transaction block (`CREATE INDEX CONCURRENTLY`, `CREATE DATABASE`)
cannot go in a migration file.

# Schema — the tables themselves

Column names, CHECK vocabularies and indexes are **the same on both backends**;
only the types differ, per the mapping above. What follows is written against
the SQLite DDL because that is still what runs.

## `interviews`
`id` PK, job spec columns, `mode`, `status`, `config` JSON, `ai_persona` JSON
(legacy), `scheduled_at`, `started_at`, `completed_at`, `metadata` JSON,
`created_at`, `updated_at`.

The M1 configuration columns (2026-08-22): `location`, `department`,
`manager_level` (plain text, default `''`), `language` CHECK
`(english_indian,hinglish,hindi)` default `english_indian`, `proctoring` CHECK
`(off,identity,full)` default `off` (**recorded only — nothing in this service
accesses a camera at any setting**, says the column comment), `persona_notes`
(default `''`), `role_facts` JSON (default `'[]'`), `report_sections` JSON
(default `'{}'`).

`expectations` JSON (default `'[]'`, added 2026-09-13) holds the granular rubric
under the four fixed competencies — `{id, competency_id, text, source, enabled}`
each. **The competencies themselves are never stored**: they are
`evaluation_agent/rubric.py`, and an interview that could carry its own set
would stop being comparable to the one beside it. An empty array means a row
written before this column existed; the repository fills it in with
`fixed_items()` on read. See
[Interview record](/concepts/contracts/interview-record.md).

CHECK constraints mirror the Pydantic patterns: `job_location_type ∈
(remote,onsite,hybrid)`, `experience_level ∈ (junior,mid,senior)`, `company_type
∈ (startup,mnc)`, `mode ∈ (live_interview,training_interviewer)`, `status ∈
(scheduled,in_progress,completed,failed,cancelled)`.

Indexes on `status` and `experience_level`. `started_at` and `completed_at`
are never written: they are the unbuilt half of the lifecycle that `status`
values `in_progress`/`completed` already imply, and they stay for that reason.

There was a `recording_id` column beside them until 2026-09-10. It was dropped:
a recording belongs to a **session**, not an interview, and lives in
`session_recordings` keyed by `session_id`. A per-interview pointer contradicted
that model, and it was NULL in all 1788 rows of the local database.

## `virtual_candidates`
`candidate_id` PK, `interview_id` FK (CASCADE), `archetype`, `archetype_label`,
`name`, `headline`, `verdict` CHECK, `persona_version`, `catalog_version`,
`persona_json`, `fingerprint`, `seed_fingerprint`, `seed`, `model_used`,
`created_at`, `updated_at`, **`UNIQUE (interview_id, archetype)`**.

The unique constraint is the design: re-casting an archetype **replaces** rather
than duplicating, via `ON CONFLICT(interview_id, archetype) DO UPDATE`. Reads
deserialize `persona_json` alone; the columns exist for indexing and inspection.
Indexes on `interview_id` and `verdict`.

## `participants`
`id` PK, `email` **UNIQUE**, `name`, `user_id` (nullable), `created_at`,
`last_seen_at`. Added 2026-09-13.

**An identity join key, not a user table.** No password, no login, no roles;
rows are created or updated when a session starts and never by a signup. `email`
is stored normalised (trimmed, lower-cased, shape-checked by `ParticipantInput`)
because the product rule is that the same email is the same person — which is
what lets one taker's sessions across five interviews be read as one history.
`user_id` is a SkillBrew account id when one has ever been supplied for that
email; most rows never have one, because most takers arrive on a link, and an
attached id is never cleared by a later anonymous session.

Name and email are personal data of a named employee, stored beside their
recording. Retention follows the recording's decision — indefinite, deleted by
hand (see [Session recording](/concepts/contracts/session-recording.md)) — and
neither field is ever copied into this bundle, a log or a fixture.

## `interview_links`
`token` PK, `interview_id` FK (CASCADE), `expires_at`, `revoked_at` (nullable),
`created_at`. Index on `interview_id`. Added 2026-09-13.

The token is the primary key and the interview is the foreign key, not the other
way round: **several links per interview are allowed** (a cohort in March and
another in June) and one link serves any number of takers. 32 bytes of
`secrets.token_urlsafe`. Expiry is enforced at the moment a session is created —
there is no sweeper and no background job, so a row past `expires_at` is simply
never redeemable again. See
[Links and participants](/concepts/contracts/links-and-participants.md).

## `sessions`
`id` PK, `interview_id` FK (CASCADE), `candidate_id` FK (CASCADE),
`archetype`, `status` CHECK `(live,completed,abandoned)`, `modality` CHECK
`(text,voice)` default `text`, `planned_minutes`, `opening_line`,
`participant_id` (nullable FK → `participants(id)`, added 2026-09-13),
`started_at`, `ended_at`, `created_at`. Indexes on `interview_id`, `status` and
`participant_id`.

`participant_id` is nullable only for rows that predate it and for the ones the
Go engine's ingest creates on its own; every session opened through
`POST /sessions` with a participant carries one.

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

## `session_ingests`
`session_id` **PK**, FK → `sessions(id)` (CASCADE), `payload` (JSON; `jsonb`
with a `jsonb_typeof = 'object'` CHECK on Postgres, `TEXT` on SQLite),
`engine_version`, `contract_fingerprint`, `end_reason` (CHECK
`(interviewer_ended,abandoned,duration_cap,error)` on Postgres only —
the SQLite DDL carries no CHECK, the Pydantic model enforces it),
`first_received_at`, `received_at`. Added 2026-09-12 with migration `0002`;
`0003` (2026-09-13) re-creates the CHECK without `cost_cap`, a value the engine
never produced — the constraint is swapped in a new file because `0002` may
already be applied somewhere, and an edited applied file is drift.

The Go engine's single write-back for a finished voice session, kept **whole**
beside the transcript it carries: the repository rewrites `session_turns` from
the payload's turn table, and this row keeps everything the turn table does
not model — metrics, degradations, ceiling flags, the unlock flip. One row per
session, **replaced** on a repeated ingest (the engine retries with the session
id as its idempotency key; `first_received_at` survives the replace,
`received_at` moves). See [Session ingest](/concepts/contracts/session-ingest.md)
for the payload and the 409 rule, and
[Storage ports](/concepts/contracts/storage-ports.md) for why `IngestStore` is
its own port rather than a method on `SessionStore`.

## `ai_personas` (legacy)
`candidate_id` PK, `interview_id` FK, `name`, `background`, `attributes` JSON,
`fingerprint`, `created_at`. Written only at creation when `mode ==
"training_interviewer"`, by `control_plane/persona.py`. Superseded by
`virtual_candidates`; never read back.

## Two tables that used to be here (dropped 2026-09-13)

**`interview_expectations`** held the retired expectation agent's per-interview
plan document. The pivot replaced a generated rubric with a fixed one, so there
was nothing left for the document to say; the granular half of it now lives in
`interviews.expectations`. The agent's pages are marked superseded rather than
deleted — see [Expectation agent](/concepts/subsystems/expectation-agent.md).

**`interview_assignments`** was designed and never written: zero readers, zero
writers, zero rows, through two milestones. `participants` plus `interview_links`
is what it was reaching for — the decision that this service never builds invites
was amended on 2026-09-13 — so it was dropped rather than left in the schema
unbuilt for a third. Its shape and the reasoning behind it are in
[log.md](/log.md).

## Gotchas

* **Foreign keys are not enforced.** SQLite requires `PRAGMA foreign_keys = ON` per connection, and it is never set — so the `ON DELETE CASCADE` clauses do nothing. Deleting an interview leaves orphaned personas, links, sessions, and turns. Deleting a persona out from under a live session is the case the API handles explicitly: `POST /turns` returns **410**.
* Timestamps are ISO strings via `datetime.now(UTC).isoformat()`; reads do `.replace("Z", "+00:00")` before `fromisoformat`.
* `raw_model_output` is excluded from the persona JSON on save.
* `updated_at` on a candidate upsert is set to the same value as `created_at` in the insert branch — on conflict only `updated_at` moves, so `created_at` correctly reflects the first cast.
* The gotchas above describe **SQLite**, which is still what runs. On Postgres the FK-enforcement gap closes — see the Postgres section for the one FK that is deliberately not carried over, and why the others becoming real is the point.

## Related

[repository.py](/concepts/modules/control-plane-repository.md) ·
[Storage ports](/concepts/contracts/storage-ports.md) ·
[Session recording](/concepts/contracts/session-recording.md)
