"""Throwaway Postgres and MinIO for the test suite, on Apple `container`.

One helper, two callers: `tests/conftest.py` provisions lazily from inside
pytest, and `scripts/check.sh` brings the same stack up once for a whole gate
run so the many per-file pytest sessions share it.

**The container runtime is Apple `container`, not Docker.** Docker is not
installed and is not used in this project. `docker.io/...` in the image names
below is a *registry* hostname, which Apple `container` pulls from like any
other client; it says nothing about the runtime.

Precedence, and why it is this way round:

* If `TEST_DATABASE_URL` (and, for the object store, `TEST_S3_ENDPOINT` with
  its two keys) are set, **nothing is provisioned** — the suite uses what you
  point it at. A developer with a local Postgres already running, and CI with
  a service container, both take this path, and neither needs a runtime.
* Otherwise the runtime must be up: `container system status` has to succeed.
  It is not started automatically. Starting it is a machine-level action with
  a one-time kernel download behind it, and a test helper is the wrong thing
  to be doing that silently — so an unavailable runtime raises
  `InfraUnavailableError`, which the caller turns into a **NOT RUN** gate.

Everything here is disposable. Containers are started with `--rm` and named
`iw-pg-<hex>` / `iw-minio-<hex>`; `down(handle)` stops both, which removes
them. A handle is just that hex, so the process that tears the stack down does
not have to be the one that brought it up.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import conninfo as _conninfo

from control_plane import migrate

CONTAINER_BIN = os.getenv("CONTAINER_BIN", "/usr/local/bin/container")

POSTGRES_IMAGE = "docker.io/library/postgres:16-alpine"
MINIO_IMAGE = "docker.io/minio/minio:latest"

POSTGRES_USER = "test"
POSTGRES_PASSWORD = "test"
MINIO_USER = "test"
MINIO_PASSWORD = "testtest1"  # MinIO refuses a secret shorter than 8 characters.

#: First run pulls an image over the network, so the readiness caps are
#: generous on purpose. A tight timeout here fails the gate for a slow link,
#: which reads as a broken test rather than a cold cache.
PULL_TIMEOUT_S = 600
READY_TIMEOUT_S = 180

#: `-p` accepts `[host-ip:]host-port:container-port` on Docker; this build of
#: Apple `container` is not known to, so the forms are tried in order and the


class InfraUnavailableError(RuntimeError):
    """No test infrastructure, and none can be provisioned on this machine."""


@dataclass
class Infra:
    """A provisioned (or borrowed) test stack.

    `env` is what the suite needs in its environment; `containers` is what
    `down()` has to stop. Both are empty for a stack that was pointed at
    rather than started.
    """

    handle: str
    env: dict[str, str] = field(default_factory=dict)
    containers: list[str] = field(default_factory=list)

    @property
    def database_url(self) -> str:
        return self.env["TEST_DATABASE_URL"]

    def export_lines(self) -> list[str]:
        lines = [f"export {k}={v}" for k, v in sorted(self.env.items())]
        lines.append(f"export TEST_INFRA_HANDLE={self.handle}")
        return lines


# --------------------------------------------------------------- runtime ----


def runtime_available() -> bool:
    """True when the Apple `container` apiserver answers."""
    if not Path(CONTAINER_BIN).exists():
        return False
    try:
        done = subprocess.run(
            [CONTAINER_BIN, "system", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "not running" not in done.stdout


def _container(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CONTAINER_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _container_ipv4(name: str) -> str:
    """The container's own address on the runtime's bridge network.

    Apple `container` 1.2.0 does not usefully publish ports to the host. A
    `-p 127.0.0.1:<host>:<guest>` binding is accepted, and a TCP handshake
    against it even succeeds, but the forwarded connection is dropped as soon
    as a real protocol exchange begins -- Postgres reports "server closed the
    connection unexpectedly" while the very same server answers fine on the
    address below. Measured, not assumed: `nc` says the host port is open and
    psycopg cannot talk to it, on a container whose own log says "database
    system is ready to accept connections".

    So we do not publish ports at all; we talk to the container directly. That
    also removes the free-port race that publishing needs.
    """
    done = _container("inspect", name, timeout=60)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise InfraUnavailableError(f"could not inspect {name}: {detail}")
    try:
        payload = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise InfraUnavailableError(f"could not parse `container inspect {name}` output") from exc
    entries = payload if isinstance(payload, list) else [payload]
    for entry in entries:
        for network in entry.get("status", {}).get("networks", []):
            address = network.get("ipv4Address", "")
            if address:
                return str(address).split("/", 1)[0]
    raise InfraUnavailableError(f"{name} started but reported no IPv4 address")


def _run_detached(
    name: str,
    image: str,
    container_port: int,
    env: dict[str, str],
    command: list[str],
) -> str:
    """Start a detached container, returning the host:port it is reachable on.

    The address is the container's own, not a published host port -- see
    `_container_ipv4` for the measurement behind that.
    """
    args = ["run", "-d", "--rm", "--name", name]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    done = _container(*args, image, *command, timeout=PULL_TIMEOUT_S)
    if done.returncode != 0:
        message = (done.stderr or done.stdout).strip()
        _container("stop", name, timeout=60)
        raise InfraUnavailableError(f"could not start {name} from {image}: {message[-400:]}")
    try:
        return f"{_container_ipv4(name)}:{container_port}"
    except InfraUnavailableError:
        _container("stop", name, timeout=60)
        raise


# -------------------------------------------------------------- postgres ----


def _wait_for_postgres(dsn: str, timeout: int = READY_TIMEOUT_S) -> None:
    """Poll until a real connection succeeds.

    Readiness is "psycopg connected", not "the process started": Postgres'
    entrypoint brings the server up, shuts it down to run initdb scripts, and
    brings it back — so a port that accepts a TCP connection is not yet a
    database that accepts a query.
    """
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.Error as exc:  # not up yet
            last = exc
            time.sleep(0.5)
    raise InfraUnavailableError(f"postgres never became ready at {dsn}: {last}")


def start_postgres(token: str) -> tuple[str, str]:
    """Start a throwaway Postgres. Returns (container name, admin DSN)."""
    name = f"iw-pg-{token}"
    address = _run_detached(
        name,
        POSTGRES_IMAGE,
        5432,
        {"POSTGRES_USER": POSTGRES_USER, "POSTGRES_PASSWORD": POSTGRES_PASSWORD},
        [],
    )
    dsn = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{address}/{POSTGRES_USER}"
    try:
        _wait_for_postgres(dsn)
    except InfraUnavailableError:
        _container("stop", name, timeout=60)
        raise
    return name, dsn


# ----------------------------------------------------------------- minio ----


def _wait_for_minio(endpoint: str, timeout: int = READY_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            url = f"{endpoint}/minio/health/live"
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
        time.sleep(0.5)
    raise InfraUnavailableError(f"minio never became ready at {endpoint}: {last}")


def start_minio(token: str) -> tuple[str, str]:
    """Start a throwaway MinIO. Returns (container name, endpoint URL)."""
    name = f"iw-minio-{token}"
    address = _run_detached(
        name,
        MINIO_IMAGE,
        9000,
        {"MINIO_ROOT_USER": MINIO_USER, "MINIO_ROOT_PASSWORD": MINIO_PASSWORD},
        ["server", "/data"],
    )
    endpoint = f"http://{address}"
    try:
        _wait_for_minio(endpoint)
    except InfraUnavailableError:
        _container("stop", name, timeout=60)
        raise
    return name, endpoint


# ------------------------------------------------------------ up and down ----


def _from_env() -> dict[str, str]:
    """Whatever the environment already points at, filtered to what is set."""
    keys = (
        "TEST_DATABASE_URL",
        "TEST_S3_ENDPOINT",
        "TEST_S3_ACCESS_KEY",
        "TEST_S3_SECRET_KEY",
    )
    return {k: v for k in keys if (v := os.getenv(k, "").strip())}


def up(*, postgres: bool = True, s3: bool = True) -> Infra:
    """Provide the requested services, provisioning only what is not supplied.

    Raises `InfraUnavailableError` when something has to be provisioned and the
    container runtime is not up. Callers turn that into NOT RUN — never into a
    silent pass.
    """
    supplied = _from_env()
    want_pg = postgres and "TEST_DATABASE_URL" not in supplied
    want_s3 = s3 and not {"TEST_S3_ENDPOINT", "TEST_S3_ACCESS_KEY", "TEST_S3_SECRET_KEY"} <= set(
        supplied
    )

    if not (want_pg or want_s3):
        return Infra(handle="external", env=supplied)

    if not runtime_available():
        raise InfraUnavailableError(
            "Apple `container` is not running (tried "
            f"`{CONTAINER_BIN} system status`). Run `container system start` once, "
            "or set TEST_DATABASE_URL / TEST_S3_* to servers you already run."
        )

    token = secrets.token_hex(4)
    infra = Infra(handle=token, env=dict(supplied))
    try:
        if want_pg:
            name, dsn = start_postgres(token)
            infra.containers.append(name)
            infra.env["TEST_DATABASE_URL"] = dsn
        if want_s3:
            name, endpoint = start_minio(token)
            infra.containers.append(name)
            infra.env["TEST_S3_ENDPOINT"] = endpoint
            infra.env["TEST_S3_ACCESS_KEY"] = MINIO_USER
            infra.env["TEST_S3_SECRET_KEY"] = MINIO_PASSWORD
    except BaseException:
        down(infra.handle)
        raise
    return infra


def down(handle: str | None) -> None:
    """Stop everything a handle names. Safe to call twice, or on nothing."""
    if not handle or handle == "external":
        return
    for name in (f"iw-pg-{handle}", f"iw-minio-{handle}"):
        _container("stop", name, timeout=60)


# ------------------------------------------------- a scratch database ----


def _with_dbname(dsn: str, dbname: str) -> str:
    return _conninfo.make_conninfo(dsn, dbname=dbname)


def create_database(admin_dsn: str, name: str) -> str:
    """CREATE DATABASE `name` on the server `admin_dsn` points at.

    Returns the DSN of the new database. `CREATE DATABASE` cannot run inside a
    transaction block, hence the autocommit connection.
    """
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return _with_dbname(admin_dsn, name)


def drop_database(admin_dsn: str, name: str) -> None:
    """DROP DATABASE `name`, disconnecting anything still attached to it."""
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextlib.contextmanager
def temporary_database(admin_dsn: str | None = None) -> Iterator[str]:
    """A migrated scratch database that is dropped on exit.

    For the live scenario scripts, which want a real schema for one run and
    nothing left behind afterwards. `admin_dsn` defaults to
    `TEST_DATABASE_URL`; without one, infrastructure is provisioned for the
    duration of the block.
    """
    infra: Infra | None = None
    if admin_dsn is None:
        admin_dsn = os.getenv("TEST_DATABASE_URL", "").strip() or None
    if admin_dsn is None:
        infra = up(s3=False)
        admin_dsn = infra.database_url

    name = f"iw_tmp_{secrets.token_hex(6)}"
    dsn = create_database(admin_dsn, name)
    try:
        migrate.apply(dsn)
        yield dsn
    finally:
        with contextlib.suppress(psycopg.Error):
            drop_database(admin_dsn, name)
        if infra is not None:
            down(infra.handle)


# ------------------------------------------------------------------- cli ----


USAGE = (
    "usage: python -m tests.infra up [postgres|s3|all]\n       python -m tests.infra down <handle>"
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "up":
        # Which services to bring up. Callers name what they need rather than
        # taking everything, so a gate is never held up by infrastructure none
        # of its suites touch.
        wanted = args[1] if len(args) > 1 else "all"
        if wanted not in {"postgres", "s3", "all"}:
            print(USAGE, file=sys.stderr)
            return 2
        try:
            infra = up(postgres=wanted in {"postgres", "all"}, s3=wanted in {"s3", "all"})
        except InfraUnavailableError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("\n".join(infra.export_lines()))
        return 0
    if len(args) == 2 and args[0] == "down":
        down(args[1])
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
