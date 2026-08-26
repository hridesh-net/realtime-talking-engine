"""The audio analysis agent.

One session's recording in, one `SessionAnalysis` out. It does not build a
report, does not persist anything, and does not decide a score — the report
engine composes from what this returns, and the numbers are computed there.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from analysis_agent import audio, harness, prompts
from analysis_agent.schema import ANALYSIS_INSTRUCTIONS_VERSION, AnalysisContext, SessionAnalysis
from llm.base import AudioModel, ModelError

#: Observation is extraction, not composition. Warmth here invents turns.
TEMPERATURE = 0.0

#: Windows are cut to WAV so each is a self-contained file the model can decode.
WINDOW_MIME = "audio/wav"


class AudioAnalysisAgent:
    """Analyses a recording against the expectation it was held against."""

    def __init__(self, model: AudioModel | None = None) -> None:
        self._model = model

    async def _analyze_window(
        self, window: audio.Window, context: AnalysisContext, count: int, total_ms: int
    ) -> dict[str, Any]:
        """One window, analysed on its own clock."""
        if self._model is None:  # pragma: no cover - guarded by the caller
            raise ModelError("AudioAnalysisAgent needs an AudioModel")
        return await self._model.analyze_audio(
            audio=window.data,
            mime_type=WINDOW_MIME,
            system=prompts.system_prompt(),
            prompt=prompts.window_prompt(
                context,
                index=window.index,
                count=count,
                offset_ms=window.offset_ms,
                total_ms=total_ms,
            ),
            schema=ANALYSIS_JSON_SCHEMA,
        )

    async def analyze(
        self,
        recording: Path,
        context: AnalysisContext,
        *,
        window_ms: int = audio.WINDOW_MS,
    ) -> SessionAnalysis:
        """Window the recording, analyse each window, and merge the answers.

        A window that fails is skipped rather than failing the session: a
        six-window interview with five good windows is worth reporting, and the
        harness records how many were lost.
        """
        if self._model is None:
            raise ModelError("AudioAnalysisAgent needs an AudioModel")

        windows = audio.cut(recording, window_ms=window_ms)
        if not windows:
            raise ModelError(f"no audio to analyse in {recording}")
        total_ms = (
            sum(w.duration_ms for w in windows[:1])
            if len(windows) == 1
            else audio.duration_ms(recording)
        )

        # Windows are independent, so they go out together: a twenty-minute
        # interview then costs about the same wall-clock as a five-minute one.
        results = await asyncio.gather(
            *(self._analyze_window(w, context, len(windows), total_ms) for w in windows),
            return_exceptions=True,
        )
        answers: list[tuple[int, int, dict[str, Any]]] = []
        failures = 0
        for window, result in zip(windows, results, strict=True):
            if isinstance(result, BaseException):
                failures += 1
                continue
            answers.append((window.offset_ms, window.duration_ms, result))

        if not answers:
            raise ModelError("every analysis window failed")

        analysis = harness.merge(
            answers,
            audio_duration_ms=total_ms,
            model_used=getattr(self._model, "model_id", ""),
        )
        analysis.instructions_version = ANALYSIS_INSTRUCTIONS_VERSION
        if failures:
            analysis.quality_notes = (
                f"{failures} of {len(windows)} windows could not be analysed. "
                + analysis.quality_notes
            ).strip()
        return analysis


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def _arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_NUM = {"type": "number"}
_CONF = {"type": "string", "enum": ["high", "medium", "low"]}

#: The shape the model must answer in. Kept beside the agent because it and the
#: prompt are one contract - a field added here without a rule in
#: INSTRUCTIONS.md is a field the model has no instruction for.
ANALYSIS_JSON_SCHEMA: dict[str, Any] = _obj(
    {
        "spoken_languages": _arr(_STR),
        "quality_notes": _STR,
        "transcript": _arr(
            _obj(
                {
                    "start_ms": _INT,
                    "end_ms": _INT,
                    "speaker": {"type": "string", "enum": ["manager", "candidate"]},
                    "text": _STR,
                    "text_en": _STR,
                    "confidence": _CONF,
                },
                ["start_ms", "end_ms", "speaker", "text", "text_en", "confidence"],
            )
        ),
        "questions": _arr(
            _obj(
                {
                    "at_ms": _INT,
                    "text": _STR,
                    "text_en": _STR,
                    "type": {
                        "type": "string",
                        "enum": [
                            "leading",
                            "double_barrelled",
                            "behavioural",
                            "situational",
                            "closed",
                            "open",
                        ],
                    },
                    "is_probe": _BOOL,
                    "targets_skill": _STR,
                    "clarity": _INT,
                    "confidence": _CONF,
                },
                ["at_ms", "text", "text_en", "type", "is_probe", "clarity", "confidence"],
            )
        ),
        "topic_flags": _arr(
            _obj(
                {
                    "at_ms": _INT,
                    "category": _STR,
                    "raised_by": {"type": "string", "enum": ["manager", "candidate"]},
                    "pursued_by_manager": _BOOL,
                    "quote": _STR,
                    "quote_en": _STR,
                    "why": _STR,
                    "confidence": _CONF,
                },
                [
                    "at_ms",
                    "category",
                    "raised_by",
                    "pursued_by_manager",
                    "quote",
                    "why",
                    "confidence",
                ],
            )
        ),
        "silences": _arr(
            _obj(
                {
                    "at_ms": _INT,
                    "seconds": _NUM,
                    "broken_by": {"type": "string", "enum": ["manager", "candidate", "nobody"]},
                },
                ["at_ms", "seconds", "broken_by"],
            )
        ),
        "interruptions": _arr(
            _obj(
                {
                    "at_ms": _INT,
                    "quote": _STR,
                    "candidate_cut_short": _BOOL,
                    "confidence": _CONF,
                },
                ["at_ms", "candidate_cut_short", "confidence"],
            )
        ),
        "discovery": _arr(
            _obj(
                {
                    "id": _STR,
                    "status": {
                        "type": "string",
                        "enum": ["surfaced", "not_surfaced", "volunteered", "unclear"],
                    },
                    "is_restraint_item": _BOOL,
                    "at_ms": _INT,
                    "evidence": _STR,
                    "confidence": _CONF,
                },
                ["id", "status", "is_restraint_item", "at_ms", "evidence", "confidence"],
            )
        ),
        "delivery": _obj(
            {
                "question_clarity": _INT,
                "explanation_quality": _INT,
                "tone_trajectory": _STR,
                "pace_note": _STR,
                "confidence": _CONF,
            },
            [
                "question_clarity",
                "explanation_quality",
                "tone_trajectory",
                "pace_note",
                "confidence",
            ],
        ),
        "persona_response": _obj(
            {
                "read_the_candidate": _INT,
                "adapted_approach": _INT,
                "handled_the_hard_moment": _INT,
                "rating": _INT,
                "reasoning": _STR,
                "misread_signals": _arr(_STR),
                "evidence_at_ms": _arr(_INT),
                "confidence": _CONF,
            },
            [
                "read_the_candidate",
                "adapted_approach",
                "handled_the_hard_moment",
                "rating",
                "reasoning",
                "evidence_at_ms",
                "confidence",
            ],
        ),
        "expectation_coverage": _obj(
            {
                "rating": _INT,
                "reachable_items": _INT,
                "covered_items": _INT,
                "reasoning": _STR,
                "unreachable_because": _STR,
                "confidence": _CONF,
            },
            ["rating", "reachable_items", "covered_items", "reasoning", "confidence"],
        ),
        "early_end": _obj(
            {
                "ended_early": _BOOL,
                "at_ms": _INT,
                "evidence_before_deciding": _INT,
                "closed_civilly": _BOOL,
                "justified": _BOOL,
                "reasoning": _STR,
                "confidence": _CONF,
            },
            [
                "ended_early",
                "evidence_before_deciding",
                "closed_civilly",
                "justified",
                "confidence",
            ],
        ),
        "criteria": _arr(
            _obj(
                {
                    "id": _STR,
                    "rating": _INT,
                    "reasoning": _STR,
                    "evidence_at_ms": _arr(_INT),
                    "confidence": _CONF,
                },
                ["id", "rating", "reasoning", "evidence_at_ms", "confidence"],
            )
        ),
    },
    [
        "spoken_languages",
        "transcript",
        "questions",
        "topic_flags",
        "silences",
        "interruptions",
        "discovery",
        "delivery",
        "persona_response",
        "expectation_coverage",
        "early_end",
        "criteria",
    ],
)
