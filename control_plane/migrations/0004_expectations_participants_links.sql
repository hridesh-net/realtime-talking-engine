-- Interview expectations, participants and links (2026-09-13).
--
-- Four changes, one migration, because they arrive together as one product
-- decision (docs/INTERVIEW_EXPECTATIONS_PLAN.md, D7/D8):
--
--   * `interviews.expectations` -- the granular rubric under the four fixed
--     competencies. The competencies themselves stay in code.
--   * `participants` -- an identity join key on email, so one taker's sessions
--     across several interviews read as one history. Not a user table.
--   * `interview_links` -- a token with an expiry, enforced by whatever creates
--     the session.
--   * `sessions.participant_id` -- who held the session.
--
-- And two drops. `interview_expectations` held the retired expectation agent's
-- per-interview plan document, which the pivot replaced with a fixed rubric.
-- `interview_assignments` was designed and never built; `participants` plus a
-- link is what it was reaching for, so it goes rather than sitting in the
-- schema unwritten for a second milestone.
--
-- Every statement is guarded (`IF NOT EXISTS` / `IF EXISTS`) on purpose. This
-- file has to be correct on two paths that both really happen: a database that
-- applied the *old* 0001 and needs these changes, and a fresh database that
-- gets the reshaped 0001 -- which already carries all four -- and then reaches
-- here. An unguarded ADD COLUMN would make `migrate.apply` on an empty
-- database fail, which is exactly the path `tests/conftest.py` builds every
-- test schema through.

ALTER TABLE interviews ADD COLUMN IF NOT EXISTS expectations jsonb NOT NULL
    DEFAULT '[]'::jsonb;
ALTER TABLE interviews DROP CONSTRAINT IF EXISTS interviews_expectations_check;
ALTER TABLE interviews ADD CONSTRAINT interviews_expectations_check
    CHECK (jsonb_typeof(expectations) = 'array');

CREATE TABLE IF NOT EXISTS participants (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    name text NOT NULL,
    user_id text,
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS interview_links (
    token text PRIMARY KEY,
    interview_id text NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_links_interview ON interview_links(interview_id);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS participant_id text REFERENCES participants(id);

CREATE INDEX IF NOT EXISTS idx_sessions_participant ON sessions(participant_id);

DROP TABLE IF EXISTS interview_expectations;
DROP TABLE IF EXISTS interview_assignments;
