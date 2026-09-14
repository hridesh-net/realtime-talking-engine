"""The interview's expectation items: the granular rubric under the four competencies.

The four competencies themselves are fixed (`evaluation_agent.rubric`) and are
never a setting — they are the report's four cards and the rubric's four
weights on every interview. What varies per interview is the list of
:class:`ExpectationItem` grouped under them:

* **fixed** — one item per behaviour in ``DEFAULT_RUBRIC.criteria[].covers``,
  present on every interview with a deterministic id, and what the existing
  deterministic signals already measure. The manager may toggle one off; they
  may not reword it.
* **drafted** — job-grounded wording :class:`ExpectationsAgent` proposes at
  creation, the way role facts are drafted today.
* **custom** — the manager's own text, with the competency the model
  *suggested* and the manager may override.

This is `evaluation_agent/role_facts.py`'s discipline applied to a second
checklist: the model writes wording onto keys code owns, and anything it
returns that is not on the list is discarded. It cannot add a competency,
change a weight, or set ``enabled``.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from evaluation_agent.prompts import (
    EXPECTATIONS_CLASSIFY_PERSONA,
    EXPECTATIONS_DRAFT_PERSONA,
    build_expectations_classify_prompt,
    build_expectations_draft_prompt,
)
from evaluation_agent.rubric import DEFAULT_RUBRIC
from llm.base import StructuredModel
from llm.factory import build_model

#: The four competency ids, in report order. Derived from the rubric rather
#: than restated, so a retuned rubric cannot leave a second copy behind.
COMPETENCY_IDS: tuple[str, ...] = DEFAULT_RUBRIC.ids

#: Where an item the model could not place goes. Structured Interviewing is the
#: heaviest criterion and the one a stray behavioural expectation most often
#: belongs under; the manager can move it, and the blank reason is the signal
#: that nothing was actually decided.
DEFAULT_COMPETENCY_ID = "structure"

#: The three sources an item can have. ``fixed`` comes from the rubric,
#: ``drafted`` from the model, ``custom`` from the manager.
ITEM_SOURCES = ("fixed", "drafted", "custom")

#: How many custom items one interview may carry. A checklist longer than this
#: stops being a checklist; the wizard shows the limit rather than truncating.
MAX_CUSTOM_ITEMS = 12

#: The model may propose at most this many drafted items per competency.
MAX_DRAFTED_PER_COMPETENCY = 3

#: Longest item text. Long enough for a behaviour written as a sentence, short
#: enough that it renders in a scorecard strip.
MAX_ITEM_TEXT = 200

#: Longest classification reason. One line, shown beside the suggestion.
MAX_CLASSIFY_REASON = 200

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """A stable, readable id fragment for one rubric behaviour.

    Deterministic by construction: the same ``covers`` string always produces
    the same slug, so a fixed item's id survives a restart, a redeploy and a
    stored interview. `tests/test_expectations.py` pins the full set, which is
    what makes editing the rubric's wording a deliberate act rather than an
    accident that silently re-keys every stored interview.
    """
    return _NON_SLUG.sub("-", text.strip().lower()).strip("-")[:60].strip("-")


class ExpectationItem(BaseModel):
    """One behaviour the interviewer is expected to show, under one competency."""

    id: str = Field(..., min_length=1)
    competency_id: str = Field(..., description=f"One of: {', '.join(COMPETENCY_IDS)}.")
    text: str = Field(..., min_length=1, max_length=MAX_ITEM_TEXT)
    source: str = Field(..., pattern=f"^({'|'.join(ITEM_SOURCES)})$")
    enabled: bool = Field(
        True,
        description=(
            "The toggle the manager sees. A disabled item is still computed and "
            "stored; it stops counting toward its competency and stops rendering."
        ),
    )


class ExpectationClassification(BaseModel):
    """Which competency a custom item belongs under, and why.

    The suggestion only. The manager can override it, which is why an answer
    outside the four competencies degrades to
    :data:`DEFAULT_COMPETENCY_ID` with a blank reason rather than failing the
    request: losing the whole add-item interaction over a bad label is the
    worse failure, and a blank reason says plainly that nothing was decided.
    """

    competency_id: str = Field(..., description=f"One of: {', '.join(COMPETENCY_IDS)}.")
    reason: str = Field("", max_length=MAX_CLASSIFY_REASON)


def fixed_items() -> list[ExpectationItem]:
    """The rubric's own behaviours, one item each, in rubric order.

    Present on every interview. `POST /interviews` fills these in when the
    caller sends none and restores any the caller left out, so no interview can
    be created that is missing part of the instrument managers are compared on.
    """
    return [
        ExpectationItem(
            id=f"{criterion.id}.{_slug(covers)}",
            competency_id=criterion.id,
            text=covers,
            source="fixed",
            enabled=True,
        )
        for criterion in DEFAULT_RUBRIC.criteria
        for covers in criterion.covers
    ]


def fixed_text_by_id() -> dict[str, str]:
    """Fixed item id -> the rubric's wording, for validating what a caller sent."""
    return {item.id: item.text for item in fixed_items()}


_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competency_id": {"type": "string", "enum": list(COMPETENCY_IDS)},
                    "text": {"type": "string"},
                },
                "required": ["competency_id", "text"],
            },
        }
    },
    "required": ["items"],
}

_CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "competency_id": {"type": "string", "enum": list(COMPETENCY_IDS)},
        "reason": {"type": "string"},
    },
    "required": ["competency_id", "reason"],
}


class ExpectationsAgent:
    """Drafts expectation wording, and suggests where a custom item belongs.

    Two calls, neither of which stores anything and neither of which may move a
    wall: the competencies, the weights, the item limits and ``enabled`` are all
    code. What the model writes is the *text* of a job-grounded behaviour, and
    the *label* on one the manager typed.
    """

    #: Low: this is grounding, not invention. Warmth here produces expectations
    #: the job description does not support.
    DEFAULT_TEMPERATURE = 0.1

    def __init__(self, model: StructuredModel | None = None) -> None:
        self._model = model or build_model("expectations", self.DEFAULT_TEMPERATURE)

    @property
    def model(self) -> str:
        """Model id in use, for provenance."""
        return self._model.model_id

    async def draft(
        self,
        *,
        job_title: str,
        jd: str,
        skills_required: list[str],
        location: str = "",
    ) -> list[ExpectationItem]:
        """Propose job-grounded items, clamped onto the four fixed competencies."""
        draft = await self._model.generate_json(
            system=EXPECTATIONS_DRAFT_PERSONA,
            prompt=build_expectations_draft_prompt(
                job_title=job_title,
                jd=jd,
                skills_required=skills_required,
                location=location,
                competencies=[
                    {"id": c.id, "label": c.label, "covers": c.covers}
                    for c in DEFAULT_RUBRIC.criteria
                ],
                per_competency=MAX_DRAFTED_PER_COMPETENCY,
                max_chars=MAX_ITEM_TEXT,
            ),
            schema=_DRAFT_SCHEMA,
        )
        return self._build_drafted(draft)

    async def classify(self, *, text: str) -> ExpectationClassification:
        """Suggest the competency a manager's own item belongs under."""
        answer = await self._model.generate_json(
            system=EXPECTATIONS_CLASSIFY_PERSONA,
            prompt=build_expectations_classify_prompt(
                text=text,
                competencies=[
                    {"id": c.id, "label": c.label, "covers": c.covers}
                    for c in DEFAULT_RUBRIC.criteria
                ],
            ),
            schema=_CLASSIFY_SCHEMA,
        )
        return self._build_classification(answer)

    @staticmethod
    def _build_drafted(draft: dict[str, Any]) -> list[ExpectationItem]:
        """Clamp the model's answer onto the fixed competencies.

        Four clamps, each of which has a way to be wrong that this discards
        rather than passes on: a competency the rubric does not have, more items
        under one competency than the wizard will show, an essay in place of a
        behaviour, and a restatement of a fixed item the interview already
        carries.
        """
        # Seeded with the rubric's own wording, so a drafted item that merely
        # restates a fixed one never reaches the manager as a second toggle.
        # It also grows as items are accepted, which drops an exact repeat.
        seen = {item.text.strip().casefold() for item in fixed_items()}
        per_competency: dict[str, int] = dict.fromkeys(COMPETENCY_IDS, 0)
        items: list[ExpectationItem] = []
        for raw in draft.get("items", []):
            if not isinstance(raw, dict):
                continue
            competency_id = str(raw.get("competency_id", "")).strip().lower()
            if competency_id not in per_competency:
                continue
            if per_competency[competency_id] >= MAX_DRAFTED_PER_COMPETENCY:
                continue
            text = str(raw.get("text", "") or "").strip()[:MAX_ITEM_TEXT].strip()
            if not text or text.casefold() in seen:
                continue
            seen.add(text.casefold())
            per_competency[competency_id] += 1
            items.append(
                ExpectationItem(
                    id=f"drafted.{competency_id}.{per_competency[competency_id]}",
                    competency_id=competency_id,
                    text=text,
                    source="drafted",
                    enabled=True,
                )
            )
        return items

    @staticmethod
    def _build_classification(answer: dict[str, Any]) -> ExpectationClassification:
        """Keep the suggestion only when it names one of the four competencies."""
        competency_id = str(answer.get("competency_id", "")).strip().lower()
        if competency_id not in COMPETENCY_IDS:
            return ExpectationClassification(competency_id=DEFAULT_COMPETENCY_ID, reason="")
        reason = str(answer.get("reason", "") or "").strip()[:MAX_CLASSIFY_REASON]
        return ExpectationClassification(competency_id=competency_id, reason=reason)
