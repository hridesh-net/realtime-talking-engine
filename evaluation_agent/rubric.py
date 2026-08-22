"""The fixed manager rubric: criteria, weights and bands.

**Org-owned configuration, not generated content.** The rubric must be identical
across every session or manager scores stop being comparable, which is the whole
point of the report. It is therefore code with an optional file override, never
something a model authors per interview.

The defaults are the four criteria and weights from the training-wizard
specification. `load_rubric` reads a JSON override so the weights can be retuned
— or the criteria expanded back to the BRD's five — without touching the judge,
the signals, or the report layout.

**No criterion is a critical-fail gate.** Nothing here caps, fails or overrides a
score: the report is an analytical estimate. A bias incident raises a flag that
the session row and the cohort count read; it does not move a number.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class Criterion(BaseModel):
    """One scored manager competency."""

    id: str
    label: str
    weight: float = Field(..., gt=0.0, le=1.0)
    #: What the report lists under this heading. Shown to the manager verbatim.
    covers: list[str] = Field(default_factory=list)


class Band(BaseModel):
    """A readiness band. `floor` is inclusive; the highest matching band wins."""

    label: str
    floor: int = Field(..., ge=0, le=100)


class Rubric(BaseModel):
    """The complete scoring instrument."""

    version: str
    criteria: list[Criterion]
    bands: list[Band]

    @property
    def ids(self) -> tuple[str, ...]:
        """Criterion ids, in report order."""
        return tuple(c.id for c in self.criteria)

    def band_for(self, readiness: int) -> str:
        """The band a 0-100 readiness index falls in."""
        for band in sorted(self.bands, key=lambda b: b.floor, reverse=True):
            if readiness >= band.floor:
                return band.label
        return self.bands[0].label if self.bands else "unbanded"


RUBRIC_VERSION = "v1.0"

#: The specification's four categories. Weights sum to 1.0, checked on load.
DEFAULT_RUBRIC = Rubric(
    version=RUBRIC_VERSION,
    criteria=[
        Criterion(
            id="clarity",
            label="Hiring with Clarity",
            weight=0.25,
            covers=[
                "Explains the role beyond the JD",
                "Answers the candidate's questions",
                "States compensation and shift facts honestly",
                "Closes with next steps and timeline",
            ],
        ),
        Criterion(
            id="structure",
            label="Structured Interviewing",
            weight=0.30,
            covers=[
                "Relevant, role-based questions",
                "Open vs closed question balance",
                "Behavioural (STAR) questions",
                "Probes vague answers and inflated claims",
                "Covers the skills that matter",
            ],
        ),
        Criterion(
            id="fairness",
            label="Fair & Inclusive",
            weight=0.25,
            covers=[
                "No questions on protected topics",
                "No stereotyped or assumption-loaded framing",
                "Handles a volunteered personal detail correctly",
                "Routes accommodation requests to policy",
            ],
        ),
        Criterion(
            id="communication",
            label="Communication & Presence",
            weight=0.20,
            covers=[
                "Warm, professional tone of language",
                "Clear single questions, no compounds",
                "Sensible talk-to-listen ratio, few interruptions",
                "Welcome, greeting and agenda",
                "Composure under provocation",
                "Encourages an under-confident candidate",
            ],
        ),
    ],
    bands=[
        Band(label="Needs practice", floor=0),
        Band(label="Developing", floor=45),
        Band(label="Competent", floor=65),
    ],
)


def load_rubric(path: str | Path | None = None) -> Rubric:
    """Load the rubric, falling back to the built-in default.

    The caller resolves the path — this package never reads the environment,
    the same rule the model adapters follow for API keys.
    """
    if not path:
        return DEFAULT_RUBRIC
    rubric = Rubric.model_validate(json.loads(Path(path).read_text()))
    total = round(sum(c.weight for c in rubric.criteria), 4)
    if total != 1.0:
        raise ValueError(f"rubric weights sum to {total}, expected 1.0")
    if len({c.id for c in rubric.criteria}) != len(rubric.criteria):
        raise ValueError("rubric has duplicate criterion ids")
    return rubric
