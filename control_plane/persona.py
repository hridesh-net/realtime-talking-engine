"""Deterministic persona generation from BRD §4.3 / §5.2."""
from __future__ import annotations

import hashlib
import json
import random
from typing import List

from control_plane.schemas import CandidatePersona, PersonaAttribute

# BRD: persona template bounds are code-defined, not runtime-configurable.
ATTRIBUTE_BOUNDS = {
    "communication_style": {"min": 3, "max": 9},
    "technical_depth": {"min": 2, "max": 8},
    "confidence_level": {"min": 2, "max": 8},
    "nervousness_level": {"min": 1, "max": 7},
    "problem_approach": {"min": 3, "max": 9},
}

VARIANCE_POOL = {
    "communication_style": ["verbose", "concise", "structured", "rambling", "technical"],
    "technical_depth": ["surface", "medium", "deep", "overly-theoretical"],
    "confidence_level": ["overconfident", "balanced", "humble", "self-doubting"],
    "nervousness_level": ["calm", "slightly-nervous", "visibly-nervous", "panicky"],
    "problem_approach": ["methodical", "exploratory", "pragmatic", "academic"],
}

FIRST_NAMES = [
    "Alex", "Priya", "Jordan", "Sam", "Taylor", "Riley", "Maya", "Jamie",
    "Chris", "Lee", "Anika", "Rahul", "Sofia", "Marcus", "Elena", "Omar",
]
LAST_NAMES = [
    "Chen", "Patel", "Johnson", "Kim", "Garcia", "Smith", "Reddy", "Lee",
    "Brown", "Singh", "Muller", "Nguyen", "Taylor", "Ivanov", "Doe", "Rossi",
]
BACKGROUNDS = [
    "Backend engineer with {years} years building distributed systems",
    "Full-stack engineer with {years} years shipping web products",
    "SRE with {years} years running large-scale infrastructure",
    "Platform engineer with {years} years on internal developer tools",
    "Mobile engineer with {years} years of app performance work",
]


def _seed(requirement_id: str, interview_id: str, index: int) -> str:
    return f"{requirement_id}:{interview_id}:{index}"


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _fingerprint(persona: dict) -> str:
    return hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).hexdigest()


def generate_persona(
    requirement_id: str,
    interview_id: str,
    index: int = 0,
    seed_override: str | None = None,
) -> CandidatePersona:
    """Generate a deterministic CandidatePersona per BRD FR-002."""
    seed = seed_override or _seed(requirement_id, interview_id, index)
    rng = _rng(seed)

    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    years = rng.randint(2, 8)
    background = rng.choice(BACKGROUNDS).format(years=years)

    attributes: List[PersonaAttribute] = []
    for attr_name, bounds in ATTRIBUTE_BOUNDS.items():
        score = rng.randint(bounds["min"], bounds["max"])
        variance = rng.choice(VARIANCE_POOL[attr_name])
        attributes.append(
            PersonaAttribute(name=attr_name, score=score, variance=variance)
        )

    persona_dict = {
        "name": name,
        "background": background,
        "attributes": [a.model_dump() for a in attributes],
    }
    fingerprint = _fingerprint(persona_dict)

    return CandidatePersona(
        candidate_id=f"ai-{interview_id}-{index}",
        name=name,
        background=background,
        attributes=attributes,
        fingerprint=fingerprint,
    )
