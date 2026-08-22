"""Regenerate the JSON Schema contracts in owner_handover/.

Derived from the Pydantic models so the handover cannot drift from the code.
Hand-written samples in that folder are left alone.

Run:  .venv/bin/python scripts/export_schemas.py
      .venv/bin/python scripts/export_schemas.py --check   # CI: fail if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_agent import archetypes as catalog
from candidate_agent.schema import EngineContract, VirtualCandidate
from control_plane.schemas import (
    CandidateEnrollRequest,
    InterviewResponse,
    RealtimeCredentialResponse,
    SessionCreateRequest,
    SessionResponse,
    SessionSummary,
    TranscriptAppendRequest,
)
from expectation_agent.schema import InterviewExpectation

OUT = Path(__file__).resolve().parent.parent / "owner_handover"

EXPORTS = [
    (
        "candidate_enroll_schema.json",
        CandidateEnrollRequest,
        "Body for POST /api/v1/interviews/{interview_id}/candidates. Send no body to "
        "enroll the two defaults: the bias trap and the evasive candidate, which "
        "carry the heaviest rubric criteria between them.",
    ),
    (
        "candidate_output_schema.json",
        VirtualCandidate,
        "One virtual candidate persona. Returned by the enrollment endpoint and by "
        "GET /api/v1/candidates/{candidate_id}.",
    ),
    (
        "engine_contract_schema.json",
        EngineContract,
        "The runtime slice the Go interview-candidate engine consumes. Served by "
        "GET /api/v1/candidates/{candidate_id}/engine-contract.",
    ),
    (
        "interview_response_schema.json",
        InterviewResponse,
        "Interview record returned by the interview endpoints.",
    ),
    (
        "session_create_schema.json",
        SessionCreateRequest,
        "Body for POST /api/v1/sessions. Opens a live typed interview against one "
        "persona, casting it first if that archetype is not yet enrolled.",
    ),
    (
        "session_output_schema.json",
        SessionResponse,
        "A live or finished interview session with its full server-stamped "
        "transcript. Returned by the session endpoints; this is the artifact the "
        "evaluation layer reads, and the shape the Go voice engine will emit.",
    ),
    (
        "session_summary_schema.json",
        SessionSummary,
        "One row of GET /api/v1/interviews/{interview_id}/sessions. A session "
        "without its transcript, for listing what has been run against an "
        "interview.",
    ),
    (
        "session_realtime_schema.json",
        RealtimeCredentialResponse,
        "Returned by POST /api/v1/sessions/{session_id}/realtime. Everything a "
        "browser needs to open a speech-to-speech session with the realtime "
        "vendor directly. The persona instructions are sealed into the minted "
        "credential vendor-side and are deliberately not included here.",
    ),
    (
        "session_transcript_append_schema.json",
        TranscriptAppendRequest,
        "Body for POST /api/v1/sessions/{session_id}/transcript. Records a turn "
        "that was spoken elsewhere (a voice session) without generating a reply.",
    ),
    (
        "expectation_output_schema.json",
        InterviewExpectation,
        "Interviewer expectation document for one interview.",
    ),
]


def _rendered() -> dict[str, str]:
    """Every generated file, as {filename: content}."""
    out: dict[str, str] = {}
    for filename, model, description in EXPORTS:
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["description"] = description
        out[filename] = json.dumps(schema, indent=2) + "\n"

    # The archetype catalog is data, not a schema — ship it as-is so the owner
    # can see every persona option without running the service.
    out["candidate_archetypes.json"] = (
        json.dumps(
            {
                "catalog_version": catalog.CATALOG_VERSION,
                "defaults": catalog.default_keys(),
                "trait_axes": list(catalog.TRAIT_NAMES),
                "rubric_criteria": {c: catalog.RUBRIC_LABELS[c] for c in catalog.RUBRIC_CRITERIA},
                "stress_labels": list(catalog.STRESS_LABELS),
                "archetypes": [
                    {
                        **row,
                        "knowledge_band": list(catalog.get(row["key"]).knowledge_band),
                        "speech": catalog.get(row["key"]).speech,
                        "answer_policy": catalog.get(row["key"]).answer_policy,
                        "must_discover": [
                            {
                                "id": s.id,
                                "signal": s.signal,
                                "weight": s.weight,
                                "how_to_surface": s.how_to_surface,
                            }
                            for s in catalog.get(row["key"]).must_discover
                        ],
                        "interviewer_failure_modes": catalog.get(
                            row["key"]
                        ).interviewer_failure_modes,
                    }
                    for row in catalog.catalog()
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any file on disk differs from what the code produces",
    )
    args = parser.parse_args()

    stale: list[str] = []
    for filename, content in _rendered().items():
        path = OUT / filename
        current = path.read_text() if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(filename)
            continue
        path.write_text(content)
        print(f"wrote owner_handover/{filename}")

    if args.check:
        if stale:
            print("owner_handover/ is stale; run scripts/export_schemas.py:")
            for filename in stale:
                print(f"  - {filename}")
            return 1
        print("owner_handover/ matches the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
