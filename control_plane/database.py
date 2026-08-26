"""SQLite storage for the interview control-plane."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    job_title TEXT NOT NULL,
    jd TEXT NOT NULL,
    skills_required TEXT NOT NULL,
    job_location_type TEXT NOT NULL CHECK (job_location_type IN ('remote', 'onsite', 'hybrid')),
    experience_level TEXT NOT NULL CHECK (experience_level IN ('junior', 'mid', 'senior')),
    company_type TEXT NOT NULL CHECK (company_type IN ('startup', 'mnc')),
    mode TEXT NOT NULL DEFAULT 'live_interview'
        CHECK (mode IN ('live_interview', 'training_interviewer')),
    location TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    manager_level TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'english_indian'
        CHECK (language IN ('english_indian', 'hinglish', 'hindi')),
    -- Recorded only. Nothing in this service accesses a camera at any setting.
    proctoring TEXT NOT NULL DEFAULT 'off'
        CHECK (proctoring IN ('off', 'identity', 'full')),
    candidate_notes TEXT NOT NULL DEFAULT '',
    clarity_facts TEXT NOT NULL DEFAULT '[]',
    report_sections TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'in_progress', 'completed', 'failed', 'cancelled')),
    config TEXT NOT NULL DEFAULT '{}',
    ai_persona TEXT,
    scheduled_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    recording_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_reports (
    -- One report per session, keyed by the session, for the same reason the
    -- recording is: the stable identity is "this session's report", whatever
    -- produced it. Regenerating overwrites in place; there is no history.
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    report_json TEXT NOT NULL,
    -- Denormalised out of the JSON so the list view can render a row and the
    -- cohort view can segment without parsing every report.
    readiness_index INTEGER,
    band TEXT NOT NULL DEFAULT '',
    unscoreable TEXT NOT NULL DEFAULT '',
    scoring_version TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    english_weight REAL,
    language_gate INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interview_assignments (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    interviewer_id TEXT NOT NULL,
    interviewer_type TEXT NOT NULL CHECK (interviewer_type IN ('human', 'ai')),
    task_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (task_status IN ('pending', 'accepted', 'rejected', 'completed')),
    accepted_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_personas (
    candidate_id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    background TEXT,
    attributes TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interviews_status ON interviews(status);
CREATE INDEX IF NOT EXISTS idx_interviews_experience_level ON interviews(experience_level);
CREATE INDEX IF NOT EXISTS idx_assignments_interview ON interview_assignments(interview_id);
CREATE INDEX IF NOT EXISTS idx_assignments_interviewer ON interview_assignments(interviewer_id);

CREATE TABLE IF NOT EXISTS virtual_candidates (
    candidate_id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    archetype TEXT NOT NULL,
    archetype_label TEXT NOT NULL,
    name TEXT NOT NULL,
    headline TEXT,
    verdict TEXT NOT NULL CHECK (verdict IN ('select', 'reject', 'borderline')),
    persona_version TEXT NOT NULL DEFAULT 'v1.0',
    catalog_version TEXT NOT NULL DEFAULT 'v1.0',
    persona_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    seed_fingerprint TEXT NOT NULL,
    seed TEXT NOT NULL,
    model_used TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (interview_id, archetype)
);

CREATE INDEX IF NOT EXISTS idx_candidates_interview ON virtual_candidates(interview_id);
CREATE INDEX IF NOT EXISTS idx_candidates_verdict ON virtual_candidates(verdict);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES virtual_candidates(candidate_id) ON DELETE CASCADE,
    persona_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'live'
        CHECK (status IN ('live', 'completed', 'abandoned')),
    modality TEXT NOT NULL DEFAULT 'text' CHECK (modality IN ('text', 'voice')),
    planned_minutes INTEGER NOT NULL,
    opening_line TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    created_at TEXT NOT NULL
);

-- The transcript. (session_id, idx) is the primary key rather than a surrogate
-- id: turn order is the conversation, and a duplicate index is a bug worth a
-- constraint violation instead of a silently reordered replay.
CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    speaker TEXT NOT NULL CHECK (speaker IN ('manager', 'candidate')),
    text TEXT NOT NULL,
    at TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_sessions_interview ON sessions(interview_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS interview_expectations (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL UNIQUE REFERENCES interviews(id) ON DELETE CASCADE,
    expectation_version TEXT NOT NULL DEFAULT 'v1.0',
    expectation_json TEXT NOT NULL,
    model_used TEXT,
    created_at TEXT NOT NULL
);

-- One recording per session; the artifact's identity IS the session, whoever
-- produced it. Bytes live outside SQLite (RECORDINGS_DIR today; S3 when the
-- Go engine's Finalizer becomes the producer). Channel semantics are contract:
-- left = the manager's mic, right = the persona -- the same split as the
-- engine Recorder port's WriteHuman/WritePersona.
CREATE TABLE IF NOT EXISTS session_recordings (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'recording' CHECK (status IN ('recording', 'complete')),
    producer TEXT NOT NULL DEFAULT 'browser' CHECK (producer IN ('browser', 'engine')),
    mime_type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0,
    next_seq INTEGER NOT NULL DEFAULT 0,
    channel_layout TEXT NOT NULL DEFAULT 'manager_left_candidate_right',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


DEFAULT_DB_PATH = "control_plane.db"

#: Where session audio artifacts land on disk (RECORDINGS_DIR env), relative
#: to the process working directory, mirroring DEFAULT_DB_PATH.
DEFAULT_RECORDINGS_DIR = "recordings"


def db_path_from_env() -> str:
    """Database path from CONTROL_PLANE_DB, falling back to the default."""
    return os.getenv("CONTROL_PLANE_DB") or DEFAULT_DB_PATH


def recordings_dir_from_env() -> str:
    """Recordings directory from RECORDINGS_DIR, falling back to the default."""
    return os.getenv("RECORDINGS_DIR") or DEFAULT_RECORDINGS_DIR


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open or create the control-plane database and apply schema."""
    conn = sqlite3.connect(str(db_path or db_path_from_env()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
