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

CREATE TABLE IF NOT EXISTS interview_expectations (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL UNIQUE REFERENCES interviews(id) ON DELETE CASCADE,
    expectation_version TEXT NOT NULL DEFAULT 'v1.0',
    expectation_json TEXT NOT NULL,
    model_used TEXT,
    created_at TEXT NOT NULL
);
"""


DEFAULT_DB_PATH = "control_plane.db"


def db_path_from_env() -> str:
    """Database path from CONTROL_PLANE_DB, falling back to the default."""
    return os.getenv("CONTROL_PLANE_DB") or DEFAULT_DB_PATH


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open or create the control-plane database and apply schema."""
    conn = sqlite3.connect(str(db_path or db_path_from_env()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
