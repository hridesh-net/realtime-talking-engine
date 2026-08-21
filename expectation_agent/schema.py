"""Fixed, deterministic schema for interview expectations.

Versioned so expectations remain backward-compatible across model updates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InterviewPhase(BaseModel):
    name: str
    duration_minutes: int
    mandatory: bool
    guidance: str


class SkillExpectation(BaseModel):
    skill: str
    priority: str = Field(..., pattern="^(high|medium|low)$")
    min_duration_minutes: int
    assessment_method: str = Field(..., pattern="^(live_coding|discussion|scenario|review)$")
    evidence_to_look_for: str


class ResumeProbing(BaseModel):
    required: bool
    focus_areas: List[str]
    sample_questions: List[str]


class BehavioralAssessment(BaseModel):
    required: bool
    focus_areas: List[str]
    sample_questions: List[str]


class EvaluationCriterion(BaseModel):
    name: str
    weight: float
    description: str


class InterviewerGuidance(BaseModel):
    dos: List[str]
    donts: List[str]


class InterviewExpectation(BaseModel):
    """The deterministic expectation document for one interview."""

    expectation_version: str = "v1.0"
    interview_id: str
    interview_type: str = Field(..., pattern="^(technical_coding|technical_discussion|behavioral|mixed)$")

    structure: List[InterviewPhase]
    mandatory_skills: List[SkillExpectation]
    optional_skills: List[SkillExpectation] = Field(default_factory=list)

    resume_probing: ResumeProbing
    behavioral_assessment: BehavioralAssessment

    red_flags: List[str]
    green_flags: List[str]
    evaluation_criteria: List[EvaluationCriterion]
    interviewer_guidance: InterviewerGuidance

    raw_model_output: Optional[Dict[str, Any]] = None


# JSON Schema for Gemini/OpenAI structured output
EXPECTATION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "expectation_version": {"type": "string", "const": "v1.0"},
        "interview_id": {"type": "string"},
        "interview_type": {
            "type": "string",
            "enum": ["technical_coding", "technical_discussion", "behavioral", "mixed"],
        },
        "structure": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "mandatory": {"type": "boolean"},
                    "guidance": {"type": "string"},
                },
                "required": ["name", "duration_minutes", "mandatory", "guidance"],
            },
        },
        "mandatory_skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "min_duration_minutes": {"type": "integer"},
                    "assessment_method": {
                        "type": "string",
                        "enum": ["live_coding", "discussion", "scenario", "review"],
                    },
                    "evidence_to_look_for": {"type": "string"},
                },
                "required": [
                    "skill",
                    "priority",
                    "min_duration_minutes",
                    "assessment_method",
                    "evidence_to_look_for",
                ],
            },
        },
        "optional_skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "min_duration_minutes": {"type": "integer"},
                    "assessment_method": {
                        "type": "string",
                        "enum": ["live_coding", "discussion", "scenario", "review"],
                    },
                    "evidence_to_look_for": {"type": "string"},
                },
                "required": [
                    "skill",
                    "priority",
                    "min_duration_minutes",
                    "assessment_method",
                    "evidence_to_look_for",
                ],
            },
        },
        "resume_probing": {
            "type": "object",
            "properties": {
                "required": {"type": "boolean"},
                "focus_areas": {"type": "array", "items": {"type": "string"}},
                "sample_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["required", "focus_areas", "sample_questions"],
        },
        "behavioral_assessment": {
            "type": "object",
            "properties": {
                "required": {"type": "boolean"},
                "focus_areas": {"type": "array", "items": {"type": "string"}},
                "sample_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["required", "focus_areas", "sample_questions"],
        },
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "green_flags": {"type": "array", "items": {"type": "string"}},
        "evaluation_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "weight": {"type": "number"},
                    "description": {"type": "string"},
                },
                "required": ["name", "weight", "description"],
            },
        },
        "interviewer_guidance": {
            "type": "object",
            "properties": {
                "dos": {"type": "array", "items": {"type": "string"}},
                "donts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dos", "donts"],
        },
    },
    "required": [
        "expectation_version",
        "interview_id",
        "interview_type",
        "structure",
        "mandatory_skills",
        "resume_probing",
        "behavioral_assessment",
        "red_flags",
        "green_flags",
        "evaluation_criteria",
        "interviewer_guidance",
    ],
}
