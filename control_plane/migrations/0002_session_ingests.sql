-- The Go engine's end-of-session write-back (docs/ENGINE_IMPLEMENTATION_PLAN.md
-- §8.2). One row per session, replaced on a repeated ingest: the engine
-- retries with the session id as its idempotency key, and the newest payload
-- wins. The transcript it carries is written into session_turns by the
-- repository; this row keeps the payload whole for anything the turn table
-- does not model (metrics, degradations, ceiling flags, the unlock flip).
CREATE TABLE session_ingests (
    session_id text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    payload jsonb NOT NULL
        CHECK (jsonb_typeof(payload) = 'object'),
    engine_version text NOT NULL,
    contract_fingerprint text NOT NULL,
    end_reason text NOT NULL
        CHECK (end_reason IN ('interviewer_ended', 'abandoned', 'duration_cap', 'cost_cap', 'error')),
    first_received_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL
);
