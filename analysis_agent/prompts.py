"""Prompt assembly. Loads the shipped instructions and frames the context.

No model call happens here, and none may: the architecture suite checks it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from analysis_agent.schema import AnalysisContext

INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "INSTRUCTIONS.md"


@lru_cache(maxsize=1)
def instructions() -> str:
    """The agent's operating instructions, as shipped.

    Read from the file rather than embedded in a string literal so the rules a
    report rests on are reviewable as a document, and so a change to them shows
    up in a diff as prose rather than as an edited f-string.
    """
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


def system_prompt() -> str:
    """What the model is, and the rules it works under."""
    return instructions()


def context_block(ctx: AnalysisContext) -> str:
    """The expectation this interview was held against, as JSON."""
    payload = {
        "role": {
            "job_title": ctx.job_title,
            "description": ctx.job_description,
            "skills_required": ctx.skills_required,
            "clarity_facts_the_manager_should_convey": ctx.clarity_facts,
            "configured_language": ctx.language_setting,
        },
        "candidate_persona": {
            "label": ctx.persona_label,
            "description": ctx.persona_description,
            "what_the_manager_has_to_do": ctx.interviewer_challenge,
            # The manager's job was to read and adapt to this person. Without
            # knowing who they were facing there is no way to tell adaptation
            # from luck, so the traits go in the brief rather than being
            # inferred from the audio.
            "traits_0_to_10": ctx.persona_traits,
            "speech_profile": ctx.persona_speech,
            "how_they_answer": ctx.persona_answer_policy,
            "competence_band_on_required_skills": ctx.persona_knowledge_band,
            "must_discover": ctx.must_discover,
            "scripted_beats": ctx.session_beats,
            "known_interviewer_failure_modes": ctx.interviewer_failure_modes,
        },
        "rubric_being_assessed": ctx.rubric,
    }
    if ctx.interview_expectation:
        # Framed as coverage context, never as scoring guidance: this document's
        # own criteria describe assessing the candidate, and the subject here is
        # the manager. Mislabelling it would invite the model to score the wrong
        # person.
        payload["what_this_interview_was_meant_to_cover"] = ctx.interview_expectation

    return json.dumps(payload, indent=2, ensure_ascii=False)


def window_prompt(
    ctx: AnalysisContext, *, index: int, count: int, offset_ms: int, total_ms: int
) -> str:
    """The user turn for one window, including where it sits in the recording."""
    header = (
        f"This is window {index + 1} of {count} from a recording "
        f"{total_ms / 1000:.0f} seconds long. This window starts at "
        f"{offset_ms / 1000:.0f}s of the full recording.\n\n"
        "Report every timestamp RELATIVE TO THE START OF THIS AUDIO, beginning "
        "at 0. Do not add the offset yourself — the system does that. Nothing "
        "you report may exceed the length of this window.\n\n"
        if count > 1
        else "This is the complete recording.\n\n"
    )
    return (
        header
        + "What this interview was held against:\n\n"
        + context_block(ctx)
        + "\n\nAnalyse the audio against it, following your instructions exactly."
    )
