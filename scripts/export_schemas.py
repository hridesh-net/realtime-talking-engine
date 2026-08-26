"""Regenerate the JSON Schema contracts in owner_handover/.

Derived from the Pydantic models so the handover cannot drift from the code.
Most samples in that folder are hand-written and left alone — except
``engine_contract_sample.json``, whose ``--check`` here also verifies it is
still on the current ``ENGINE_CONTRACT_VERSION`` and still carries every v1.3
field non-empty. That sample is generated, not hand-written — see
``scripts/export_engine_contract_sample.py``, which this check does not run
(no live model call happens here); it only asserts the checked-in file has not
gone stale relative to the schema. A v1.0 sample sitting next to a v1.3 schema
previously passed this script silently, because ``--check`` here only ever
validated schemas, never the samples.

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
from candidate_agent.schema import ENGINE_CONTRACT_VERSION, EngineContract, VirtualCandidate
from control_plane.schemas import (
    CandidateEnrollRequest,
    InterviewResponse,
    RealtimeCredentialResponse,
    RecordingMeta,
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
        "session_recording_schema.json",
        RecordingMeta,
        "A session's audio artifact. Returned by the recording endpoints and "
        "embedded in SessionResponse. Bytes are served separately by "
        "GET /api/v1/sessions/{session_id}/recording; storage_key is "
        "server-internal and deliberately not part of this shape.",
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


#: v1.3 fields the sample must carry non-empty. `unlock_spec` is checked
#: separately below (its "empty" isn't the same shape as the others').
_V13_LIST_FIELDS = ("precompiled_beliefs", "stall_phrases", "pregate_lexicon", "tts_voice_id")


def _stale_engine_contract_sample() -> list[str]:
    """Problems with owner_handover/engine_contract_sample.json, if any.

    Catches exactly the defect this check exists for: a sample left on an
    older `contract_version` after the schema moved on, silently passing a
    schema-only `--check`. Regenerate with
    `scripts/export_engine_contract_sample.py` — this function does not fix
    anything, only names what is wrong.
    """
    path = OUT / "engine_contract_sample.json"
    if not path.exists():
        return [f"engine_contract_sample.json is missing (expected at {path})"]

    try:
        sample = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"engine_contract_sample.json is not valid JSON: {exc}"]

    problems: list[str] = []

    version = sample.get("contract_version")
    if version != ENGINE_CONTRACT_VERSION:
        problems.append(
            f"contract_version is {version!r}, want {ENGINE_CONTRACT_VERSION!r} "
            "(ENGINE_CONTRACT_VERSION in candidate_agent/schema.py)"
        )

    for field in _V13_LIST_FIELDS:
        if not sample.get(field):
            problems.append(f"{field!r} is empty or missing — v1.3 samples must carry it")

    unlock_spec = sample.get("unlock_spec")
    if not isinstance(unlock_spec, dict) or not unlock_spec.get("kind"):
        problems.append("'unlock_spec' is missing a 'kind' — v1.3 samples must carry a real spec")

    return problems


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

    sample_problems = _stale_engine_contract_sample() if args.check else []

    if args.check:
        ok = True
        if stale:
            ok = False
            print("owner_handover/ is stale; run scripts/export_schemas.py:")
            for filename in stale:
                print(f"  - {filename}")
        if sample_problems:
            ok = False
            print(
                "owner_handover/engine_contract_sample.json is stale; run "
                "scripts/export_engine_contract_sample.py:"
            )
            for problem in sample_problems:
                print(f"  - {problem}")
        if not ok:
            return 1
        print("owner_handover/ matches the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
