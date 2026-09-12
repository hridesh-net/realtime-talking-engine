"""One contract, two adapters — the object store's behaviour, held to both.

Almost every test here is parametrized over `FilesystemObjectStore` and
`S3ObjectStore`, because the reason the port exists is that the deployed
service and a laptop with no bucket must behave the same. A range that returns
three bytes from a local file has to return the same three from S3, and a range
that runs off the end has to do the same thing in both places. A test that ran
against only one of them would let the two drift and would still be green.

**The S3 parametrization runs against a real S3-compatible server** (MinIO —
`tests/infra.py` provisions one, or honours `TEST_S3_*` pointing at one you
already run). It is deliberately **not** skipped when that server is missing:
the fixture raises, every S3 case ERRORs, and the suite goes red. A storage
adapter tested against a fake proves that the fake matches the fake; see the
comment above `missing()` in `scripts/check.sh` for what this repo has already
paid for a check that quietly stopped checking.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from botocore.client import Config

from control_plane.object_store import FilesystemObjectStore, S3ObjectStore
from tests import infra as test_infra

#: MinIO does not care about the region, and AWS would; naming one keeps the
#: two paths identical rather than relying on a default that differs.
REGION = "us-east-1"

#: A non-empty S3_PREFIX in every S3 test, so "the prefix is applied" is not a
#: property that only one test happens to exercise.
PREFIX = "iw"

#: Comfortably past boto3's own 8 MiB multipart threshold, so `upload_file`
#: takes the multipart path for real rather than by assumption. The ETag check
#: in `test_a_large_upload_really_went_multipart` is the proof.
LARGE_SIZE = 9 * 1024 * 1024


# ------------------------------------------------------------- fixtures ----


@pytest.fixture(scope="session")
def s3_infra() -> Iterator[test_infra.Infra]:
    """A live S3-compatible server: MinIO, provisioned or pointed at.

    `InfraUnavailableError` is allowed to propagate on purpose — an errored
    fixture fails the run, which is the honest outcome for an adapter whose
    server is not there.
    """
    infra = test_infra.up(postgres=False)
    try:
        yield infra
    finally:
        test_infra.down(infra.handle)


@pytest.fixture(scope="session")
def s3_endpoint(s3_infra: test_infra.Infra) -> str:
    return s3_infra.env["TEST_S3_ENDPOINT"]


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """`monkeypatch`, but living as long as the session-scoped bucket does."""
    patch = pytest.MonkeyPatch()
    try:
        yield patch
    finally:
        patch.undo()


@pytest.fixture(scope="session")
def s3_credentials(s3_infra, monkeypatch_session):
    """The keys where boto3's default chain finds them, as a deployment has them.

    The adapter must never read a credential itself — that is an architecture
    rule, not a preference — so the test supplies them the only way the adapter
    is allowed to receive them.
    """
    monkeypatch_session.setenv("AWS_ACCESS_KEY_ID", s3_infra.env["TEST_S3_ACCESS_KEY"])
    monkeypatch_session.setenv("AWS_SECRET_ACCESS_KEY", s3_infra.env["TEST_S3_SECRET_KEY"])
    monkeypatch_session.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch_session.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture(scope="session")
def s3_client(s3_endpoint, s3_credentials):
    """A boto3 client for looking at the bucket from outside the adapter.

    The tests use this to assert on what actually landed — the real key, the
    ETag — rather than asking the adapter to confirm its own work.
    """
    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        region_name=REGION,
        config=Config(s3={"addressing_style": "path"}),
    )


@pytest.fixture(scope="session")
def s3_bucket(s3_client) -> str:
    """One bucket for this run. Keys are unique per test, so it can be shared."""
    name = f"iw-object-store-{secrets.token_hex(6)}"
    s3_client.create_bucket(Bucket=name)
    return name


@pytest.fixture
def filesystem_store(tmp_path: Path) -> FilesystemObjectStore:
    return FilesystemObjectStore(tmp_path / "objects")


@pytest.fixture
def s3_store(s3_endpoint, s3_bucket) -> S3ObjectStore:
    return S3ObjectStore(
        s3_bucket,
        region=REGION,
        prefix=PREFIX,
        endpoint=s3_endpoint,
        force_path_style=True,
    )


@pytest.fixture(params=["filesystem", "s3"])
def store(request):
    """Both adapters, one test body.

    `getfixturevalue` rather than two fixtures in the signature, so a
    filesystem case never asks for the S3 server and a run with no MinIO still
    reports the filesystem half honestly.
    """
    return request.getfixturevalue(f"{request.param}_store")


@pytest.fixture
def key() -> str:
    """A logical key in the layout the Go engine's bundle shares."""
    return f"sessions/{secrets.token_hex(6)}/recording.webm"


def _file(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / f"upload-{secrets.token_hex(4)}.bin"
    path.write_bytes(payload)
    return path


def _read(store, key, *args):
    source = store.open(key)
    assert source is not None, f"{key} should exist"
    return b"".join(source.read(*args))


# ------------------------------------------------------- the round trip ----


def test_put_then_open_round_trips_the_bytes(store, tmp_path, key):
    payload = b"the manager on the left, the persona on the right"
    store.put(key, _file(tmp_path, payload), content_type="audio/webm")

    source = store.open(key)
    assert source is not None
    assert source.size == len(payload)
    assert b"".join(source.read()) == payload


def test_content_type_round_trips(store, tmp_path, key):
    """What went in comes back out — a filesystem has to record it too."""
    store.put(key, _file(tmp_path, b"x"), content_type="audio/webm;codecs=opus")

    source = store.open(key)
    assert source is not None
    assert source.content_type == "audio/webm;codecs=opus"


def test_put_overwrites_an_existing_object(store, tmp_path, key):
    store.put(key, _file(tmp_path, b"first take"), content_type="audio/webm")
    store.put(key, _file(tmp_path, b"second"), content_type="audio/ogg")

    source = store.open(key)
    assert source is not None
    assert b"".join(source.read()) == b"second"
    assert source.size == len(b"second")
    assert source.content_type == "audio/ogg"


def test_open_returns_none_for_a_missing_key(store):
    assert store.open("sessions/never-recorded/recording.webm") is None


def test_open_returns_none_rather_than_raising_for_a_missing_prefix_too(store):
    """A whole missing prefix is still just "no object", not an error."""
    assert store.open("sessions/no-such/nested/deeper.webm") is None


# ------------------------------------------------------------- the ranges ----

RANGE_PAYLOAD = b"0123456789abcdef"


@pytest.fixture
def ranged(store, tmp_path, key):
    """An object of known content, for the range cases below."""
    store.put(key, _file(tmp_path, RANGE_PAYLOAD), content_type="application/octet-stream")
    return store, key


def test_range_with_a_start_only_runs_to_the_end(ranged):
    store, key = ranged
    assert _read(store, key, 10) == RANGE_PAYLOAD[10:]


def test_range_with_a_start_and_end_includes_the_end_byte(ranged):
    store, key = ranged
    assert _read(store, key, 4, 8) == RANGE_PAYLOAD[4:9]


def test_a_single_byte_range_is_start_equal_to_end(ranged):
    store, key = ranged
    assert _read(store, key, 7, 7) == RANGE_PAYLOAD[7:8]


def test_an_end_past_the_last_byte_is_clamped(ranged):
    """Asking for more than there is returns what there is, in both adapters.

    S3 clamps this server-side and a file read would too; the point of the test
    is that neither of them turns it into an error, so a caller reading "a
    megabyte from here" at the tail of a recording needs no special case.
    """
    store, key = ranged
    assert _read(store, key, 12, 9_999) == RANGE_PAYLOAD[12:]


def test_a_start_beyond_the_end_reads_nothing(ranged):
    """Empty, not an exception — and S3 is never asked, which would 416."""
    store, key = ranged
    assert _read(store, key, len(RANGE_PAYLOAD)) == b""
    assert _read(store, key, len(RANGE_PAYLOAD) + 500, 9_999) == b""


def test_a_negative_bound_is_refused_by_both_adapters(ranged):
    """No suffix ranges. -1 is a caller's bug, not "the last byte"."""
    store, key = ranged
    source = store.open(key)
    assert source is not None
    with pytest.raises(ValueError, match="negative"):
        source.read(-1)
    with pytest.raises(ValueError, match="negative"):
        source.read(0, -5)


def test_an_empty_object_reads_as_empty_at_any_range(store, tmp_path, key):
    store.put(key, _file(tmp_path, b""), content_type="application/octet-stream")

    source = store.open(key)
    assert source is not None
    assert source.size == 0
    assert b"".join(source.read()) == b""
    assert b"".join(source.read(0, 10)) == b""


# -------------------------------------------------------------- big object ----


def test_an_object_larger_than_the_multipart_threshold_round_trips(store, tmp_path, key):
    """9 MiB, so `upload_file` splits it — and the ranges still line up.

    The middle range deliberately straddles the 8 MiB boundary boto3 splits on:
    a multipart upload that reassembled its parts in the wrong order, or lost
    one, reads back fine at the head and wrong right here.
    """
    payload = secrets.token_bytes(LARGE_SIZE)
    store.put(key, _file(tmp_path, payload), content_type="audio/webm")

    source = store.open(key)
    assert source is not None
    assert source.size == LARGE_SIZE
    assert b"".join(source.read()) == payload

    boundary = 8 * 1024 * 1024
    assert _read(store, key, boundary - 32, boundary + 31) == payload[boundary - 32 : boundary + 32]
    assert _read(store, key, LARGE_SIZE - 5) == payload[-5:]


# ------------------------------------------------------------ the bad keys ----


@pytest.mark.parametrize(
    "bad",
    ["", "/sessions/a.webm", "sessions/../../etc/passwd", "sessions//a.webm", "a.content-type"],
)
def test_a_key_that_would_mean_two_things_is_refused(store, tmp_path, bad):
    """Both adapters refuse the same keys, so a key is legal for the port or not.

    `..` matters most: on the filesystem adapter it resolves against the host
    and writes outside the root, while S3 would store it as a literal name.
    """
    with pytest.raises(ValueError):
        store.put(bad, _file(tmp_path, b"x"), content_type="application/octet-stream")
    with pytest.raises(ValueError):
        store.open(bad)


# ------------------------------------------------------------- s3 specifics ----


def test_the_prefix_lands_in_the_real_object_key(s3_store, s3_client, s3_bucket, tmp_path, key):
    """`S3_PREFIX` is applied by the adapter, and the caller never sees it.

    Checked against the bucket rather than against the adapter, because the
    thing that matters is where the Go engine's Finalizer will find the object:
    the same `sessions/{id}/` folder under the same prefix (plan §9).
    """
    s3_store.put(key, _file(tmp_path, b"prefixed"), content_type="audio/webm")

    head = s3_client.head_object(Bucket=s3_bucket, Key=f"{PREFIX}/{key}")
    assert head["ContentLength"] == len(b"prefixed")
    assert head["ContentType"] == "audio/webm"

    listing = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=f"{PREFIX}/{key}")
    assert [obj["Key"] for obj in listing.get("Contents", [])] == [f"{PREFIX}/{key}"]


def test_a_large_upload_really_went_multipart(s3_store, s3_client, s3_bucket, tmp_path, key):
    """The proof that `put` streamed in parts: S3 ETags a multipart as `<hex>-N`.

    A single-part upload's ETag is the MD5 of the whole object and carries no
    dash. Without this the "boto3 handles multipart" claim in `object_store.py`
    is an assumption about a default that could change under us.
    """
    s3_store.put(key, _file(tmp_path, secrets.token_bytes(LARGE_SIZE)), content_type="audio/webm")

    etag = s3_client.head_object(Bucket=s3_bucket, Key=f"{PREFIX}/{key}")["ETag"].strip('"')
    assert "-" in etag, f"ETag {etag!r} has no part count — the upload was not multipart"
    assert int(etag.rsplit("-", 1)[1]) > 1


def test_a_missing_bucket_is_an_error_not_a_missing_object(s3_endpoint, key):
    """A wrong bucket must not read as "the recording does not exist".

    This one is here because the obvious implementation gets it wrong: a HEAD
    reply has no body, so botocore reports a bare `404` for a missing bucket
    exactly as it does for a missing key, and `except 404: return None` reports
    an undeployed bucket as an empty one for every session at once.
    """
    store = S3ObjectStore(
        f"iw-no-such-bucket-{secrets.token_hex(4)}",
        region=REGION,
        prefix=PREFIX,
        endpoint=s3_endpoint,
        force_path_style=True,
    )
    with pytest.raises(RuntimeError, match="does not exist or is not reachable"):
        store.open(key)
