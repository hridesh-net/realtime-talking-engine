"""Where a session's bytes come to rest — one port, two adapters.

The control plane stores exactly one kind of large artifact today, the browser's
session recording, and it stores it as a *file*: `put` takes a filesystem path
and `open` returns a stream. Nothing here ever holds a whole recording in
memory, because an hour of stereo Opus is not a `bytes` the API process should
be asked to carry, and the moment one method takes or returns `bytes` every
caller downstream inherits that.

Two adapters, both production code:

* `FilesystemObjectStore` is the no-S3 default — a developer with no bucket
  runs the service and the bytes land under `OBJECT_STORE_DIR`. It is **not** a
  test fake; it is what runs when `S3_BUCKET` is unset.
* `S3ObjectStore` is the deployed path, and works against MinIO or any other
  S3-compatible server through `S3_ENDPOINT` + `S3_FORCE_PATH_STYLE`.

**The two must behave identically**, which is the only reason a port is worth
having: a range that reads three bytes from a local file has to read the same
three bytes from S3, and a range that runs off the end of the object has to do
the same thing in both places rather than "empty here, exception there". The
range rules are written down under `_resolve_range` and both adapters go
through it.

## Key layout — shared with the Go engine

Callers pass a *logical* key, `sessions/{session_id}/recording.webm`. The S3
adapter prepends `S3_PREFIX`; the filesystem adapter treats it as a path under
its root. This is deliberate and not merely tidy: the Go engine's Finalizer
writes `audio.wav`, `transcript.jsonl` and `events.jsonl` under
`s3://{bucket}/{prefix}/sessions/{session_id}/` (see
`docs/ENGINE_IMPLEMENTATION_PLAN.md` §9), so a session's artifacts sit together
in one place whichever process produced them — the control plane's browser
recording next to the engine's bundle, discoverable by session id alone rather
than by knowing who wrote what.

## Deliberately not here

* **No `delete`.** Retention is manual by decision (see
  [Session recording](okf/concepts/contracts/session-recording.md)); nothing in
  this service prunes on a schedule or on session deletion. A `delete` with no
  caller is dead code, and dead code in a storage adapter is the kind that gets
  wired up later by someone who has not read the retention decision.
* **No credential handling.** `S3ObjectStore` never reads a key: boto3's
  default chain (env, shared config, instance role) is the one place that
  belongs, exactly as agents take an injected model rather than an API key.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

#: How much of an object is handed to the caller per iteration. One MiB is
#: large enough that a long recording is a few hundred yields rather than a few
#: hundred thousand, and small enough to stay off the large-object heap.
CHUNK_SIZE = 1024 * 1024

#: `OBJECT_STORE_DIR` when it is unset, relative to the working directory —
#: the same convention as the database's own default path.
DEFAULT_OBJECT_STORE_DIR = "objects"

#: What `open` reports when the stored object has no recorded type. Only
#: reachable for a filesystem object whose sidecar was removed by hand.
DEFAULT_CONTENT_TYPE = "application/octet-stream"

#: The filesystem adapter records an object's content type in a sibling file
#: with this suffix. Keys ending in it are rejected by **both** adapters, so a
#: key that is legal against S3 cannot be one the filesystem store would read
#: back as its own metadata.
SIDECAR_SUFFIX = ".content-type"


# ------------------------------------------------------------------ ports ----


class ByteSource(Protocol):
    """An object opened for reading: how big it is, and how to stream it."""

    size: int
    content_type: str

    def read(self, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """Stream `[start, end]` — **inclusive** at both ends, like HTTP Range.

        `end=None` means "to the last byte". See `_resolve_range` for what a
        range that runs past the end of the object does.
        """
        ...


@runtime_checkable
class ObjectStore(Protocol):
    """Bytes at rest, addressed by a logical key."""

    def put(self, key: str, source: Path, *, content_type: str) -> None:
        """Store the file at `source` under `key`, overwriting what was there."""
        ...

    def open(self, key: str) -> ByteSource | None:
        """Open `key` for streaming, or `None` when no such object exists."""
        ...


# ------------------------------------------------------------ shared rules ----


def _validate_key(key: str) -> str:
    """Reject a key that either adapter would have to interpret differently.

    A logical key is a `/`-joined list of non-empty segments. Absolute keys,
    empty segments and `.`/`..` are refused because the filesystem adapter
    would resolve them against the host filesystem — `..` in a key that reached
    `root / key` writes outside the root, which is a path-traversal bug and not
    a hypothetical one for keys built from client-supplied ids.

    S3 would happily accept all of them as literal object names, so the check
    lives here rather than in one adapter: a key is either legal for the port
    or it is not, and finding out only after switching backends is the failure
    mode a port exists to prevent.
    """
    if not key or key.startswith("/") or key.endswith("/"):
        raise ValueError(f"object key must be a non-empty relative path, got {key!r}")
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        raise ValueError(f"object key has an empty or relative segment: {key!r}")
    if key.endswith(SIDECAR_SUFFIX):
        raise ValueError(f"object key may not end in {SIDECAR_SUFFIX!r}: {key!r}")
    return key


def _resolve_range(size: int, start: int, end: int | None) -> tuple[int, int] | None:
    """Clamp an inclusive `[start, end]` request to what the object holds.

    The decisions, identical in both adapters because both call this:

    * **`end` past the last byte is clamped**, not an error. A caller asking
      for "a megabyte from here" at the tail of a recording wants the tail, and
      making that an error would push the same clamping into every caller.
    * **`start` at or beyond the end yields nothing** — an empty iterator, not
      an exception and not a short read of the last byte. HTTP answers this
      with 416, but a 416 is a *protocol* decision that belongs to the handler
      serving the range; the port's answer is "there are no bytes there", which
      the handler can turn into 416, an empty body, or a 200 as it sees fit.
      S3 really does raise `InvalidRange` for this, so the S3 adapter uses the
      size it already has from `head_object` and never sends the request.
    * A **negative** bound is an error. Negative offsets mean "from the end" in
      HTTP's Range grammar; nothing here needs suffix ranges, and silently
      treating -1 as byte 0 would hide the caller's bug.

    Returns the concrete `(first, last)` byte offsets, or `None` for "no bytes".
    """
    if start < 0:
        raise ValueError(f"range start must not be negative, got {start}")
    if end is not None and end < 0:
        raise ValueError(f"range end must not be negative, got {end}")
    last = size - 1
    resolved_end = last if end is None else min(end, last)
    if size == 0 or start > resolved_end:
        return None
    return start, resolved_end


# ------------------------------------------------------------- filesystem ----


# Not frozen: `ByteSource` declares `size` and `content_type` as plain
# attributes, and mypy only accepts a settable attribute as satisfying a
# settable protocol member. Nothing writes to either after construction.
@dataclass
class _FileByteSource:
    """A local file, read through the port's range rules."""

    path: Path
    size: int
    content_type: str

    def read(self, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """Stream the inclusive range, seeking rather than reading and slicing."""
        window = _resolve_range(self.size, start, end)
        if window is None:
            return iter(())
        return self._stream(*window)

    def _stream(self, first: int, last: int) -> Iterator[bytes]:
        remaining = last - first + 1
        with self.path.open("rb") as handle:
            handle.seek(first)
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:  # truncated under us; stop rather than spin
                    return
                remaining -= len(chunk)
                yield chunk


class FilesystemObjectStore:
    """Objects as files under `root`. The default when no bucket is configured.

    The content type is kept in a sibling `<name>.content-type` file. A
    filesystem has nowhere else to put it, and dropping it would make the two
    adapters disagree about what `open` reports — the one thing this port is
    for. The sidecar is why `SIDECAR_SUFFIX` keys are refused everywhere.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def put(self, key: str, source: Path, *, content_type: str) -> None:
        """Copy `source` to `root/key`, creating parents, and record its type.

        `shutil.copyfile` streams; the file is never read into memory, which is
        the same promise `upload_file` makes on the S3 side.
        """
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self._sidecar(target).write_text(content_type, encoding="utf-8")

    def open(self, key: str) -> ByteSource | None:
        """Open `root/key`, or `None` when there is no such file."""
        path = self._path(key)
        if not path.is_file():
            return None
        sidecar = self._sidecar(path)
        content_type = (
            sidecar.read_text(encoding="utf-8") if sidecar.is_file() else DEFAULT_CONTENT_TYPE
        )
        return _FileByteSource(path=path, size=path.stat().st_size, content_type=content_type)

    def _path(self, key: str) -> Path:
        return self.root / _validate_key(key)

    @staticmethod
    def _sidecar(target: Path) -> Path:
        return target.with_name(target.name + SIDECAR_SUFFIX)


# --------------------------------------------------------------------- s3 ----

#: Error codes a `head_object` returns for something that is not there. S3
#: sends a bare `404`; other implementations and the GET path send
#: `NoSuchKey`/`NotFound`.
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def _is_not_found(exc: ClientError) -> bool:
    """True when a `ClientError` is a 404 rather than something worse."""
    error = exc.response.get("Error", {})
    code = str(error.get("Code", ""))
    status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
    return code in _NOT_FOUND_CODES or status == 404


@dataclass
class _S3ByteSource:
    """One S3 object, sized once by `head_object` and then served by range."""

    client: Any
    bucket: str
    key: str
    size: int
    content_type: str

    def read(self, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """Stream the inclusive range with a ranged GET, or nothing at all.

        The empty case never reaches S3: the size is already known, and a
        request for bytes past the end would come back as `InvalidRange`
        rather than as the empty read the port promises.
        """
        window = _resolve_range(self.size, start, end)
        if window is None:
            return iter(())
        return self._stream(*window)

    def _stream(self, first: int, last: int) -> Iterator[bytes]:
        response = self.client.get_object(
            Bucket=self.bucket, Key=self.key, Range=f"bytes={first}-{last}"
        )
        body = response["Body"]
        try:
            yield from body.iter_chunks(CHUNK_SIZE)
        finally:
            body.close()


class S3ObjectStore:
    """S3, or anything that speaks it — MinIO in dev, a real bucket in prod.

    Credentials come from boto3's default chain and are never read here. The
    bucket must already exist; this adapter does not create one, because
    creating a bucket is a deployment action with a region, a policy and a
    retention tag attached to it, none of which belong in a write path.
    """

    def __init__(
        self,
        bucket: str,
        *,
        region: str | None = None,
        prefix: str = "",
        endpoint: str | None = None,
        force_path_style: bool = False,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        # Path-style addressing is what an S3-compatible server on a bare host
        # or IP needs: `http://127.0.0.1:9000/bucket/key` rather than a
        # virtual-hosted `http://bucket.127.0.0.1:9000/key` that does not
        # resolve. AWS itself is happy either way, so this stays configuration.
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint,
            config=Config(s3={"addressing_style": "path" if force_path_style else "auto"}),
        )

    def put(self, key: str, source: Path, *, content_type: str) -> None:
        """Upload `source` under `key`, multipart above boto3's own threshold.

        `upload_file` is the managed transfer: it chunks anything past its
        default threshold into a multipart upload and streams every part from
        disk, so a long recording costs one file handle rather than its own
        size in memory.
        """
        self.client.upload_file(
            str(source), self.bucket, self._key(key), ExtraArgs={"ContentType": content_type}
        )

    def open(self, key: str) -> ByteSource | None:
        """`head_object` for the size and type; `None` when the object is gone.

        **A 404 here is checked against the bucket before it is believed.** A
        HEAD response carries no body, so botocore has no error code to report
        and a missing *bucket* is indistinguishable from a missing *object* —
        both arrive as a bare `404` (verified against MinIO; S3 behaves the
        same way, for the same reason). Returning `None` on that would turn a
        wrong or undeployed bucket into "no session has a recording", silently,
        for every session. `head_bucket` costs one extra request on the miss
        path only, and a miss is the rare case: a session either has its
        recording or never made one.
        """
        real_key = self._key(key)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=real_key)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            self._require_bucket()
            return None
        return _S3ByteSource(
            client=self.client,
            bucket=self.bucket,
            key=real_key,
            size=int(head["ContentLength"]),
            content_type=str(head.get("ContentType") or DEFAULT_CONTENT_TYPE),
        )

    def _key(self, key: str) -> str:
        """The real object key: the logical key under `S3_PREFIX`."""
        validated = _validate_key(key)
        return f"{self.prefix}/{validated}" if self.prefix else validated

    def _require_bucket(self) -> None:
        """Raise unless the bucket really is there — see `open` for why."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            raise RuntimeError(
                f"S3 bucket {self.bucket!r} does not exist or is not reachable; "
                f"this is a configuration fault, not a missing recording"
            ) from exc


# ------------------------------------------------------------------- wiring ----


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def object_store_from_env() -> ObjectStore:
    """The configured store: S3 when `S3_BUCKET` is set, local disk otherwise.

    The bucket is the switch rather than a separate `OBJECT_STORE_BACKEND`
    variable, so there is no way to configure "S3, but without a bucket" or
    "disk, but with one" — the two settings that would need a runtime error to
    catch simply cannot be written down.
    """
    bucket = os.getenv("S3_BUCKET", "").strip()
    if not bucket:
        return FilesystemObjectStore(os.getenv("OBJECT_STORE_DIR") or DEFAULT_OBJECT_STORE_DIR)
    return S3ObjectStore(
        bucket,
        region=os.getenv("S3_REGION", "").strip() or None,
        prefix=os.getenv("S3_PREFIX", "").strip(),
        endpoint=os.getenv("S3_ENDPOINT", "").strip() or None,
        force_path_style=_flag("S3_FORCE_PATH_STYLE"),
    )
