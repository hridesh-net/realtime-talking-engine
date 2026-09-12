-- 0001_initial — the control-plane schema on Postgres.
--
-- A faithful translation of the SQLite `_SCHEMA` in control_plane/database.py,
-- with four systematic changes:
--
--   * every JSON-bearing TEXT column becomes `jsonb`, with a
--     `jsonb_typeof` CHECK wherever the shape is fixed;
--   * every timestamp column becomes `timestamptz` (they were ISO strings);
--   * `session_reports.language_gate` becomes a real `boolean`;
--   * `ON DELETE CASCADE` becomes real. SQLite never enforced it — see the
--     comment on `sessions.candidate_id` for the two places that mattered.
--
-- Id columns stay `text` on purpose: candidate ids are `vc-<sha256[:12]>` and
-- `ai-<interview>-<n>`, derived from a cast seed, not uuids.
--
-- CHECK (x IN (...)) is kept in preference to native enum types. The lists
-- mirror the Pydantic patterns and change with them, and `ALTER TYPE ... ADD
-- VALUE` cannot run in the same transaction that then reads the new value —
-- which is exactly what a migration in this runner would try to do.

CREATE TABLE interviews (
    id text PRIMARY KEY,
    job_title text NOT NULL,
    jd text NOT NULL,
    skills_required jsonb NOT NULL
        CHECK (jsonb_typeof(skills_required) = 'array'),
    job_location_type text NOT NULL CHECK (job_location_type IN ('remote', 'onsite', 'hybrid')),
    experience_level text NOT NULL CHECK (experience_level IN ('junior', 'mid', 'senior')),
    company_type text NOT NULL CHECK (company_type IN ('startup', 'mnc')),
    mode text NOT NULL DEFAULT 'live_interview'
        CHECK (mode IN ('live_interview', 'training_interviewer')),
    location text NOT NULL DEFAULT '',
    department text NOT NULL DEFAULT '',
    manager_level text NOT NULL DEFAULT '',
    language text NOT NULL DEFAULT 'english_indian'
        CHECK (language IN ('english_indian', 'hinglish', 'hindi')),
    -- Recorded only. Nothing in this service accesses a camera at any setting.
    proctoring text NOT NULL DEFAULT 'off'
        CHECK (proctoring IN ('off', 'identity', 'full')),
    persona_notes text NOT NULL DEFAULT '',
    role_facts jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(role_facts) = 'array'),
    report_sections jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(report_sections) = 'object'),
    status text NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'in_progress', 'completed', 'failed', 'cancelled')),
    config jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(config) = 'object'),
    ai_persona jsonb
        CHECK (ai_persona IS NULL OR jsonb_typeof(ai_persona) = 'object'),
    scheduled_at timestamptz,
    -- Never written: the unbuilt half of the lifecycle that the `in_progress`
    -- and `completed` status values already imply. They stay for that reason.
    started_at timestamptz,
    completed_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX idx_interviews_status ON interviews(status);
CREATE INDEX idx_interviews_experience_level ON interviews(experience_level);

CREATE TABLE virtual_candidates (
    candidate_id text PRIMARY KEY,
    interview_id text NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    archetype text NOT NULL,
    archetype_label text NOT NULL,
    name text NOT NULL,
    headline text,
    verdict text NOT NULL CHECK (verdict IN ('select', 'reject', 'borderline')),
    persona_version text NOT NULL DEFAULT 'v1.0',
    catalog_version text NOT NULL DEFAULT 'v1.0',
    persona_json jsonb NOT NULL
        CHECK (jsonb_typeof(persona_json) = 'object'),
    fingerprint text NOT NULL,
    seed_fingerprint text NOT NULL,
    seed text NOT NULL,
    model_used text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    -- The unique constraint is the design: re-casting an archetype replaces
    -- rather than duplicating, through repository.py's
    -- `ON CONFLICT(interview_id, archetype) DO UPDATE`.
    UNIQUE (interview_id, archetype)
);

CREATE INDEX idx_candidates_interview ON virtual_candidates(interview_id);
CREATE INDEX idx_candidates_verdict ON virtual_candidates(verdict);

CREATE TABLE interview_expectations (
    id text PRIMARY KEY,
    interview_id text NOT NULL UNIQUE REFERENCES interviews(id) ON DELETE CASCADE,
    expectation_version text NOT NULL DEFAULT 'v1.0',
    expectation_json jsonb NOT NULL
        CHECK (jsonb_typeof(expectation_json) = 'object'),
    model_used text,
    created_at timestamptz NOT NULL
);

CREATE TABLE sessions (
    id text PRIMARY KEY,
    interview_id text NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    -- NO FOREIGN KEY, deliberately, even though the SQLite DDL declared one.
    -- SQLite never enforced it (foreign_keys defaults to OFF and is never set),
    -- so two shipped behaviours depend on this reference being inert:
    --
    --   1. Deleting a persona must leave its sessions readable. The repository
    --      renders the missing name as "(deleted persona)" and the API answers
    --      410 on POST /turns. A real ON DELETE CASCADE would instead destroy
    --      the transcript, which is the evaluation layer's only evidence that
    --      the interview happened.
    --   2. Re-casting an archetype REWRITES virtual_candidates' primary key,
    --      via `ON CONFLICT (interview_id, archetype) DO UPDATE SET
    --      candidate_id = excluded.candidate_id` in repository.py. A row
    --      referencing the old key would block that update.
    --
    -- Enforcing this FK is therefore a product change, not a tidy-up.
    candidate_id text NOT NULL,
    archetype text NOT NULL,
    status text NOT NULL DEFAULT 'live'
        CHECK (status IN ('live', 'completed', 'abandoned')),
    modality text NOT NULL DEFAULT 'text' CHECK (modality IN ('text', 'voice')),
    planned_minutes integer NOT NULL CHECK (planned_minutes >= 0),
    -- Denormalised on purpose: for a text session it is also turn 0 of the
    -- transcript, and re-reading it from the persona later would silently
    -- change the stored record if the persona were re-cast.
    opening_line text NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    created_at timestamptz NOT NULL
);

CREATE INDEX idx_sessions_interview ON sessions(interview_id);
CREATE INDEX idx_sessions_status ON sessions(status);

-- The transcript. (session_id, idx) is the primary key rather than a surrogate
-- id: turn order is the conversation, and a duplicate index is a bug worth a
-- constraint violation instead of a silently reordered replay.
CREATE TABLE session_turns (
    session_id text NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx integer NOT NULL CHECK (idx >= 0),
    speaker text NOT NULL CHECK (speaker IN ('manager', 'candidate')),
    text text NOT NULL,
    at timestamptz NOT NULL,
    elapsed_ms integer NOT NULL CHECK (elapsed_ms >= 0),
    PRIMARY KEY (session_id, idx)
);

CREATE TABLE session_analyses (
    -- One analysis per session. The row is created the moment analysis starts
    -- rather than when it finishes, so a caller can tell "running" from "never
    -- asked for" - the analysis takes about a minute and the UI has to show
    -- something in between.
    session_id text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'complete', 'failed')),
    analysis_json jsonb
        CHECK (analysis_json IS NULL OR jsonb_typeof(analysis_json) = 'object'),
    error text NOT NULL DEFAULT '',
    -- Denormalised for the list view and for cohort segmentation. Two analyses
    -- are only comparable when the instructions and the model match.
    instructions_version text NOT NULL DEFAULT '',
    model_used text NOT NULL DEFAULT '',
    session_judgement double precision,
    dropped_anchors integer NOT NULL DEFAULT 0 CHECK (dropped_anchors >= 0),
    windows integer NOT NULL DEFAULT 0 CHECK (windows >= 0),
    started_at timestamptz NOT NULL,
    finished_at timestamptz
);

CREATE TABLE session_reports (
    -- One report per session, keyed by the session, for the same reason the
    -- recording is: the stable identity is "this session's report", whatever
    -- produced it. Regenerating overwrites in place; there is no history.
    session_id text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    report_json jsonb NOT NULL
        CHECK (jsonb_typeof(report_json) = 'object'),
    -- Denormalised out of the JSON so the list view can render a row and the
    -- cohort view can segment without parsing every report.
    readiness_index integer,
    band text NOT NULL DEFAULT '',
    unscoreable text NOT NULL DEFAULT '',
    scoring_version text NOT NULL,
    rubric_version text NOT NULL,
    english_weight double precision,
    -- Was INTEGER DEFAULT 1 on SQLite, which has no boolean type.
    language_gate boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- One recording per session; the artifact's identity IS the session, whoever
-- produced it. Bytes live outside the database (RECORDINGS_DIR today; S3 when
-- the Go engine's Finalizer becomes the producer). Channel semantics are
-- contract: left = the manager's mic, right = the persona -- the same split as
-- the engine Recorder port's WriteHuman/WritePersona.
CREATE TABLE session_recordings (
    session_id text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'recording' CHECK (status IN ('recording', 'complete')),
    producer text NOT NULL DEFAULT 'browser' CHECK (producer IN ('browser', 'engine')),
    mime_type text NOT NULL,
    storage_key text NOT NULL,
    byte_size bigint NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    next_seq integer NOT NULL DEFAULT 0 CHECK (next_seq >= 0),
    channel_layout text NOT NULL DEFAULT 'manager_left_candidate_right',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Designed, not built: nothing reads or writes this table yet. It is the
-- shape an assignment takes when a SkillBrew user is given an interview to
-- conduct against a chosen persona -- the user's performance *as the
-- interviewer* is what gets assessed. Identity belongs to SkillBrew, which
-- owns the email invitation and always hands us an opaque user id; there is
-- no AI assignee, so there is no assignee-type column.
CREATE TABLE interview_assignments (
    id text PRIMARY KEY,
    interview_id text NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    -- The persona assigned. No FOREIGN KEY, for the same reason
    -- sessions.candidate_id has none: virtual_candidates.candidate_id is
    -- derived from the cast seed, so re-casting with a seed_prefix rewrites
    -- that primary key in place via repository.py's
    -- `ON CONFLICT ... DO UPDATE SET candidate_id = excluded.candidate_id`.
    candidate_id text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'completed')),
    accepted_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL
);

CREATE INDEX idx_assignments_interview ON interview_assignments(interview_id);
CREATE INDEX idx_assignments_user ON interview_assignments(user_id);

-- Legacy. Written only at creation when mode = 'training_interviewer', by
-- control_plane/persona.py. Superseded by virtual_candidates; never read back.
CREATE TABLE ai_personas (
    candidate_id text PRIMARY KEY,
    interview_id text NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    name text NOT NULL,
    background text,
    attributes jsonb NOT NULL
        CHECK (jsonb_typeof(attributes) = 'object'),
    fingerprint text NOT NULL,
    created_at timestamptz NOT NULL
);
