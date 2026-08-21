"""Interview Expectation Agent.

One agent instance per model backend. Generates deterministic, schema-valid
expectation documents from an interview job spec.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

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


class InterviewExpectationAgent:
    """Generates interview expectations using Gemini (or OpenAI fallback)."""

    #: Model IDs are config, never hardcoded — override with EXPECTATION_MODEL.
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, model: str | None = None, temperature: float = 0.1):
        self.model = model or os.getenv("EXPECTATION_MODEL") or self.DEFAULT_MODEL
        self.temperature = temperature
        self._client = None
        self._backend = None
        self._init_backend()

    def _init_backend(self) -> None:
        """Backend follows EXPECTATION_PROVIDER when set, else the key that exists."""
        provider = (os.getenv("EXPECTATION_PROVIDER") or "").strip().lower()
        if provider == "openai" and os.getenv("OPENAI_API_KEY"):
            import openai

            self._client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self._backend = "openai"
            return
        if os.getenv("GEMINI_API_KEY"):
            from google import genai

            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            self._backend = "gemini"
            return
        if os.getenv("OPENAI_API_KEY"):
            import openai

            self._client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self._backend = "openai"
            return
        raise ValueError("Set GEMINI_API_KEY or OPENAI_API_KEY")

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
                    {"name": "technical_deep_dive", "duration_minutes": phases[1], "mandatory": True},
                    {"name": "candidate_questions", "duration_minutes": phases[2], "mandatory": True},
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
        raw["green_flags"] = green_flags + [f for f in raw.get("green_flags", []) if f not in green_flags]
        raw["resume_probing"]["required"] = resume_required
        raw["interviewer_guidance"] = interviewer_guidance(experience_level, company_type)

        # Validate structure durations
        total = sum(p["duration_minutes"] for p in raw.get("structure", []))
        if total != duration_minutes:
            raw["structure"] = [
                {"name": "introduction", "duration_minutes": phases[0], "mandatory": True, "guidance": "Build rapport and set expectations."},
                {"name": "technical_deep_dive", "duration_minutes": phases[1], "mandatory": True, "guidance": "Cover mandatory skills with live exercises or scenarios."},
                {"name": "candidate_questions", "duration_minutes": phases[2], "mandatory": True, "guidance": "Answer candidate questions and assess engagement."},
                {"name": "closing", "duration_minutes": phases[3], "mandatory": True, "guidance": "Summarize next steps and thank the candidate."},
            ]

        expectation = InterviewExpectation.model_validate(raw)
        expectation.raw_model_output = raw
        return expectation

    async def _call_model(self, prompt: str) -> Dict[str, Any]:
        """Call the configured backend with structured output."""
        if self._backend == "gemini":
            return await self._call_gemini(prompt)
        if self._backend == "openai":
            return await self._call_openai(prompt)
        raise RuntimeError("no backend configured")

    async def _call_gemini(self, prompt: str) -> Dict[str, Any]:
        from google.genai import types

        full_prompt = f"{PERSONA}\n\n{SYSTEM_GUARDRAILS}\n\n{prompt}"
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=EXPECTATION_JSON_SCHEMA,
        )
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=full_prompt,
            config=config,
        )
        text = response.text or "{}"
        return json.loads(text)

    async def _call_openai(self, prompt: str) -> Dict[str, Any]:
        full_prompt = f"{PERSONA}\n\n{SYSTEM_GUARDRAILS}\n\n{prompt}"
        response = await self._client.chat.completions.acreate(
            model=self.model,
            messages=[
                {"role": "system", "content": PERSONA + "\n\n" + SYSTEM_GUARDRAILS},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or "{}"
        return json.loads(text)
