#!/usr/bin/env python3
"""Bring an existing SQLite control-plane database in line with the renamed schema.

There are no migrations in this repo: `control_plane/database.py` applies its
`_SCHEMA` with `CREATE TABLE IF NOT EXISTS`, so renaming a column in the DDL
changes nothing about a database that already exists — the old column simply
stays, and the code that now asks for the new name fails at runtime. This
script is the one-off that closes that gap for the 2026-09-10 naming cleanup.

It is deliberately idempotent: every step checks the live schema first and
skips work that has already happened, so re-running it on an up-to-date
database is a no-op that reports "already renamed" rather than an error. That
matters because the only way to know whether a given `.db` file has been
through it is to look.

    scripts/rename_columns_sqlite.py --db control_plane.db --dry-run
    scripts/rename_columns_sqlite.py --db control_plane.db

What it does:

* `interviews.candidate_notes` -> `persona_notes`
* `interviews.clarity_facts`   -> `role_facts`
* `interviews.recording_id`    -> dropped (recordings are per *session*, and
  live in `session_recordings`; the per-interview pointer contradicted the
  model and was never written). Dropped only when every row holds NULL.
* `sessions.persona_key`       -> `archetype`
* `interview_assignments`      -> recreated with the new shape, and **only
  when it is empty**. Its shape changes rather than just its names — the
  assignee type is gone and a `candidate_id` is added — so there is no
  rename that preserves rows, and silently discarding them would be worse
  than refusing.

The old names appear throughout this file on purpose: it is the one place in
the tree that has to know both sides of the rename.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "control_plane.db"

#: (table, old column, new column) for the plain `ALTER TABLE ... RENAME COLUMN`
#: cases. SQLite has supported it since 3.25.
RENAMES: tuple[tuple[str, str, str], ...] = (
    ("interviews", "candidate_notes", "persona_notes"),
    ("interviews", "clarity_facts", "role_facts"),
    ("sessions", "persona_key", "archetype"),
)

#: Columns to remove outright, with the guard that must hold first: the column
#: has to be empty in every row, or the drop is destructive and we stop.
DROPS: tuple[tuple[str, str], ...] = (("interviews", "recording_id"),)

NEW_ASSIGNMENTS_DDL = """
CREATE TABLE interview_assignments (
    id TEXT PRIMARY KEY,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected', 'completed')),
    accepted_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
)
"""

NEW_ASSIGNMENTS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_assignments_interview ON interview_assignments(interview_id)",
    "CREATE INDEX IF NOT EXISTS idx_assignments_user ON interview_assignments(user_id)",
)


class AbortedError(Exception):
    """A guard failed. Nothing was written."""


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def rename_column(
    conn: sqlite3.Connection, table: str, old: str, new: str, *, dry_run: bool
) -> str:
    """One `ALTER TABLE ... RENAME COLUMN`, or a reason it was not needed."""
    if not table_exists(conn, table):
        return f"{table}.{old} -> {new}: SKIP (no such table)"
    cols = columns(conn, table)
    if new in cols and old not in cols:
        return f"{table}.{old} -> {new}: already renamed"
    if old not in cols:
        return f"{table}.{old} -> {new}: SKIP (no such column)"
    if new in cols:
        raise AbortedError(
            f"{table} has both {old} and {new}; refusing to guess which one the code means"
        )
    if not dry_run:
        conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    return f"{table}.{old} -> {new}: renamed"


def drop_column(conn: sqlite3.Connection, table: str, column: str, *, dry_run: bool) -> str:
    """Drop a column, but only once it is proven to hold nothing."""
    if not table_exists(conn, table):
        return f"{table}.{column}: SKIP (no such table)"
    if column not in columns(conn, table):
        return f"{table}.{column}: already dropped"
    (populated,) = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL"
    ).fetchone()
    if populated:
        raise AbortedError(
            f"{table}.{column} holds {populated} non-NULL value(s); refusing to drop it. "
            "Move that data somewhere before re-running."
        )
    if not dry_run:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    return f"{table}.{column}: dropped (was NULL in every row)"


def rebuild_assignments(conn: sqlite3.Connection, *, dry_run: bool) -> str:
    """Recreate `interview_assignments` in its new shape — empty tables only.

    The column set changes, not just the names: `interviewer_type` is gone
    (the assignee is always a SkillBrew user, never an AI) and `candidate_id`
    is new (the persona being assigned). A row written against the old shape
    has no honest translation, so if there are any, we stop.
    """
    if not table_exists(conn, "interview_assignments"):
        return "interview_assignments: SKIP (no such table)"
    cols = set(columns(conn, "interview_assignments"))
    if {"user_id", "candidate_id", "status"} <= cols and "interviewer_type" not in cols:
        return "interview_assignments: already the new shape"
    (rows,) = conn.execute("SELECT COUNT(*) FROM interview_assignments").fetchone()
    if rows:
        raise AbortedError(
            f"interview_assignments holds {rows} row(s) and its shape changes "
            "(interviewer_type dropped, candidate_id added). This script will not "
            "discard them — migrate them by hand, then re-run."
        )
    if not dry_run:
        conn.execute("DROP TABLE interview_assignments")
        conn.execute(NEW_ASSIGNMENTS_DDL)
        for stmt in NEW_ASSIGNMENTS_INDEXES:
            conn.execute(stmt)
    return "interview_assignments: recreated empty with (user_id, candidate_id, status)"


def _steps(conn: sqlite3.Connection, *, dry_run: bool) -> list[str]:
    """Every step in order. With `dry_run` set this only reads and guards."""
    report = [rename_column(conn, t, old, new, dry_run=dry_run) for t, old, new in RENAMES]
    report += [drop_column(conn, t, c, dry_run=dry_run) for t, c in DROPS]
    report.append(rebuild_assignments(conn, dry_run=dry_run))
    return report


def migrate(db: Path, *, dry_run: bool) -> list[str]:
    """Plan the whole migration, then apply it in one transaction.

    Two things force this shape. Python's `sqlite3` does not open its implicit
    transaction for DDL, so `ALTER TABLE` commits the moment it runs — a guard
    that fires on the last step would otherwise leave a half-renamed database
    behind, which is exactly the state this script exists to avoid. And the
    guards are all pure reads, so running every one of them *before* the first
    write costs nothing and turns "abort" into "nothing happened".
    """
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        report = _steps(conn, dry_run=True)  # guards only; raises before any write
        if dry_run:
            return report
        conn.execute("BEGIN")
        try:
            report = _steps(conn, dry_run=False)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return report
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path(DEFAULT_DB), help=f"default {DEFAULT_DB}")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, write nothing"
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"no database at {args.db} — nothing to migrate", file=sys.stderr)
        return 1

    try:
        report = migrate(args.db, dry_run=args.dry_run)
    except AbortedError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2

    prefix = "would " if args.dry_run else ""
    print(f"{args.db}:")
    for line in report:
        print(f"  {prefix}{line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
