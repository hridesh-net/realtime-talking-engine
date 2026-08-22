"""Public models for the evaluation layer."""

from __future__ import annotations

from pydantic import BaseModel, Field

#: The role facts a manager is expected to convey, in the order the report lists
#: them. **Fixed in code on purpose.** The report compares managers to each
#: other, so the checklist cannot vary per interview or the scores stop being
#: comparable — the same reason the trait axes are fixed in `candidate_agent`.
#: What varies per interview is the *statement* of each fact, not which facts
#: are on the list.
CLARITY_FACT_KEYS: tuple[str, ...] = (
    "targets",
    "shifts",
    "location",
    "comp_band",
    "growth_path",
    "next_steps",
)

CLARITY_FACT_LABELS: dict[str, str] = {
    "targets": "Targets",
    "shifts": "Shifts",
    "location": "Location",
    "comp_band": "Compensation",
    "growth_path": "Growth path",
    "next_steps": "Next steps",
}


class ClarityFact(BaseModel):
    """One fact about the role the manager is expected to convey.

    The report counts how many were actually said — the spec's "4 of 5 role
    facts conveyed". A fact with an empty ``statement`` is not on this
    interview's checklist and is neither counted nor scored against.
    """

    key: str = Field(..., description=f"One of: {', '.join(CLARITY_FACT_KEYS)}.")
    statement: str = Field(
        "",
        max_length=300,
        description="The fact in this interview's terms. Empty means 'not applicable here'.",
    )

    @property
    def label(self) -> str:
        """Human label for the report and the picker."""
        return CLARITY_FACT_LABELS.get(self.key, self.key.replace("_", " ").title())
