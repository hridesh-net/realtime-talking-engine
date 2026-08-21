"""Deterministic rubric for interview expectation generation.

These rules are code-defined and versioned. The LLM fills in the blanks but
cannot override structure, weights, or constraints.
"""
from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# Fixed phase durations by experience level and interview duration
# ---------------------------------------------------------------------------
# (introduction, technical, candidate_questions, closing) in minutes
PHASE_TEMPLATE: Dict[str, Dict[int, List[int]]] = {
    "junior": {
        30: [3, 22, 3, 2],
        45: [5, 33, 4, 3],
        60: [5, 45, 5, 5],
    },
    "mid": {
        30: [3, 22, 3, 2],
        45: [5, 33, 4, 3],
        60: [5, 45, 5, 5],
    },
    "senior": {
        30: [3, 22, 3, 2],
        45: [5, 35, 4, 3],
        60: [5, 45, 5, 5],
    },
}

DEFAULT_PHASES = [5, 45, 5, 5]  # fallback for 60 min


def phase_durations(experience_level: str, duration_minutes: int) -> List[int]:
    """Return [intro, technical, candidate_questions, closing] minutes."""
    template = PHASE_TEMPLATE.get(experience_level, PHASE_TEMPLATE["mid"])
    if duration_minutes in template:
        return template[duration_minutes]
    # Scale linearly if no exact template
    base = DEFAULT_PHASES
    scale = duration_minutes / 60.0
    return [max(1, int(round(x * scale))) for x in base]


# ---------------------------------------------------------------------------
# Fixed evaluation criteria (mirrors BRD §9 / pkg/criteria)
# ---------------------------------------------------------------------------
EVALUATION_CRITERIA: List[Dict[str, object]] = [
    {
        "name": "communication",
        "weight": 0.15,
        "description": "Clarity, structure, and responsiveness of answers.",
    },
    {
        "name": "problem_solving",
        "weight": 0.25,
        "description": "Approach to ambiguous problems, trade-off analysis, decomposition.",
    },
    {
        "name": "technical_depth",
        "weight": 0.25,
        "description": "Accuracy, breadth, and depth in required skills.",
    },
    {
        "name": "system_design",
        "weight": 0.15,
        "description": "Ability to design scalable, maintainable systems.",
    },
    {
        "name": "cultural_fit",
        "weight": 0.10,
        "description": "Collaboration, ownership, growth mindset.",
    },
    {
        "name": "code_quality",
        "weight": 0.10,
        "description": "Readability, testing, error handling, best practices.",
    },
]


# ---------------------------------------------------------------------------
# Interview type selection rules
# ---------------------------------------------------------------------------
def determine_interview_type(experience_level: str, company_type: str) -> str:
    """Deterministic interview type from experience + company."""
    if experience_level == "junior":
        return "technical_coding"
    if experience_level == "mid" and company_type == "startup":
        return "technical_coding"
    if experience_level == "mid":
        return "mixed"
    if experience_level == "senior" and company_type == "startup":
        return "technical_discussion"
    return "mixed"


# ---------------------------------------------------------------------------
# Resume probing rules
# ---------------------------------------------------------------------------
def should_probe_resume(experience_level: str, has_resume: bool) -> bool:
    """Resume probing is mandatory for live interviews when a resume exists."""
    return has_resume and experience_level != "junior"


# ---------------------------------------------------------------------------
# Skill prioritization rules
# ---------------------------------------------------------------------------
def skill_priority(skill: str, experience_level: str, company_type: str) -> str:
    """Assign priority deterministically from skill name and context."""
    core_backend = {"go", "golang", "python", "java", "rust", "c++", "sql", "postgresql"}
    core_frontend = {"react", "typescript", "javascript", "html", "css", "next.js"}
    core_infra = {"kubernetes", "docker", "aws", "gcp", "terraform", "ci/cd"}

    s = skill.lower()
    if s in core_backend or s in core_frontend:
        return "high"
    if s in core_infra and experience_level in ("mid", "senior"):
        return "high"
    if experience_level == "senior" and company_type == "mnc":
        return "medium"
    return "medium"


def min_skill_duration(skill_count: int, technical_minutes: int) -> int:
    """Distribute technical time across mandatory skills."""
    if skill_count == 0:
        return technical_minutes
    base = max(5, technical_minutes // max(skill_count, 3))
    return base


# ---------------------------------------------------------------------------
# Red / green flags (deterministic starter sets; LLM may extend)
# ---------------------------------------------------------------------------
BASE_RED_FLAGS = [
    "Cannot explain trade-offs of chosen technology",
    "Blames external factors without ownership",
    "No evidence of testing or code review discipline",
    "Cannot estimate scale or performance constraints",
]

BASE_GREEN_FLAGS = [
    "Explains why a decision was made, not just what",
    "Mentions monitoring, observability, or rollback strategy",
    "Asks clarifying questions before solving",
    "References concrete production incidents and learnings",
]


# ---------------------------------------------------------------------------
# Interviewer guidance (dos / donts) by experience level
# ---------------------------------------------------------------------------
def interviewer_guidance(experience_level: str, company_type: str) -> Dict[str, List[str]]:
    dos = [
        "Ask open-ended questions first, then drill down",
        "Let the candidate finish their thought before interrupting",
        "Ask for specific examples from past projects",
        "Keep track of time per phase",
    ]
    donts = [
        "Do not answer the question for the candidate",
        "Do not make assumptions about background from the resume",
        "Do not spend more than 20% of time on any single topic",
    ]
    if experience_level == "senior":
        dos.append("Challenge architectural decisions with scale or failure scenarios")
    if company_type == "startup":
        dos.append("Ask about speed vs quality trade-offs and ownership")
    if company_type == "mnc":
        dos.append("Ask about cross-team collaboration and process compliance")
    return {"dos": dos, "donts": donts}
