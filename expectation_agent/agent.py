"""Interview Expectation Agent.

One agent instance per model backend. Generates deterministic, schema-valid
expectation documents from an interview job spec.
"""

from __future__ import annotations

import json
from typing import Any

from expectation_agent.prompts import (
    PERSONA,
    SYSTEM_GUARDRAILS,
    build_user_prompt,
)
from expectation_agent.rubric import (
    BASE_GREEN_FLAGS,
    BASE_RED_FLAGS,
    EVALUATION_CRITERIA,
    determine_interview_type,
    interviewer_guidance,
    phase_durations,
    should_probe_resume,
)
from expectation_agent.schema import (
    EXPECTATION_JSON_SCHEMA,
    InterviewExpectation,
)
from llm.base import StructuredModel
from llm.factory import build_model


class InterviewExpectationAgent:
    """Generates interview expectations from a job spec."""

    #: Low temperature: the expectation document must be stable across runs.
    DEFAULT_TEMPERATURE = 0.1

    def __init__(self, model: StructuredModel | None = None) -> None:
        # Injected for tests and for swapping providers; built from config
        # otherwise. This agent never imports a vendor SDK.
        self._model = model or build_model("expectation", self.DEFAULT_TEMPERATURE)

    @property
    def model(self) -> str:
        """Model ID recorded against generated expectations."""
        return self._model.model_id

    async def generate(
        self,
        interview_id: str,
        job_title: str,
        jd: str,
        skills_required: list[str],
        job_location_type: str,
        experience_level: str,
        company_type: str,
        duration_minutes: int,
        mode: str = "live_interview",
        has_resume: bool = True,
    ) -> InterviewExpectation:
        """Generate one expectation document. Deterministic given same inputs."""
        # ---- Deterministic pre-computation (LLM cannot override these) ----
        interview_type = determine_interview_type(experience_level, company_type)
        phases = phase_durations(experience_level, duration_minutes)
        criteria = EVALUATION_CRITERIA
        red_flags = BASE_RED_FLAGS
        green_flags = BASE_GREEN_FLAGS
        resume_required = should_probe_resume(experience_level, has_resume)

        user_prompt = build_user_prompt(
            job_title=job_title,
            jd=jd,
            skills_required=skills_required,
            job_location_type=job_location_type,
            experience_level=experience_level,
            company_type=company_type,
            duration_minutes=duration_minutes,
            interview_type=interview_type,
            mode=mode,
            criteria_json=json.dumps(criteria, indent=2),
            red_flags_json=json.dumps(red_flags, indent=2),
            green_flags_json=json.dumps(green_flags, indent=2),
            phases_json=json.dumps(
                [
                    {"name": "introduction", "duration_minutes": phases[0], "mandatory": True},
                    {
                        "name": "technical_deep_dive",
                        "duration_minutes": phases[1],
                        "mandatory": True,
                    },
                    {
                        "name": "candidate_questions",
                        "duration_minutes": phases[2],
                        "mandatory": True,
                    },
                    {"name": "closing", "duration_minutes": phases[3], "mandatory": True},
                ],
                indent=2,
            ),
        )

        raw = await self._call_model(user_prompt)

        # Post-process: enforce deterministic fields the model cannot override
        raw["interview_id"] = interview_id
        raw["interview_type"] = interview_type
        raw["evaluation_criteria"] = criteria
        raw["red_flags"] = red_flags + [f for f in raw.get("red_flags", []) if f not in red_flags]
        raw["green_flags"] = green_flags + [
            f for f in raw.get("green_flags", []) if f not in green_flags
        ]
        raw["resume_probing"]["required"] = resume_required
        raw["interviewer_guidance"] = interviewer_guidance(experience_level, company_type)

        # Validate structure durations
        total = sum(p["duration_minutes"] for p in raw.get("structure", []))
        if total != duration_minutes:
            raw["structure"] = [
                {
                    "name": "introduction",
                    "duration_minutes": phases[0],
                    "mandatory": True,
                    "guidance": "Build rapport and set expectations.",
                },
                {
                    "name": "technical_deep_dive",
                    "duration_minutes": phases[1],
                    "mandatory": True,
                    "guidance": "Cover mandatory skills with live exercises or scenarios.",
                },
                {
                    "name": "candidate_questions",
                    "duration_minutes": phases[2],
                    "mandatory": True,
                    "guidance": "Answer candidate questions and assess engagement.",
                },
                {
                    "name": "closing",
                    "duration_minutes": phases[3],
                    "mandatory": True,
                    "guidance": "Summarize next steps and thank the candidate.",
                },
            ]

        expectation = InterviewExpectation.model_validate(raw)
        expectation.raw_model_output = raw
        return expectation

    async def _call_model(self, prompt: str) -> dict[str, Any]:
        """Delegate to the injected provider."""
        return await self._model.generate_json(
            system=f"{PERSONA}\n\n{SYSTEM_GUARDRAILS}",
            prompt=prompt,
            schema=EXPECTATION_JSON_SCHEMA,
        )
