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
    SessionResponse,
    SessionSummary,
    Turn,
)
from expectation_agent.schema import InterviewExpectation


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _parse_ts(value: str) -> datetime:
    """Read a stored ISO timestamp back as an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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

    # ------------------------------------------------------------------
    # Live sessions
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        interview_id: str,
        candidate_id: str,
        persona_key: str,
        planned_minutes: int,
        opening_line: str,
        modality: str = "text",
    ) -> SessionResponse:
        """Open a session, seeding turn 0 with the persona's opening line.

        The opening turn is written in the same transaction as the session row:
        a session whose transcript does not start with the line the persona
        actually said would misreport time-to-first-question for every manager.
        """
        session_id = _new_id()
        now = _utcnow()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sessions (
                    id, interview_id, candidate_id, persona_key, status, modality,
                    planned_minutes, opening_line, started_at, created_at
                ) VALUES (?, ?, ?, ?, 'live', ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    interview_id,
                    candidate_id,
                    persona_key,
                    modality,
                    planned_minutes,
                    opening_line,
                    now,
                    now,
                ),
            )
            if modality == "text":
                # Voice sessions deliberately skip this: the persona *says* its
                # opening line over the audio channel, and the browser reports it
                # back like any other turn. Writing it here too would duplicate
                # turn 0 and shift every elapsed_ms the report reads.
                self.conn.execute(
                    """
                    INSERT INTO session_turns (session_id, idx, speaker, text, at, elapsed_ms)
                    VALUES (?, 0, 'candidate', ?, ?, 0)
                    """,
                    (session_id, opening_line, now),
                )

        created = self.get_session(session_id)
        if created is None:  # pragma: no cover - the insert above just succeeded
            raise RuntimeError(f"session {session_id} vanished after insert")
        return created

    def get_session(self, session_id: str) -> SessionResponse | None:
        """Return one session with its full transcript, or None."""
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        name_row = self.conn.execute(
            "SELECT name FROM virtual_candidates WHERE candidate_id = ?",
            (row["candidate_id"],),
        ).fetchone()
        turns = self.conn.execute(
            "SELECT * FROM session_turns WHERE session_id = ? ORDER BY idx ASC",
            (session_id,),
        ).fetchall()
        return SessionResponse(
            id=row["id"],
            interview_id=row["interview_id"],
            candidate_id=row["candidate_id"],
            persona_key=row["persona_key"],
            candidate_name=(name_row["name"] if name_row else "(deleted persona)"),
            status=row["status"],
            modality=row["modality"],
            planned_minutes=row["planned_minutes"],
            started_at=_parse_ts(row["started_at"]),
            ended_at=(_parse_ts(row["ended_at"]) if row["ended_at"] else None),
            opening_line=row["opening_line"],
            turns=[
                Turn(
                    index=t["idx"],
                    speaker=t["speaker"],
                    text=t["text"],
                    at=_parse_ts(t["at"]),
                    elapsed_ms=t["elapsed_ms"],
                )
                for t in turns
            ],
        )

    def list_sessions(self, interview_id: str) -> builtins.list[SessionSummary]:
        """Every session held against one interview, newest first, no transcripts."""
        rows = self.conn.execute(
            """
            SELECT s.*,
                   COALESCE(v.name, '(deleted persona)') AS candidate_name,
                   (SELECT COUNT(*) FROM session_turns t WHERE t.session_id = s.id) AS turn_count
            FROM sessions s
            LEFT JOIN virtual_candidates v ON v.candidate_id = s.candidate_id
            WHERE s.interview_id = ?
            ORDER BY s.started_at DESC
            """,
            (interview_id,),
        ).fetchall()
        return [
            SessionSummary(
                id=r["id"],
                interview_id=r["interview_id"],
                persona_key=r["persona_key"],
                candidate_name=r["candidate_name"],
                status=r["status"],
                modality=r["modality"],
                planned_minutes=r["planned_minutes"],
                started_at=_parse_ts(r["started_at"]),
                ended_at=(_parse_ts(r["ended_at"]) if r["ended_at"] else None),
                turn_count=int(r["turn_count"]),
            )
            for r in rows
        ]

    def append_turn(self, session_id: str, speaker: str, text: str) -> Turn:
        """Append a turn, stamping its index, wall time, and elapsed offset."""
        row = self.conn.execute(
            "SELECT started_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"session {session_id} does not exist")

        at = datetime.now(UTC)
        elapsed_ms = max(0, int((at - _parse_ts(row["started_at"])).total_seconds() * 1000))
        with self.conn:
            cur = self.conn.execute(
                "SELECT COALESCE(MAX(idx) + 1, 0) AS next FROM session_turns WHERE session_id = ?",
                (session_id,),
            )
            index = int(cur.fetchone()["next"])
            self.conn.execute(
                """
                INSERT INTO session_turns (session_id, idx, speaker, text, at, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, index, speaker, text, at.isoformat(), elapsed_ms),
            )
        return Turn(index=index, speaker=speaker, text=text, at=at, elapsed_ms=elapsed_ms)

    def end_session(self, session_id: str, status: str = "completed") -> SessionResponse | None:
        """Close a session. Returns the final record, or None when unknown."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE sessions SET status = ?, ended_at = ? WHERE id = ? AND status = 'live'",
                (status, _utcnow(), session_id),
            )
        if cur.rowcount == 0 and self.get_session(session_id) is None:
            return None
        return self.get_session(session_id)
