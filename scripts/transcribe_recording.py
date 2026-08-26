"""Turn a stereo session recording into a speaker-labelled turn list.

The browser records `channel_layout = "manager_left_candidate_right"`, so the
two speakers are already physically separated. Transcribing each channel on its
own means speaker labels are exact rather than the output of a diarisation
model that guesses -- which is the whole reason the recorder was built that way.

    python scripts/transcribe_recording.py session.webm -o turns.json

Costs money: one ASR call per channel. Not part of scripts/check.sh.

NOTE ON LAYERING: this reaches for the vendor SDK directly because it is a
script, not a package -- `tests/test_architecture.py` does not scan `scripts/`.
When the English module lands (spec phase 7) the ASR adapter belongs in `llm/`
behind a port, like every other vendor call in this repo.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

CHANNELS = {"left": "manager", "right": "candidate"}

#: A segment whose own channel is near-silent across its span is bleed from the
#: other speaker or an ASR hallucination on silence, not speech. Dropping it is
#: the difference between a usable transcript and a haunted one.
SILENCE_RMS = 0.006
NO_SPEECH_MAX = 0.6

#: Gap between same-speaker segments above which a new turn starts.
TURN_GAP_MS = 1500


def split_channels(source: Path, workdir: Path) -> dict[str, Path]:
    """Decode to 16 kHz mono WAVs, one per speaker channel."""
    workdir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for index, side in enumerate(("left", "right")):
        target = workdir / f"{side}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-af",
                f"pan=mono|c0=c{index}",
                "-ar",
                "16000",
                str(target),
            ],
            check=True,
        )
        out[side] = target
    return out


def rms_profile(path: Path, window_ms: int = 100) -> list[float]:
    """Per-window RMS, so a segment can be checked against its own channel."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    per_window = int(rate * window_ms / 1000)
    profile = []
    for start in range(0, len(samples), per_window):
        chunk = samples[start : start + per_window]
        if not chunk:
            break
        profile.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768.0)
    return profile


def loud_enough(profile: list[float], start_s: float, end_s: float) -> bool:
    """Whether this channel actually carries speech across the segment."""
    lo, hi = int(start_s * 10), max(int(end_s * 10), int(start_s * 10) + 1)
    window = profile[lo:hi]
    return bool(window) and max(window) >= SILENCE_RMS


def transcribe(client, path: Path) -> list[dict]:
    """One channel, with segment timestamps."""
    with path.open("rb") as handle:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=handle,
            response_format="verbose_json",
            language="en",
        )
    return [s if isinstance(s, dict) else s.model_dump() for s in (result.segments or [])]


def build_turns(collected: list[dict]) -> list[dict]:
    """Merge time-ordered segments into speaker turns."""
    collected.sort(key=lambda s: s["start_ms"])
    turns: list[dict] = []
    for segment in collected:
        if (
            turns
            and turns[-1]["speaker"] == segment["speaker"]
            and segment["start_ms"] - turns[-1]["end_ms"] <= TURN_GAP_MS
        ):
            turns[-1]["text"] = f"{turns[-1]['text']} {segment['text']}".strip()
            turns[-1]["end_ms"] = segment["end_ms"]
            continue
        turns.append({**segment})
    for index, turn in enumerate(turns):
        turn["index"] = index
        turn["elapsed_ms"] = turn["start_ms"]
    return turns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=Path("/tmp/transcribe"))
    args = parser.parse_args()

    from openai import OpenAI

    client = OpenAI()
    channels = split_channels(args.recording, args.workdir)

    collected: list[dict] = []
    for side, path in channels.items():
        speaker = CHANNELS[side]
        profile = rms_profile(path)
        kept = dropped = 0
        for segment in transcribe(client, path):
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            if segment.get("no_speech_prob", 0.0) > NO_SPEECH_MAX or not loud_enough(
                profile, segment["start"], segment["end"]
            ):
                dropped += 1
                continue
            kept += 1
            collected.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "start_ms": int(segment["start"] * 1000),
                    "end_ms": int(segment["end"] * 1000),
                }
            )
        print(f"{speaker:<10} kept {kept} segments, dropped {dropped}", file=sys.stderr)

    turns = build_turns(collected)
    args.out.write_text(json.dumps({"turns": turns}, indent=2), encoding="utf-8")
    words = sum(len(t["text"].split()) for t in turns)
    print(f"wrote {args.out}: {len(turns)} turns, {words} words", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
