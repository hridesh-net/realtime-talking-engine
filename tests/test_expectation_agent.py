"""Smoke tests for interview expectation generation across scenarios."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane.database import init_db
from control_plane.repository import InterviewRepository
from control_plane.schemas import InterviewCreateRequest
from expectation_agent.agent import InterviewExpectationAgent

load_dotenv()


SCENARIOS = [
    {
        "name": "junior_frontend_startup",
        "payload": {
            "job_title": "Junior Frontend Developer",
            "jd": "Entry-level React role building customer dashboards.",
            "skills_required": ["React", "JavaScript", "CSS"],
            "job_location_type": "onsite",
            "experience_level": "junior",
            "company_type": "startup",
        },
        "expected_type": "technical_coding",
        "expected_resume": False,
    },
    {
        "name": "mid_fullstack_mnc",
        "payload": {
            "job_title": "Full-Stack Engineer",
            "jd": "Mid-level engineer owning features end-to-end across React and Node.js.",
            "skills_required": ["React", "Node.js", "TypeScript", "PostgreSQL"],
            "job_location_type": "hybrid",
            "experience_level": "mid",
            "company_type": "mnc",
        },
        "expected_type": "mixed",
        "expected_resume": True,
    },
    {
        "name": "senior_backend_startup",
        "payload": {
            "job_title": "Senior Backend Engineer",
            "jd": (
                "Senior backend engineer with strong Go, distributed systems, Redis, "
                "and microservices. Must design scalable services and mentor juniors."
            ),
            "skills_required": [
                "Go",
                "distributed systems",
                "Redis",
                "microservices",
                "system design",
            ],
            "job_location_type": "remote",
            "experience_level": "senior",
            "company_type": "startup",
        },
        "expected_type": "technical_discussion",
        "expected_resume": True,
    },
    {
        "name": "senior_data_mnc",
        "payload": {
            "job_title": "Senior Data Engineer",
            "jd": (
                "Build large-scale data pipelines with Spark, Airflow, and Kafka. "
                "Own data quality and observability."
            ),
            "skills_required": ["Spark", "Airflow", "Kafka", "Python", "data quality"],
            "job_location_type": "remote",
            "experience_level": "senior",
            "company_type": "mnc",
        },
        "expected_type": "mixed",
        "expected_resume": True,
    },
    {
        "name": "junior_mobile_startup",
        "payload": {
            "job_title": "Junior iOS Engineer",
            "jd": "Junior iOS developer building SwiftUI apps.",
            "skills_required": ["Swift", "SwiftUI", "Xcode"],
            "job_location_type": "onsite",
            "experience_level": "junior",
            "company_type": "startup",
        },
        "expected_type": "technical_coding",
        "expected_resume": False,
    },
]


def validate_expectation(
    name: str,
    interview_id: str,
    payload: dict[str, Any],
    exp: dict[str, Any],
    expected_type: str,
    expected_resume: bool,
) -> list[str]:
    """Return a list of validation failures."""
    failures: list[str] = []

    # 1. Deterministic interview type
    if exp.get("interview_type") != expected_type:
        failures.append(f"interview_type={exp.get('interview_type')} expected={expected_type}")

    # 2. Structure durations sum to interview duration
    total = sum(p["duration_minutes"] for p in exp.get("structure", []))
    if total != 60:
        failures.append(f"structure durations sum to {total}, expected 60")

    # 3. All input skills are covered
    covered = {s["skill"] for s in exp.get("mandatory_skills", [])} | {
        s["skill"] for s in exp.get("optional_skills", [])
    }
    for skill in payload["skills_required"]:
        if skill not in covered:
            failures.append(f"skill '{skill}' missing from output")

    # 4. Evaluation criteria match fixed rubric exactly
    criteria = exp.get("evaluation_criteria", [])
    if len(criteria) != 6:
        failures.append(f"evaluation_criteria has {len(criteria)} items, expected 6")
    expected_names = {
        "communication",
        "problem_solving",
        "technical_depth",
        "system_design",
        "cultural_fit",
        "code_quality",
    }
    actual_names = {c["name"] for c in criteria}
    if actual_names != expected_names:
        failures.append(f"criteria names mismatch: {actual_names} != {expected_names}")

    # 5. Resume probing rule
    if exp["resume_probing"]["required"] != expected_resume:
        actual = exp["resume_probing"]["required"]
        failures.append(f"resume_probing.required={actual} expected={expected_resume}")

    # 6. Red/green flags include baseline items
    baseline_red = {
        "Cannot explain trade-offs of chosen technology",
        "Blames external factors without ownership",
    }
    if not baseline_red.issubset(set(exp.get("red_flags", []))):
        failures.append("baseline red flags missing")

    baseline_green = {
        "Explains why a decision was made, not just what",
        "Asks clarifying questions before solving",
    }
    if not baseline_green.issubset(set(exp.get("green_flags", []))):
        failures.append("baseline green flags missing")

    # 7. interview_id matches
    if exp.get("interview_id") != interview_id:
        failures.append(f"interview_id mismatch: {exp.get('interview_id')} != {interview_id}")

    return failures


async def run_scenario(scenario: dict[str, Any]) -> list[str]:
    repo = InterviewRepository(init_db(":memory:"))
    agent = InterviewExpectationAgent()

    # Create interview
    req = InterviewCreateRequest(**scenario["payload"])
    interview = repo.create(req)

    # Generate expectation
    # resume probing is required when a resume is attached and role is not junior
    has_resume = scenario["payload"]["experience_level"] != "junior"
    exp = await agent.generate(
        interview_id=interview.id,
        job_title=interview.job_title,
        jd=interview.jd,
        skills_required=interview.skills_required,
        job_location_type=interview.job_location_type,
        experience_level=interview.experience_level,
        company_type=interview.company_type,
        duration_minutes=interview.config.duration_minutes,
        mode=interview.mode,
        has_resume=has_resume,
    )

    return validate_expectation(
        name=scenario["name"],
        interview_id=interview.id,
        payload=scenario["payload"],
        exp=exp.model_dump(),
        expected_type=scenario["expected_type"],
        expected_resume=scenario["expected_resume"],
    )


async def main() -> None:
    results: dict[str, list[str]] = {}
    for scenario in SCENARIOS:
        print(f"Testing {scenario['name']} ...")
        try:
            failures = await run_scenario(scenario)
            results[scenario["name"]] = failures
            if failures:
                print(f"  FAIL: {failures}")
            else:
                print("  PASS")
        except Exception as e:
            results[scenario["name"]] = [f"exception: {e}"]
            print(f"  ERROR: {e}")

    print("\n=== Summary ===")
    passed = sum(1 for f in results.values() if not f)
    print(f"Passed: {passed}/{len(SCENARIOS)}")
    for name, failures in results.items():
        if failures:
            print(f"\n{name}:")
            for f in failures:
                print(f"  - {f}")


if __name__ == "__main__":
    asyncio.run(main())
