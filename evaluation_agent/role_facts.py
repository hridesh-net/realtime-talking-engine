"""Draft the role-fact checklist statements for one job description."""

from __future__ import annotations

from typing import Any

from evaluation_agent.prompts import ROLE_FACTS_PERSONA, build_role_facts_prompt
from evaluation_agent.schema import CLARITY_FACT_KEYS, ClarityFact
from llm.base import StructuredModel
from llm.factory import build_model

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "statement": {"type": "string"},
                },
                "required": ["key", "statement"],
            },
        }
    },
    "required": ["facts"],
}


class RoleFactsAgent:
    """Turns a job description into statements for the fixed fact checklist.

    The checklist itself is `CLARITY_FACT_KEYS`, defined in code. This agent
    only writes the wording, and anything it returns for a key that is not on
    the list is discarded — so a hallucinated seventh fact cannot reach the
    report and quietly change what managers are measured against.
    """

    #: Low: this is extraction, not invention. Warmth here produces facts the
    #: job description does not contain.
    DEFAULT_TEMPERATURE = 0.1

    def __init__(self, model: StructuredModel | None = None) -> None:
        self._model = model or build_model("role_facts", self.DEFAULT_TEMPERATURE)

    @property
    def model(self) -> str:
        """Model id in use, for provenance."""
        return self._model.model_id

    async def extract(self, *, job_title: str, jd: str, location: str = "") -> list[ClarityFact]:
        """Draft one statement per fact key. Always returns every key, in order."""
        draft = await self._model.generate_json(
            system=ROLE_FACTS_PERSONA,
            prompt=build_role_facts_prompt(
                job_title=job_title, jd=jd, location=location, count=len(CLARITY_FACT_KEYS)
            ),
            schema=_SCHEMA,
        )
        return self._build(draft)

    @staticmethod
    def _build(draft: dict[str, Any]) -> list[ClarityFact]:
        """Clamp the model's answer onto the fixed checklist."""
        said = {
            str(f.get("key", "")).strip().lower(): str(f.get("statement", "") or "").strip()
            for f in draft.get("facts", [])
            if isinstance(f, dict)
        }
        # Every key, always, in catalog order — a missing key becomes an empty
        # fact rather than vanishing, so the UI shows the operator what was not
        # answered instead of silently shortening the checklist.
        return [ClarityFact(key=k, statement=said.get(k, "")[:300]) for k in CLARITY_FACT_KEYS]
