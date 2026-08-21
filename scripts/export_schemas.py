"""Regenerate the JSON Schema contracts in owner_handover/.

Derived from the Pydantic models so the handover cannot drift from the code.
Hand-written samples in that folder are left alone.

Run:  .venv/bin/python scripts/export_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_agent import archetypes as catalog
from candidate_agent.schema import EngineContract, VirtualCandidate
from control_plane.schemas import CandidateEnrollRequest, InterviewResponse
from expectation_agent.schema import InterviewExpectation

OUT = Path(__file__).resolve().parent.parent / "owner_handover"

EXPORTS = [
    (
        "candidate_enroll_schema.json",
        CandidateEnrollRequest,
        "Body for POST /api/v1/interviews/{interview_id}/candidates. Send no body to "
        "enroll the two defaults: one candidate who should be selected and one who "
        "should be rejected.",
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
        "expectation_output_schema.json",
        InterviewExpectation,
        "Interviewer expectation document for one interview.",
    ),
]


def main() -> None:
    for filename, model, description in EXPORTS:
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["description"] = description
        path = OUT / filename
        path.write_text(json.dumps(schema, indent=2) + "\n")
        print(f"wrote {path.relative_to(OUT.parent)}")

    # The archetype catalog is data, not a schema — ship it as-is so the owner
    # can see every persona option without running the service.
    catalog_path = OUT / "candidate_archetypes.json"
    catalog_path.write_text(
        json.dumps(
            {
                "catalog_version": catalog.CATALOG_VERSION,
                "defaults": catalog.default_keys(),
                "trait_axes": list(catalog.TRAIT_NAMES),
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
    print(f"wrote {catalog_path.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()
