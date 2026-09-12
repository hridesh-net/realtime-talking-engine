"""Shared fixtures. Postgres today; the SQLite suites are untouched.

Every fixture here is **lazy**: nothing is provisioned, connected to or created
until a test actually asks for it. That matters because most of this suite is
offline and must stay that way — `pytest tests/test_voice.py` on a laptop with
no container runtime has to behave exactly as it did before this file existed.

Isolation between tests is `TRUNCATE ... CASCADE`, not a database per test.
A database per test is cleaner in theory and costs roughly a second each in
practice — `CREATE DATABASE` copies a template and every connection has to be
re-established — which would put the Python gate minutes behind where it is.
The whole gate is meant to stay under about thirty seconds, so the schema is
created once per session and the rows are thrown away between tests.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import psycopg
import psycopg.rows
import pytest
from psycopg_pool import ConnectionPool

from control_plane import database, migrate
from tests import infra as test_infra


@pytest.fixture(scope="session")
def _infra() -> Iterator[test_infra.Infra]:
    """Postgres for this session, provisioned only if nothing was supplied.

    `InfraUnavailableError` is deliberately allowed to propagate: an errored fixture
    fails the run, and a database-backed suite that cannot reach a database
    must never report itself as passed. `scripts/check.sh` catches the same
    condition earlier and prints NOT RUN.
    """
    infra = test_infra.up(s3=False)
    try:
        yield infra
    finally:
        test_infra.down(infra.handle)


@pytest.fixture(scope="session")
def pg_admin_dsn(_infra: test_infra.Infra) -> str:
    """A DSN with rights to CREATE DATABASE on the test server."""
    return _infra.database_url


@pytest.fixture(scope="session")
def database_url(pg_admin_dsn: str) -> Iterator[str]:
    """A freshly migrated database, dropped when the session ends.

    The schema is built by running `migrate.apply` rather than by loading a
    dump, so every test run exercises the migration path itself. A migration
    that only works on an empty database, or that no longer parses, fails here
    instead of in production.
    """
    name = f"iw_test_{secrets.token_hex(6)}"
    dsn = test_infra.create_database(pg_admin_dsn, name)
    try:
        migrate.apply(dsn)
        yield dsn
    finally:
        test_infra.drop_database(pg_admin_dsn, name)


@pytest.fixture(scope="session")
def pool(database_url: str) -> Iterator[ConnectionPool]:
    """The application's own pool, against the test database.

    Built through `database.open_pool` on purpose: the pool's settings —
    `autocommit=True` above all — are part of what the tests are checking, and
    a hand-rolled pool here would not be the thing production uses.
    """
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    connection_pool = database.open_pool(database_url)
    connection_pool.open(wait=True, timeout=30)
    try:
        yield connection_pool
    finally:
        connection_pool.close()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _truncate_all(conn: psycopg.Connection) -> None:
    """Empty every table except the migration ledger, in one statement.

    One `TRUNCATE` over the whole list, with CASCADE, so the foreign keys the
    Postgres schema actually enforces cannot dictate an ordering.
    """
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
        )
        tables = [row[0] for row in cur.fetchall()]
        if tables:
            names = ", ".join(f'"{t}"' for t in tables)
            cur.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")


@pytest.fixture
def db(pool: ConnectionPool) -> Iterator[ConnectionPool]:
    """The pool, emptied of rows before the test runs."""
    with pool.connection() as conn:
        _truncate_all(conn)
    yield pool


@pytest.fixture
def conn(db: ConnectionPool) -> Iterator[psycopg.Connection]:
    """One connection out of the clean pool, returned to it afterwards."""
    with db.connection() as connection:
        yield connection
