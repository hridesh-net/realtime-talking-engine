#!/usr/bin/env python3
"""Bring an existing SQLite control-plane database up to the expectations schema.

There is no migration runner for SQLite in this repo: `control_plane/database.py`
applies its `_SCHEMA` with `CREATE TABLE IF NOT EXISTS`, so a **new table** in
the DDL appears on an existing database but a **new column** never does, and a
table dropped from the DDL stays forever. This script is the one-off that closes
that gap for the 2026-09-13 expectations/participants/links change, in the style
of `scripts/rename_columns_sqlite.py`.

    scripts/upgrade_sqlite_expectations.py --db control_plane.db --dry-run
    scripts/upgrade_sqlite_expectations.py --db control_plane.db

What it does:

* adds `interviews.expectations TEXT NOT NULL DEFAULT '[]'`
* adds `sessions.participant_id TEXT` (nullable: the rows that predate this
  change genuinely have no participant, and inventing one would be a lie about
  who sat the interview)
* creates `participants` and `interview_links` if they are missing
* drops `interview_expectations` (the retired expectation agent's document) and
  `interview_assignments` (designed, never written) -- **only when empty**, for
  the same reason `rename_columns_sqlite.py` refuses to discard rows

It is idempotent: every step reads the live schema first and skips work that has
already happened, because the only way to know whether a given `.db` has been
through it is to look.

Existing interviews get `'[]'`, not the rubric's fixed items. The repository
fills a missing list in with `fixed_items()` on read, so an interview created
before this change still reports the full checklist -- and writing the items
into every historical row here would bake today's rubric wording into rows
nobody asked to change.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "control_plane.db"

#: (table, column, column definition) for each plain `ALTER TABLE ADD COLUMN`.
ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("interviews", "expectations", "TEXT NOT NULL DEFAULT '[]'"),
    ("sessions", "participant_id", "TEXT REFERENCES participants(id)"),
)

#: Tables created here if absent, in dependency order.
NEW_TABLES: tuple[tuple[str, str], ...] = (
    (
        "participants",
        """
        CREATE TABLE participants (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            user_id TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """,
    ),
    (
        "interview_links",
        """
        CREATE TABLE interview_links (
            token TEXT PRIMARY KEY,
            interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        )
        """,
    ),
)

NEW_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_links_interview ON interview_links(interview_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_participant ON sessions(participant_id)",
)

#: Tables the schema no longer has. Dropped only once proven empty.
DROPS: tuple[str, ...] = ("interview_expectations", "interview_assignments")


class AbortedError(Exception):
    """A guard failed. Nothing was written."""


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def add_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str, *, dry_run: bool
) -> str:
    """One `ALTER TABLE ... ADD COLUMN`, or a reason it was not needed."""
    if not table_exists(conn, table):
        return f"{table}.{column}: SKIP (no such table)"
    if column in columns(conn, table):
        return f"{table}.{column}: already present"
    if not dry_run:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return f"{table}.{column}: added"


def create_table(conn: sqlite3.Connection, table: str, ddl: str, *, dry_run: bool) -> str:
    """Create a table that the DDL gained, if this database does not have it."""
    if table_exists(conn, table):
        return f"{table}: already present"
    if not dry_run:
        conn.execute(ddl)
    return f"{table}: created"


def drop_table(conn: sqlite3.Connection, table: str, *, dry_run: bool) -> str:
    """Drop a retired table, but only once it is proven to hold nothing."""
    if not table_exists(conn, table):
        return f"{table}: already dropped"
    (rows,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    if rows:
        raise AbortedError(
            f"{table} holds {rows} row(s); refusing to drop it. Export or delete "
            "them deliberately, then re-run."
        )
    if not dry_run:
        conn.execute(f"DROP TABLE {table}")
    return f"{table}: dropped (was empty)"


def _steps(conn: sqlite3.Connection, *, dry_run: bool) -> list[str]:
    """Every step in order. With `dry_run` set this only reads and guards."""
    report = [create_table(conn, t, ddl, dry_run=dry_run) for t, ddl in NEW_TABLES]
    report += [add_column(conn, t, c, d, dry_run=dry_run) for t, c, d in ADDITIONS]
    if not dry_run:
        for stmt in NEW_INDEXES:
            conn.execute(stmt)
    report += [drop_table(conn, t, dry_run=dry_run) for t in DROPS]
    return report


def migrate(db: Path, *, dry_run: bool) -> list[str]:
    """Plan the whole upgrade, then apply it in one transaction.

    Same shape and same reason as `rename_columns_sqlite.py`: Python's `sqlite3`
    does not open its implicit transaction for DDL, so every guard runs as a
    pure read *before* the first write and "abort" means "nothing happened".
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
        print(f"no database at {args.db} — nothing to upgrade", file=sys.stderr)
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
