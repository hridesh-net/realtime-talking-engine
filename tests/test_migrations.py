"""The migration runner, and the two schema decisions that are easy to reverse.

Needs a Postgres. `scripts/check.sh` provisions one; running this file on its
own works too, either against `TEST_DATABASE_URL` or against a throwaway Apple
`container` (see `tests/infra.py`).

Two of the tests here are not about the runner at all. `sessions.candidate_id`
carrying **no** foreign key, and deleting an interview cascading to its
sessions, are product decisions that a tidy-minded edit to the DDL would
silently reverse — SQLite never enforced either one, so nothing else in the
suite can notice.
"""

from __future__ import annotations

import secrets
import shutil
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import psycopg.errors
import psycopg.rows
import pytest

from control_plane import migrate
from tests import infra as test_infra

REAL_MIGRATIONS = migrate.DEFAULT_MIGRATIONS_DIR


# --------------------------------------------------------------- helpers ----


@pytest.fixture
def fresh_dsn(pg_admin_dsn: str) -> Iterator[str]:
    """An empty database of this test's own, dropped afterwards."""
    name = f"iw_mig_{secrets.token_hex(6)}"
    dsn = test_infra.create_database(pg_admin_dsn, name)
    try:
        yield dsn
    finally:
        test_infra.drop_database(pg_admin_dsn, name)


@pytest.fixture
def migrations_copy(tmp_path: Path) -> Path:
    """A writable copy of the real migrations directory."""
    target = tmp_path / "migrations"
    shutil.copytree(REAL_MIGRATIONS, target)
    return target


def _rows(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn, autocommit=True, row_factory=psycopg.rows.tuple_row) as conn:
        return conn.execute(sql, params).fetchall()


def _tables(dsn: str) -> set[str]:
    return {
        row[0] for row in _rows(dsn, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    }


# ------------------------------------------------------------ the runner ----


def test_apply_builds_the_schema_on_a_fresh_database(fresh_dsn: str) -> None:
    applied = migrate.apply(fresh_dsn, REAL_MIGRATIONS)

    assert applied == [1, 2, 3]
    tables = _tables(fresh_dsn)
    assert "schema_migrations" in tables
    for expected in (
        "interviews",
        "virtual_candidates",
        "interview_expectations",
        "sessions",
        "session_turns",
        "session_analyses",
        "session_reports",
        "session_recordings",
        "session_ingests",
        "interview_assignments",
        "ai_personas",
    ):
        assert expected in tables, f"{expected} was not created"


def test_the_ledger_records_the_files_checksum(fresh_dsn: str) -> None:
    migrate.apply(fresh_dsn, REAL_MIGRATIONS)

    rows = _rows(
        fresh_dsn, "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    )
    discovered = migrate.discover(REAL_MIGRATIONS)
    assert [(v, n) for v, n, _ in rows] == [
        (1, "initial"),
        (2, "session_ingests"),
        (3, "end_reason_drop_cost_cap"),
    ]
    assert [c for _, _, c in rows] == [m.checksum for m in discovered]


def test_check_is_clean_after_apply(fresh_dsn: str) -> None:
    migrate.apply(fresh_dsn, REAL_MIGRATIONS)

    code = migrate.main(["--check", "--dsn", fresh_dsn, "--migrations-dir", str(REAL_MIGRATIONS)])

    assert code == 0


def test_check_reports_pending_on_an_empty_database(fresh_dsn: str) -> None:
    code = migrate.main(["--check", "--dsn", fresh_dsn, "--migrations-dir", str(REAL_MIGRATIONS)])

    assert code == 1


def test_re_applying_is_a_no_op(fresh_dsn: str) -> None:
    migrate.apply(fresh_dsn, REAL_MIGRATIONS)

    assert migrate.apply(fresh_dsn, REAL_MIGRATIONS) == []
    assert len(_rows(fresh_dsn, "SELECT version FROM schema_migrations")) == 3


def test_an_unapplied_extra_file_is_pending_not_drift(
    fresh_dsn: str, migrations_copy: Path
) -> None:
    migrate.apply(fresh_dsn, migrations_copy)
    (migrations_copy / "0004_later.sql").write_text("CREATE TABLE later (id text PRIMARY KEY);\n")

    with psycopg.connect(fresh_dsn, autocommit=True) as conn:
        state = migrate.status(conn, migrations_copy)
    assert [m.filename for m in state.pending] == ["0004_later.sql"]
    assert state.drift == []

    code = migrate.main(["--check", "--dsn", fresh_dsn, "--migrations-dir", str(migrations_copy)])
    assert code == 1


def test_editing_an_applied_file_is_drift(fresh_dsn: str, migrations_copy: Path) -> None:
    migrate.apply(fresh_dsn, migrations_copy)
    edited = migrations_copy / "0001_initial.sql"
    edited.write_text(edited.read_text() + "\n-- a harmless-looking afterthought\n")

    with psycopg.connect(fresh_dsn, autocommit=True) as conn:
        state = migrate.status(conn, migrations_copy)
    assert state.pending == []
    assert len(state.drift) == 1
    assert "0001_initial.sql" in state.drift[0]

    code = migrate.main(["--check", "--dsn", fresh_dsn, "--migrations-dir", str(migrations_copy)])
    assert code == 2


def test_a_deleted_applied_file_is_drift(fresh_dsn: str, migrations_copy: Path) -> None:
    migrate.apply(fresh_dsn, migrations_copy)
    (migrations_copy / "0001_initial.sql").unlink()

    code = migrate.main(["--check", "--dsn", fresh_dsn, "--migrations-dir", str(migrations_copy)])

    assert code == 2


def test_a_migration_that_fails_midway_records_nothing_for_itself(
    fresh_dsn: str, migrations_copy: Path
) -> None:
    """The whole file is one transaction, so a half-run file leaves no trace."""
    (migrations_copy / "0004_broken.sql").write_text(
        "CREATE TABLE half_built (id text PRIMARY KEY);\n"
        "CREATE TABLE half_built (id text PRIMARY KEY);\n"  # same name: raises
    )

    with pytest.raises(psycopg.Error):
        migrate.apply(fresh_dsn, migrations_copy)

    # 0001-0003 ran before 0004 and stay applied; 0004 recorded nothing at all.
    assert [row[0] for row in _rows(fresh_dsn, "SELECT version FROM schema_migrations")] == [
        1,
        2,
        3,
    ]
    assert "half_built" not in _tables(fresh_dsn)
    assert "interviews" in _tables(fresh_dsn)


def test_assert_current_names_the_pending_file(fresh_dsn: str) -> None:
    with psycopg.connect(fresh_dsn, autocommit=True) as conn:
        with pytest.raises(migrate.MigrationError) as caught:
            migrate.assert_current(conn, REAL_MIGRATIONS)
        assert "0001_initial.sql" in str(caught.value)

        migrate.apply(fresh_dsn, REAL_MIGRATIONS)
        migrate.assert_current(conn, REAL_MIGRATIONS)  # no longer raises


def test_the_advisory_lock_serialises_two_runners(fresh_dsn: str, migrations_copy: Path) -> None:
    """Two runners racing must not both execute the same migration.

    The migration sleeps, so the second runner is guaranteed to arrive while
    the first is still inside its transaction. Without the advisory lock it
    would read an empty ledger, run the CREATE TABLE too, and one of the two
    would die on a duplicate relation or a duplicate ledger key. With it, the
    loser waits, re-reads under the lock, and finds the work already done.
    """
    (migrations_copy / "0004_slow.sql").write_text(
        "SELECT pg_sleep(0.75);\nCREATE TABLE lock_probe (id text PRIMARY KEY);\n"
    )
    migrate.apply(fresh_dsn, REAL_MIGRATIONS)  # get 0001 out of the way

    results: list[list[int]] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def runner() -> None:
        start.wait()
        try:
            results.append(migrate.apply(fresh_dsn, migrations_copy))
        except BaseException as exc:  # reported below, never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=runner) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"a runner raised: {errors}"
    every = sorted(v for result in results for v in result)
    assert every == [4], "version 4 was applied more than once"
    assert "lock_probe" in _tables(fresh_dsn)
    assert len(_rows(fresh_dsn, "SELECT version FROM schema_migrations")) == 4


# ---------------------------------------- the two foreign-key decisions ----


def _fk_columns(conn: psycopg.Connection, table: str) -> set[str]:
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_constraint c
            JOIN unnest(c.conkey) AS k(attnum) ON true
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            WHERE c.contype = 'f' AND c.conrelid = %s::regclass
            """,
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


def test_sessions_candidate_id_has_no_foreign_key(conn: psycopg.Connection) -> None:
    """Deleting a persona must leave the transcript standing.

    The API answers 410 on POST /turns for a deleted persona and the repository
    renders the name as "(deleted persona)"; both are only reachable because the
    session row survives. A real FK here would either cascade the transcript
    away — the evaluation layer's only evidence — or block the persona delete.
    It would also block the `ON CONFLICT ... DO UPDATE SET candidate_id =
    excluded.candidate_id` upsert that a re-cast performs.
    """
    columns = _fk_columns(conn, "sessions")

    assert "candidate_id" not in columns
    assert "interview_id" in columns, "the interview FK is meant to be real"


def test_assignments_candidate_id_has_no_foreign_key(conn: psycopg.Connection) -> None:
    columns = _fk_columns(conn, "interview_assignments")

    assert "candidate_id" not in columns
    assert "interview_id" in columns


def _seed_interview_with_a_session(conn: psycopg.Connection) -> None:
    now = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO interviews (
            id, job_title, jd, skills_required, job_location_type,
            experience_level, company_type, created_at, updated_at
        ) VALUES ('iv-1', 'SRE', 'jd', '["k8s"]'::jsonb, 'remote', 'mid', 'startup', %s, %s)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO virtual_candidates (
            candidate_id, interview_id, archetype, archetype_label, name, verdict,
            persona_json, fingerprint, seed_fingerprint, seed, created_at, updated_at
        ) VALUES ('vc-1', 'iv-1', 'strong', 'Strong', 'Asha', 'select',
                  '{}'::jsonb, 'fp', 'sfp', 'seed', %s, %s)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO sessions (
            id, interview_id, candidate_id, archetype, planned_minutes,
            opening_line, started_at, created_at
        ) VALUES ('s-1', 'iv-1', 'vc-1', 'strong', 30, 'Hello.', %s, %s)
        """,
        (now, now),
    )
    conn.execute(
        "INSERT INTO session_turns (session_id, idx, speaker, text, at, elapsed_ms) "
        "VALUES ('s-1', 0, 'candidate', 'Hello.', %s, 0)",
        (now,),
    )


def _count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        return int(cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # type: ignore[index]


def test_deleting_an_interview_cascades_to_its_sessions(conn: psycopg.Connection) -> None:
    """Every cascade except the candidate one is intended to be real now.

    On SQLite these clauses were inert, so deleting an interview left orphaned
    personas, sessions and turns behind. Postgres enforces them.
    """
    _seed_interview_with_a_session(conn)
    assert _count(conn, "sessions") == 1

    conn.execute("DELETE FROM interviews WHERE id = 'iv-1'")

    assert _count(conn, "sessions") == 0
    assert _count(conn, "session_turns") == 0
    assert _count(conn, "virtual_candidates") == 0


def test_deleting_a_persona_leaves_the_session_and_its_transcript(
    conn: psycopg.Connection,
) -> None:
    """The behaviour the missing FK exists for, asserted directly."""
    _seed_interview_with_a_session(conn)

    conn.execute("DELETE FROM virtual_candidates WHERE candidate_id = 'vc-1'")

    assert _count(conn, "sessions") == 1
    assert _count(conn, "session_turns") == 1


def test_a_recast_may_rewrite_the_candidate_primary_key(conn: psycopg.Connection) -> None:
    """The second reason the FK is absent: the upsert moves the key itself."""
    _seed_interview_with_a_session(conn)

    conn.execute("UPDATE virtual_candidates SET candidate_id = 'vc-2' WHERE candidate_id = 'vc-1'")

    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        row = cur.execute("SELECT candidate_id FROM sessions WHERE id = 's-1'").fetchone()
    assert row is not None
    assert row[0] == "vc-1", "the session keeps pointing at the id it was started with"


# ----------------------------------------------------- the type mapping ----


def test_json_columns_are_jsonb_and_timestamps_are_timestamptz(
    conn: psycopg.Connection,
) -> None:
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        cur.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        types = {(t, c): d for t, c, d in cur.fetchall()}

    for table, column in (
        ("interviews", "skills_required"),
        ("interviews", "role_facts"),
        ("interviews", "config"),
        ("interviews", "metadata"),
        ("interviews", "ai_persona"),
        ("virtual_candidates", "persona_json"),
        ("interview_expectations", "expectation_json"),
        ("session_analyses", "analysis_json"),
        ("session_reports", "report_json"),
        ("ai_personas", "attributes"),
    ):
        assert types[(table, column)] == "jsonb", f"{table}.{column} is not jsonb"

    for table, column in (
        ("interviews", "created_at"),
        ("sessions", "started_at"),
        ("session_turns", "at"),
        ("session_recordings", "updated_at"),
        ("schema_migrations", "applied_at"),
    ):
        assert types[(table, column)] == "timestamp with time zone", f"{table}.{column}"

    assert types[("session_reports", "language_gate")] == "boolean"
    assert types[("session_recordings", "byte_size")] == "bigint"


def test_a_json_column_rejects_the_wrong_shape(conn: psycopg.Connection) -> None:
    """`skills_required` is a list everywhere in the code; the CHECK says so."""
    now = datetime.now(UTC)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """
            INSERT INTO interviews (
                id, job_title, jd, skills_required, job_location_type,
                experience_level, company_type, created_at, updated_at
            ) VALUES ('iv-bad', 'SRE', 'jd', '{"k8s": true}'::jsonb, 'remote',
                      'mid', 'startup', %s, %s)
            """,
            (now, now),
        )
