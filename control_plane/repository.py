"""Persistence layer for interviews and personas."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from control_plane.persona import generate_persona
from control_plane.schemas import (
    CandidatePersona,
    InterviewConfigInput,
    InterviewCreateRequest,
    InterviewResponse,
)
from expectation_agent.schema import InterviewExpectation


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class InterviewRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, req: InterviewCreateRequest) -> InterviewResponse:
        """Persist a new interview request (job spec)."""
        interview_id = _new_id()
        now = _utcnow()

        ai_persona_json = None
        ai_persona: Optional[CandidatePersona] = None

        if req.mode == "training_interviewer":
            ai_persona = generate_persona(
                requirement_id=req.job_title,
                interview_id=interview_id,
                index=0,
            )
            ai_persona_json = ai_persona.model_dump_json()

        config_json = req.config.model_dump_json()
        metadata_json = json.dumps(req.metadata)

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO interviews (
                    id, job_title, jd, skills_required,
                    job_location_type, experience_level, company_type,
                    mode, status, ai_persona, config, scheduled_at, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?, ?)
                """,
                (
                    interview_id,
                    req.job_title,
                    req.jd,
                    json.dumps(req.skills_required),
                    req.job_location_type,
                    req.experience_level,
                    req.company_type,
                    req.mode,
                    ai_persona_json,
                    config_json,
                    (req.scheduled_at.isoformat() if req.scheduled_at else None),
                    metadata_json,
                    now,
                    now,
                ),
            )
            if ai_persona:
                self.conn.execute(
                    """
                    INSERT INTO ai_personas (
                        candidate_id, interview_id, name, background, attributes, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ai_persona.candidate_id,
                        interview_id,
                        ai_persona.name,
                        ai_persona.background,
                        json.dumps([a.model_dump() for a in ai_persona.attributes]),
                        ai_persona.fingerprint,
                        now,
                    ),
                )

        return self.get(interview_id)

    def get(self, interview_id: str) -> Optional[InterviewResponse]:
        row = self.conn.execute(
            "SELECT * FROM interviews WHERE id = ?", (interview_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_response(row)

    def list(self, status: str | None = None) -> List[InterviewResponse]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM interviews WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM interviews ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_response(r) for r in rows]

    def _row_to_response(self, row: sqlite3.Row) -> InterviewResponse:
        ai_persona = None
        if row["ai_persona"]:
            ai_persona = CandidatePersona.model_validate_json(row["ai_persona"])

        config = InterviewConfigInput.model_validate_json(row["config"])
        scheduled_at = None
        if row["scheduled_at"]:
            scheduled_at = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))

        return InterviewResponse(
            id=row["id"],
            job_title=row["job_title"],
            jd=row["jd"],
            skills_required=json.loads(row["skills_required"]),
            job_location_type=row["job_location_type"],
            experience_level=row["experience_level"],
            company_type=row["company_type"],
            mode=row["mode"],
            status=row["status"],
            config=config,
            ai_persona=ai_persona,
            scheduled_at=scheduled_at,
            created_at=created_at,
            start_url=f"/api/v1/interviews/{row['id']}/start",
            metadata=json.loads(row["metadata"]),
        )

    def save_expectation(self, expectation: InterviewExpectation, model_used: str) -> None:
        """Persist an expectation document for an interview."""
        now = _utcnow()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO interview_expectations (id, interview_id, expectation_version, expectation_json, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(interview_id) DO UPDATE SET
                    expectation_json = excluded.expectation_json,
                    model_used = excluded.model_used,
                    created_at = excluded.created_at
                """,
                (
                    _new_id(),
                    expectation.interview_id,
                    expectation.expectation_version,
                    expectation.model_dump_json(exclude={"raw_model_output"}),
                    model_used,
                    now,
                ),
            )

    def get_expectation(self, interview_id: str) -> Optional[InterviewExpectation]:
        row = self.conn.execute(
            "SELECT * FROM interview_expectations WHERE interview_id = ?", (interview_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["expectation_json"])
        data["raw_model_output"] = None
        return InterviewExpectation.model_validate(data)

