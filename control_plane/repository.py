"""Persistence layer for interviews and personas."""

from __future__ import annotations

import builtins
import json
import sqlite3
import uuid
from datetime import UTC, datetime

from candidate_agent.schema import VirtualCandidate
from control_plane.persona import generate_persona
from control_plane.schemas import (
    CandidatePersona,
    InterviewConfigInput,
    InterviewCreateRequest,
    InterviewResponse,
)
from expectation_agent.schema import InterviewExpectation


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class InterviewRepository:
    """SQLite adapter implementing every storage port in `control_plane.ports`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, req: InterviewCreateRequest) -> InterviewResponse:
        """Persist a new interview request (job spec)."""
        interview_id = _new_id()
        now = _utcnow()

        ai_persona_json = None
        ai_persona: CandidatePersona | None = None

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
                        candidate_id, interview_id, name, background, attributes,
                        fingerprint, created_at
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

        created = self.get(interview_id)
        if created is None:  # pragma: no cover - the insert above just succeeded
            raise RuntimeError(f"interview {interview_id} vanished after insert")
        return created

    def get(self, interview_id: str) -> InterviewResponse | None:
        """Return one interview, or None when it does not exist."""
        row = self.conn.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        if not row:
            return None
        return self._row_to_response(row)

    def list(self, status: str | None = None) -> builtins.list[InterviewResponse]:
        """Return interviews, newest first, optionally filtered by status."""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM interviews WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM interviews ORDER BY created_at DESC").fetchall()
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
                INSERT INTO interview_expectations (
                    id, interview_id, expectation_version, expectation_json,
                    model_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
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

    def get_expectation(self, interview_id: str) -> InterviewExpectation | None:
        """Return the stored expectation, or None when not generated yet."""
        row = self.conn.execute(
            "SELECT * FROM interview_expectations WHERE interview_id = ?", (interview_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["expectation_json"])
        data["raw_model_output"] = None
        return InterviewExpectation.model_validate(data)

    # ------------------------------------------------------------------
    # Virtual candidates
    # ------------------------------------------------------------------

    def save_candidate(self, candidate: VirtualCandidate, model_used: str) -> None:
        """Upsert a persona. Re-enrolling an archetype replaces the old cast."""
        now = _utcnow()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO virtual_candidates (
                    candidate_id, interview_id, archetype, archetype_label, name, headline,
                    verdict, persona_version, catalog_version, persona_json, fingerprint,
                    seed_fingerprint, seed, model_used, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interview_id, archetype) DO UPDATE SET
                    candidate_id = excluded.candidate_id,
                    name = excluded.name,
                    headline = excluded.headline,
                    verdict = excluded.verdict,
                    persona_json = excluded.persona_json,
                    fingerprint = excluded.fingerprint,
                    seed_fingerprint = excluded.seed_fingerprint,
                    seed = excluded.seed,
                    model_used = excluded.model_used,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.candidate_id,
                    candidate.interview_id,
                    candidate.archetype,
                    candidate.archetype_label,
                    candidate.name,
                    candidate.headline,
                    candidate.verdict,
                    candidate.persona_version,
                    candidate.catalog_version,
                    candidate.model_dump_json(exclude={"raw_model_output"}),
                    candidate.fingerprint,
                    candidate.seed_fingerprint,
                    candidate.seed,
                    model_used,
                    now,
                    now,
                ),
            )

    def list_candidates(self, interview_id: str) -> builtins.list[VirtualCandidate]:
        """Return every persona enrolled for an interview."""
        rows = self.conn.execute(
            """
            SELECT persona_json FROM virtual_candidates
            WHERE interview_id = ? ORDER BY created_at ASC
            """,
            (interview_id,),
        ).fetchall()
        return [VirtualCandidate.model_validate_json(r["persona_json"]) for r in rows]

    def get_candidate(self, candidate_id: str) -> VirtualCandidate | None:
        """Return one persona, or None when it does not exist."""
        row = self.conn.execute(
            "SELECT persona_json FROM virtual_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if not row:
            return None
        return VirtualCandidate.model_validate_json(row["persona_json"])

    def get_candidate_by_archetype(
        self, interview_id: str, archetype: str
    ) -> VirtualCandidate | None:
        """Return the persona cast for this archetype, if one is enrolled."""
        row = self.conn.execute(
            "SELECT persona_json FROM virtual_candidates WHERE interview_id = ? AND archetype = ?",
            (interview_id, archetype),
        ).fetchone()
        if not row:
            return None
        return VirtualCandidate.model_validate_json(row["persona_json"])

    def delete_candidate(self, candidate_id: str) -> bool:
        """Remove a persona. True when a row was deleted."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM virtual_candidates WHERE candidate_id = ?", (candidate_id,)
            )
        return cur.rowcount > 0
