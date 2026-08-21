"""Live scenario tests for virtual candidate enrollment.

Hits the real model. Asserts the invariants the report and the Go engine depend
on: verdicts and traits come from the catalog, knowledge stays under the
ceiling, every required skill is covered, and the engine contract is complete.

Run:  .venv/bin/python tests/test_candidate_agent.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_agent import archetypes as catalog
from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.schema import VirtualCandidate
from control_plane.database import init_db
from control_plane.repository import InterviewRepository
from control_plane.schemas import InterviewCreateRequest

load_dotenv()


JOB = {
    "job_title": "Senior Backend Engineer",
    "jd": (
        "Senior backend engineer for a payments platform. Go services, event-driven "
        "architecture on Kafka, Postgres at scale. Owns design and on-call."
    ),
    "skills_required": ["Go", "Kafka", "PostgreSQL", "system design"],
    "job_location_type": "remote",
    "experience_level": "senior",
    "company_type": "startup",
}

#: One per behavioural family, plus both defaults.
SCENARIOS: list[str] = [
    "strong_hire",
    "clear_reject",
    "smart_but_lazy",
    "confident_bluffer",
    "nervous_but_capable",
    "specialist_mismatch",
]


def validate(c: VirtualCandidate, archetype_key: str) -> list[str]:
    fail: list[str] = []
    a = catalog.get(archetype_key)
    skills = JOB["skills_required"]

    # --- identity and verdict come from the catalog, never the model ---
    if c.archetype != a.key:
        fail.append(f"archetype drifted: {c.archetype} != {a.key}")
    if c.verdict != a.verdict:
        fail.append(f"verdict drifted: {c.verdict} != {a.verdict}")
    if c.interviewer_scorecard.expected_verdict != a.verdict:
        fail.append("scorecard verdict disagrees with the archetype")

    # --- traits inside bounds ---
    traits = c.aptitude.model_dump()
    for name, (lo, hi) in a.traits.items():
        if not lo <= traits[name] <= hi:
            fail.append(f"trait {name}={traits[name]} outside [{lo},{hi}]")
    expected_ratio = round(
        c.aptitude.smartness / max(1, c.aptitude.smartness + c.aptitude.dumbness), 2
    )
    if abs(c.aptitude.smartness_ratio - expected_ratio) > 0.01:
        fail.append(f"smartness_ratio {c.aptitude.smartness_ratio} != {expected_ratio}")

    # --- knowledge coverage and ceiling ---
    covered = [k.skill for k in c.knowledge_map]
    for s in skills:
        if s not in covered:
            fail.append(f"required skill missing from knowledge_map: {s}")
    lo, hi = a.knowledge_band
    for k in c.knowledge_map:
        if k.skill in skills and not lo <= k.level <= hi:
            fail.append(f"{k.skill} level {k.level} outside band [{lo},{hi}]")
        if not k.breaking_point:
            fail.append(f"{k.skill} has no breaking_point")

    # --- scorecard is the interviewer answer key ---
    ids = [i.id for i in c.interviewer_scorecard.must_discover]
    if ids != [s.id for s in a.must_discover]:
        fail.append(f"scorecard ids drifted: {ids}")
    weight = round(sum(i.weight for i in c.interviewer_scorecard.must_discover), 4)
    if weight != 1.0:
        fail.append(f"scorecard weights sum to {weight}")
    if not c.interviewer_scorecard.interviewer_failure_modes:
        fail.append("scorecard has no interviewer failure modes")

    # --- engine contract is runnable by the Go engine ---
    ec = c.engine_contract
    if not ec.system_prompt or len(ec.system_prompt) < 500:
        fail.append("system_prompt missing or too short to drive a persona")
    if c.name not in ec.system_prompt:
        fail.append("system_prompt does not name the persona")
    for s in skills:
        if s not in ec.system_prompt:
            fail.append(f"system_prompt omits required skill {s}")
    if set(ec.knowledge_ceiling) < set(skills):
        fail.append("knowledge_ceiling does not cover every required skill")
    tp = ec.turn_policy
    if not tp["min_sentences"] <= tp["target_sentences_per_answer"] <= tp["max_sentences"]:
        fail.append(f"turn_policy target outside its own bounds: {tp}")
    if not ec.opening_line:
        fail.append("no opening_line for the engine to start the session")
    if not ec.unlock_condition:
        fail.append("no unlock_condition — the engine cannot decide when to open up")

    # --- persona texture the whole exercise depends on ---
    if not c.speech_profile.sample_phrases:
        fail.append("no sample_phrases — the voice model has nothing to anchor to")
    if a.key == "confident_bluffer" and not any(k.wrong_beliefs for k in c.knowledge_map):
        fail.append("bluffer has no wrong_beliefs to be caught out on")
    # Dishonest archetypes must inflate something, or resume probing has no target.
    if a.traits["honesty"][1] <= 4 and all(r.truthfulness == "true" for r in c.resume_claims):
        fail.append("low-honesty persona has no exaggerated or false resume claim")

    return fail


async def run() -> dict[str, list[str]]:
    conn = init_db(":memory:")
    repo = InterviewRepository(conn)
    interview = repo.create(InterviewCreateRequest(**JOB))
    agent = VirtualCandidateAgent()

    results: dict[str, list[str]] = {}
    taken: list[str] = []

    for key in SCENARIOS:
        print(f"Casting {key} ...")
        try:
            c = await agent.generate(
                interview_id=interview.id,
                archetype_key=key,
                job_title=interview.job_title,
                jd=interview.jd,
                skills_required=interview.skills_required,
                experience_level=interview.experience_level,
                company_type=interview.company_type,
                job_location_type=interview.job_location_type,
                duration_minutes=interview.config.duration_minutes,
                interview_type="mixed",
                avoid_names=taken,
            )
            repo.save_candidate(c, model_used=agent.model)
            taken.append(c.name)
            failures = validate(c, key)
            results[key] = failures
            print(f"  {'PASS' if not failures else 'FAIL'}  {c.name} -> {c.verdict}")
            for f in failures:
                print(f"    - {f}")
        except Exception as e:
            results[key] = [f"exception: {e}"]
            print(f"  ERROR: {e}")

    # --- cross-cutting checks over the whole cast ---
    cast = repo.list_candidates(interview.id)
    cross: list[str] = []
    if len(cast) != len(SCENARIOS):
        cross.append(f"persisted {len(cast)} of {len(SCENARIOS)} candidates")
    names = [c.name for c in cast]
    if len(set(names)) != len(names):
        cross.append(f"duplicate names in one training set: {names}")
    if len({c.candidate_id for c in cast}) != len(cast):
        cross.append("duplicate candidate ids")
    results["_cast"] = cross
    print(f"\nCast check: {'PASS' if not cross else 'FAIL'}")
    for f in cross:
        print(f"  - {f}")

    # --- determinism: same seed must reproduce the same person ---
    print("\nRe-casting strong_hire with the same seed ...")
    again = await agent.generate(
        interview_id=interview.id,
        archetype_key="strong_hire",
        job_title=interview.job_title,
        jd=interview.jd,
        skills_required=interview.skills_required,
        experience_level=interview.experience_level,
        company_type=interview.company_type,
        job_location_type=interview.job_location_type,
        duration_minutes=interview.config.duration_minutes,
    )
    first = next(c for c in cast if c.archetype == "strong_hire")
    det: list[str] = []
    if again.candidate_id != first.candidate_id:
        det.append("candidate_id is not stable for the same seed")
    if again.aptitude.model_dump() != first.aptitude.model_dump():
        det.append("trait scores drifted between runs with the same seed")
    if again.seed_fingerprint != first.seed_fingerprint:
        det.append(
            f"seed_fingerprint drifted: {again.seed_fingerprint[:12]} != "
            f"{first.seed_fingerprint[:12]}"
        )
    # The content hash is *expected* to move on a re-cast — that is what makes it
    # useful as a tamper check. Assert it actually reacts to content.
    if again.fingerprint == first.fingerprint and again.name != first.name:
        det.append("fingerprint did not react to changed persona content")
    results["_determinism"] = det
    print(f"Determinism: {'PASS' if not det else 'FAIL'}")
    for f in det:
        print(f"  - {f}")

    return results


async def main() -> None:
    results = await run()
    print("\n=== Summary ===")
    passed = sum(1 for f in results.values() if not f)
    print(f"Passed: {passed}/{len(results)}")
    for name, failures in results.items():
        if failures:
            print(f"\n{name}:")
            for f in failures:
                print(f"  - {f}")
    sys.exit(1 if any(results.values()) else 0)


if __name__ == "__main__":
    asyncio.run(main())
