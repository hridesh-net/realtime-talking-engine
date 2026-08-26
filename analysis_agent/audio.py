"""Audio windowing for the analysis harness.

Long recordings are cut into overlapping windows before they reach the model.
That solves two problems at once, and the second is the one that matters:

1. A whole interview may exceed what one request can carry.
2. **A model loses track of elapsed time over long audio.** Measured on a real
   5m46s session, 21 of 53 returned turns claimed to end after the recording
   did - the furthest at 9m06s. Anchors that point past the end of the file are
   worse than no anchors, because the report's whole claim is that every
   statement cites a moment you can go and listen to.

   Short windows keep the model's internal clock honest, and the offset is added
   by code afterwards rather than trusted from the model.

`ffmpeg` is a media tool invoked as a subprocess, not a vendor SDK, so it does
not belong behind the `llm/` boundary.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Long enough to hold a full exchange, short enough that the model's sense of
#: elapsed time stays reliable. See the module docstring for why this is not
#: simply "as much as the request will carry".
WINDOW_MS = 240_000

#: Overlap so an exchange spanning a boundary is heard whole by one window.
#: The merge step drops the duplicates this produces.
OVERLAP_MS = 20_000


class AudioError(RuntimeError):
    """The recording could not be read or cut."""


@dataclass(frozen=True)
class Window:
    """One span of audio, and where it sits in the whole recording."""

    index: int
    offset_ms: int
    duration_ms: int
    data: bytes


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AudioError("ffmpeg/ffprobe not found on PATH")


_TIME = re.compile(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def duration_ms(path: Path) -> int:
    """Length of the recording in milliseconds.

    Falls back to decoding when the container does not say. **Every recording
    the browser produces needs that fallback**: `MediaRecorder` writes WebM as a
    live stream, so the header carries no duration and `ffprobe` reports none.
    Decoding to null is slower than reading a header and is the only answer that
    works on the files this system actually stores.
    """
    _require_ffmpeg()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise AudioError(f"ffprobe failed: {probe.stderr.strip()[:200]}")
    try:
        return int(float(json.loads(probe.stdout)["format"]["duration"]) * 1000)
    except (KeyError, ValueError, json.JSONDecodeError):
        pass

    decoded = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostdin", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    matches = _TIME.findall(decoded.stderr)
    if not matches:
        raise AudioError("could not determine the recording's duration")
    hours, minutes, seconds = matches[-1]
    return int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def plan(
    total_ms: int, *, window_ms: int = WINDOW_MS, overlap_ms: int = OVERLAP_MS
) -> list[tuple[int, int]]:
    """`(offset_ms, duration_ms)` for each window. Pure, so it is testable."""
    if total_ms <= 0:
        return []
    if total_ms <= window_ms:
        return [(0, total_ms)]
    step = window_ms - overlap_ms
    spans: list[tuple[int, int]] = []
    offset = 0
    while offset < total_ms:
        spans.append((offset, min(window_ms, total_ms - offset)))
        if offset + window_ms >= total_ms:
            break
        offset += step
    return spans


def cut(path: Path, *, window_ms: int = WINDOW_MS, overlap_ms: int = OVERLAP_MS) -> list[Window]:
    """Cut the recording into windows, re-encoding each to a self-contained file.

    Re-encoding rather than stream-copying is deliberate: a copied WebM fragment
    carries no header of its own and no model will read it.
    """
    total = duration_ms(path)
    windows: list[Window] = []
    for index, (offset, span) in enumerate(plan(total, window_ms=window_ms, overlap_ms=overlap_ms)):
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-ss",
                f"{offset / 1000:.3f}",
                "-t",
                f"{span / 1000:.3f}",
                "-i",
                str(path),
                "-ac",
                "2",
                "-ar",
                "16000",
                "-f",
                "wav",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            raise AudioError(f"ffmpeg failed on window {index}: {result.stderr.decode()[:200]}")
        windows.append(Window(index=index, offset_ms=offset, duration_ms=span, data=result.stdout))
    return windows
