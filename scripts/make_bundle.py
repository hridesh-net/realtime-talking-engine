"""Build a report-engine bundle.

The report engine is standalone and reads no database, so something has to
assemble its input. That is this script's whole job.

    python scripts/make_bundle.py --session <id> -o bundle.json      # from control_plane.db
    python scripts/make_bundle.py --transcript turns.json ... -o b.json  # from a file
    python scripts/make_bundle.py --demo -o bundle.json              # a worked example

The rubric and the persona are read from the packages that own them
(`evaluation_agent`, `candidate_agent`) and copied into the bundle, which is why
`report_engine` never imports a sibling package.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from candidate_agent import archetypes
from evaluation_agent.rubric import DEFAULT_RUBRIC

ROOT = Path(__file__).resolve().parent.parent


def persona_block(key: str) -> dict[str, Any]:
    archetype = archetypes.get(key)
    return {
        "archetype_key": archetype.key,
        "label": archetype.label,
        "must_discover": [
            {
                "id": s.id,
                "signal": s.signal,
                "weight": s.weight,
                "how_to_surface": s.how_to_surface,
            }
            for s in archetype.must_discover
        ],
        "session_beats": list(archetype.session_beats),
        "stresses": dict(archetype.stresses),
    }


def from_db(session_id: str, db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise SystemExit(f"no session {session_id} in {db}")
    rows = conn.execute(
        "SELECT idx, speaker, text, elapsed_ms FROM session_turns "
        "WHERE session_id = ? ORDER BY idx",
        (session_id,),
    ).fetchall()
    recording = conn.execute(
        "SELECT * FROM session_recordings WHERE session_id = ?", (session_id,)
    ).fetchone()
    interview = conn.execute(
        "SELECT * FROM interviews WHERE id = ?", (session["interview_id"],)
    ).fetchone()
    conn.close()

    keys = set(session.keys())
    persona_key = session["persona_key"] if "persona_key" in keys else "cooperative_trap"
    return {
        "session": {
            "session_id": session_id,
            "modality": session["modality"],
            "planned_minutes": session["planned_minutes"] if "planned_minutes" in keys else 20,
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
        },
        "job_card": {
            "job_title": (interview["job_title"] if interview else "") or "Unknown role",
            "summary": "",
            "role_family": "sales",
            "clarity_facts": [],
        },
        "persona": persona_block(
            persona_key if persona_key in archetypes.ARCHETYPES else "cooperative_trap"
        ),
        "turns": [
            {
                "index": r["idx"],
                "speaker": r["speaker"],
                "text": r["text"],
                "elapsed_ms": r["elapsed_ms"],
            }
            for r in rows
        ],
        "recording": (
            {"path": str(ROOT / "recordings" / f"{session_id}.webm"), "status": recording["status"]}
            if recording
            else None
        ),
    }


def from_transcript(path: Path, persona: str, title: str, family: str) -> dict[str, Any]:
    """Build from a plain turn list: [{speaker, text, elapsed_ms?}, ...]."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    turns = raw["turns"] if isinstance(raw, dict) else raw
    normalised = []
    for i, turn in enumerate(turns):
        speaker = turn["speaker"]
        normalised.append(
            {
                "index": turn.get("index", i),
                "speaker": "manager" if speaker in {"manager", "interviewer"} else "candidate",
                "text": turn["text"],
                "elapsed_ms": turn.get("elapsed_ms", i * 20000),
                "start_ms": turn.get("start_ms"),
                "end_ms": turn.get("end_ms"),
            }
        )
    return {
        "session": {"session_id": path.stem, "modality": "text"},
        "job_card": {"job_title": title, "role_family": family, "clarity_facts": []},
        "persona": persona_block(persona),
        "turns": normalised,
        "recording": None,
    }


def wrap(core: dict[str, Any], jurisdiction: str) -> dict[str, Any]:
    core["bundle_version"] = "v1"
    core["rubric"] = DEFAULT_RUBRIC.model_dump()
    core["jurisdiction"] = jurisdiction
    core.setdefault("scoring_options", {"english_weight": None, "language_gate": True})
    return core


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", help="session id in control_plane.db")
    parser.add_argument("--db", type=Path, default=ROOT / "control_plane.db")
    parser.add_argument("--transcript", type=Path, help="a JSON turn list")
    parser.add_argument("--demo", action="store_true", help="build the worked example")
    parser.add_argument("--persona", default="inflated_resume")
    parser.add_argument("--title", default="Assistant Store Manager")
    parser.add_argument("--family", default="sales")
    parser.add_argument("--jurisdiction", default="IN")
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()

    if args.demo:
        core = json.loads((ROOT / "tests" / "fixtures" / "demo_turns.json").read_text())
        core["persona"] = persona_block(core["persona_key"])
        core.pop("persona_key")
    elif args.session:
        core = from_db(args.session, args.db)
    elif args.transcript:
        core = from_transcript(args.transcript, args.persona, args.title, args.family)
    else:
        raise SystemExit("pass one of --session, --transcript or --demo")

    args.out.write_text(json.dumps(wrap(core, args.jurisdiction), indent=2), encoding="utf-8")
    print(f"wrote {args.out} ({len(core['turns'])} turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
