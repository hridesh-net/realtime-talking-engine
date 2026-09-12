"""Forward-only SQL migrations for the Postgres control plane.

Migration files live in ``control_plane/migrations/`` and are named
``NNNN_name.sql``. They are applied in ascending version order, each inside a
single transaction that first takes ``pg_advisory_xact_lock`` so two runners
starting at once serialise instead of interleaving. The sha256 of the file's
bytes is recorded on apply, and a later run that finds a different checksum
reports **drift** rather than doing anything about it.

**There are no down-migrations, and there will not be.** A down-migration is a
second, less-tested code path that runs only in the worst hour of the year, and
the ones that matter — a dropped column, a narrowed type — cannot restore the
data they discarded anyway. The recovery path for a bad migration is a
**restore from backup**, followed by a new forward migration that corrects it.
Write migrations that are safe to fail: they roll back whole, so a file that
raises halfway records nothing for itself and leaves earlier versions applied.

One consequence of the one-transaction rule: a statement Postgres refuses to
run inside a transaction block (``CREATE INDEX CONCURRENTLY``, ``CREATE
DATABASE``, ``ALTER TYPE ... ADD VALUE`` followed by a read of the new value)
cannot go in a migration file. That is also why the schema uses
``CHECK (x IN (...))`` instead of native enum types.

Usage::

    python -m control_plane.migrate                 # apply everything pending
    python -m control_plane.migrate --check         # 0 clean, 1 pending, 2 drift
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import psycopg.rows

from control_plane.database import database_url_from_env

#: Where the .sql files live, resolved relative to this module so the runner
#: works from any working directory.
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: A fixed, arbitrary key inside Postgres' signed 64-bit advisory-lock space.
#: Every runner against a given database takes this same lock, so "is the
#: constant stable" is the only property that matters — never change it.
ADVISORY_LOCK_KEY = 4_412_017_309_120_755_331

#: ``NNNN_name.sql``. Anything else in the directory is ignored, which keeps a
#: stray editor backup or README from being executed as schema.
_FILENAME = re.compile(r"^(\d{4})_([A-Za-z0-9_.-]+)\.sql$")

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """A migration set that cannot be reasoned about, or has not been applied."""


@dataclass(frozen=True)
class Migration:
    """One migration file on disk."""

    version: int
    name: str
    path: Path
    checksum: str

    @property
    def filename(self) -> str:
        """The file's name, which is what every message about it should say."""
        return self.path.name


@dataclass(frozen=True)
class Status:
    """What a database's ledger says relative to the files on disk.

    ``pending`` are files never applied. ``drift`` are prose descriptions of
    applied versions that no longer match their file — a changed checksum, or
    a file that has been deleted. Drift is never repaired automatically: both
    causes mean the database and the tree disagree about history, and only a
    human knows which one is right.
    """

    pending: list[Migration] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)

    @property
    def is_current(self) -> bool:
        """True when nothing is pending and nothing has drifted."""
        return not self.pending and not self.drift


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discover(migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    """Every ``NNNN_name.sql`` in the directory, in ascending version order."""
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise MigrationError(f"no migrations directory at {directory}")

    found: dict[int, Migration] = {}
    for path in sorted(directory.iterdir()):
        match = _FILENAME.match(path.name)
        if not match:
            continue
        version = int(match.group(1))
        if version in found:
            raise MigrationError(
                f"duplicate migration version {version:04d}: "
                f"{found[version].filename} and {path.name}"
            )
        found[version] = Migration(
            version=version,
            name=match.group(2),
            path=path,
            checksum=_checksum(path.read_bytes()),
        )
    return [found[v] for v in sorted(found)]


def ensure_ledger(conn: psycopg.Connection) -> None:
    """Create ``schema_migrations`` if it is not there yet.

    Called before the first read, so a brand-new database reports "everything
    pending" rather than raising ``UndefinedTable``.
    """
    with conn.cursor() as cur:
        cur.execute(_CREATE_LEDGER)


def _applied(conn: psycopg.Connection) -> dict[int, tuple[str, str]]:
    """Version -> (name, checksum) for every recorded migration.

    Reads through a local ``tuple_row`` cursor rather than the connection's own
    row factory: this runs against both a bare ``psycopg.connect`` and the
    application pool's ``dict_row`` connections, and the shape must not depend
    on which one the caller handed over.
    """
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        cur.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
        return {int(v): (str(n), str(c)) for v, n, c in cur.fetchall()}


def status(
    conn: psycopg.Connection,
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> Status:
    """Compare the ledger against the files on disk."""
    ensure_ledger(conn)
    applied = _applied(conn)
    files = {m.version: m for m in discover(migrations_dir)}

    drift: list[str] = []
    for version in sorted(applied):
        name, checksum = applied[version]
        migration = files.get(version)
        if migration is None:
            drift.append(f"{version:04d}_{name}.sql is recorded as applied but no such file exists")
        elif migration.checksum != checksum:
            drift.append(
                f"{migration.filename} changed after it was applied "
                f"(recorded {checksum[:12]}, on disk {migration.checksum[:12]})"
            )

    pending = [files[v] for v in sorted(files) if v not in applied]
    return Status(pending=pending, drift=drift)


def assert_current(
    conn: psycopg.Connection,
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> None:
    """Raise unless every migration on disk has been applied and none drifted.

    The service calls this at startup: booting behind an unapplied migration
    means every request fails on a column that is not there, which is far
    harder to diagnose than refusing to start.
    """
    state = status(conn, migrations_dir)
    problems: list[str] = list(state.drift)
    if state.pending:
        problems.append("pending: " + ", ".join(m.filename for m in state.pending))
    if problems:
        raise MigrationError(
            "the database schema is not current — run "
            "`python -m control_plane.migrate`. " + "; ".join(problems)
        )


def apply(
    dsn: str | None = None,
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> list[int]:
    """Apply every pending migration in order; return the versions applied.

    Each file gets its own connection-level transaction which takes
    ``pg_advisory_xact_lock`` first, so a second runner blocks at the lock and
    then finds the version already recorded rather than executing it twice.
    A file that raises rolls its own transaction back — including the ledger
    insert — and the exception propagates with earlier versions still applied.
    """
    target = dsn or database_url()
    applied_now: list[int] = []
    with psycopg.connect(target, autocommit=True) as conn:
        ensure_ledger(conn)
        already = set(_applied(conn))
        for migration in discover(migrations_dir):
            if migration.version in already:
                continue
            sql = migration.path.read_text()
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                # Re-read under the lock: another runner may have applied this
                # version while we were queued behind it.
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (migration.version,)
                )
                if cur.fetchone() is not None:
                    continue
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
                applied_now.append(migration.version)
    return applied_now


def database_url() -> str:
    """The DSN to migrate, from ``DATABASE_URL``.

    Delegates to ``control_plane.database`` rather than repeating the default:
    the runner and the application must never disagree about which database
    they mean, and a second copy of the string is how they would start to.
    """
    return database_url_from_env()


def _report(state: Status) -> None:
    for line in state.drift:
        print(f"drift:   {line}", file=sys.stderr)
    for migration in state.pending:
        print(f"pending: {migration.filename}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m control_plane.migrate",
        description="Apply forward-only SQL migrations to the control-plane database.",
    )
    parser.add_argument("--dsn", default=None, help="connection string (default: $DATABASE_URL)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report only: exit 0 current, 1 pending, 2 drift",
    )
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="directory of NNNN_name.sql files",
    )
    args = parser.parse_args(argv)
    dsn = args.dsn or database_url()

    if args.check:
        with psycopg.connect(dsn, autocommit=True) as conn:
            state = status(conn, args.migrations_dir)
        _report(state)
        if state.drift:
            return 2
        if state.pending:
            return 1
        print("schema is current")
        return 0

    applied_now = apply(dsn, args.migrations_dir)
    if applied_now:
        print("applied: " + ", ".join(f"{v:04d}" for v in applied_now))
    else:
        print("nothing to apply")
    with psycopg.connect(dsn, autocommit=True) as conn:
        state = status(conn, args.migrations_dir)
    if state.drift:
        _report(state)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI tests
    raise SystemExit(main())
