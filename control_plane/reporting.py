"""Assemble a report-engine bundle from stored rows, and generate the report.

`report_engine` is standalone by design - it imports no first-party package and
reads no database, so the rubric and the persona travel in its input. This
module is the seam that does the importing: it reads the interview, the session
and the catalog, hands the engine one bundle, and hands the result back.

Nothing here scores anything. Every number in the returned report is the
engine's, computed from the bundle this module built.
"""

from __future__ import annotations

from typing import Any

from analysis_agent import AnalysisContext
from candidate_agent import archetypes
from candidate_agent.schema import VirtualCandidate
from control_plane.schemas import InterviewResponse, SessionResponse
from evaluation_agent.rubric import DEFAULT_RUBRIC
from report_engine.schema import SessionBundle
from report_engine.score import build_report

#: Role families the competency pack knows about. The job card in the pivot plan
#: carries `role_family` as a field; today's interview record does not, so it is
#: derived from the job title. Deterministic, and the report prints which family
#: it scored against so a wrong guess is visible rather than silent.
_FAMILY_CUES: dict[str, tuple[str, ...]] = {
    "technical": ("engineer", "technician", "network", "field", "tower", "fibre", "fiber"),
    "operations": ("operations", "ops", "coordinator", "roster", "scheduler", "support"),
}
DEFAULT_ROLE_FAMILY = "sales"


def role_family_for(job_title: str) -> str:
    """The competency list this role should be scored against."""
    lowered = job_title.lower()
    for family, cues in _FAMILY_CUES.items():
        if any(cue in lowered for cue in cues):
            return family
    return DEFAULT_ROLE_FAMILY


def persona_block(session: SessionResponse, candidate: VirtualCandidate | None) -> dict[str, Any]:
    """The persona ground truth: what this candidate was hiding, and at what weight.

    Two shapes reach here and both carry it. A **catalog archetype** owns its
    `must_discover` in code, along with the scripted beats and the stress map. A
    **composed persona** has no catalog entry at all - its key is a `dyn-` hash -
    but the casting agent wrote the same scorecard onto the candidate, so the
    fixed denominator survives composition.

    When neither is available the block is empty rather than guessed, and the
    engine reports the persona-grounded signals as unmeasurable.
    """
    if session.persona_key in archetypes.ARCHETYPES:
        archetype = archetypes.get(session.persona_key)
        return {
            "archetype_key": archetype.key,
            "label": archetype.label,
            "must_discover": [
                {
                    "id": s.id,
                    "signal": s.signal,
                    "weight": s.weight,
                    "how_to_surface": s.how_to_surface,
                }
                for s in archetype.must_discover
            ],
            "session_beats": list(archetype.session_beats),
            "stresses": dict(archetype.stresses),
        }

    if candidate is not None:
        scorecard = candidate.interviewer_scorecard
        return {
            "archetype_key": session.persona_key,
            "label": candidate.archetype_label or session.persona_key,
            "must_discover": [
                {
                    "id": s.id,
                    "signal": s.signal,
                    "weight": s.weight,
                    "how_to_surface": s.how_to_surface,
                }
                for s in scorecard.must_discover
            ],
            # A composed persona has no scripted beats and no stress map: it was
            # assembled from trait presets, not written to stress a criterion.
            "session_beats": [],
            "stresses": {},
        }

    return {
        "archetype_key": session.persona_key,
        "label": session.persona_key,
        "must_discover": [],
        "session_beats": [],
        "stresses": {},
    }


def build_bundle(
    interview: InterviewResponse,
    session: SessionResponse,
    candidate: VirtualCandidate | None = None,
    analysis: dict[str, Any] | None = None,
    *,
    jurisdiction: str = "IN",
    english_weight: float | None = None,
    language_gate: bool = True,
    report_config: dict[str, Any] | None = None,
) -> SessionBundle:
    """Everything the engine needs for one session, as one validated object."""
    return SessionBundle.model_validate(
        {
            "session": {
                "session_id": session.id,
                "manager_id": "",
                "manager_name": interview.job_title,
                "modality": session.modality,
                "planned_minutes": session.planned_minutes,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
            },
            "job_card": {
                "job_title": interview.job_title,
                "summary": interview.jd,
                "role_family": role_family_for(interview.job_title),
                "clarity_facts": [
                    {"key": f.key, "statement": f.statement} for f in interview.clarity_facts
                ],
            },
            "persona": persona_block(session, candidate),
            "turns": [
                {
                    "index": t.index,
                    "speaker": t.speaker,
                    "text": t.text,
                    "elapsed_ms": t.elapsed_ms,
                }
                for t in session.turns
            ],
            "rubric": DEFAULT_RUBRIC.model_dump(),
            "jurisdiction": jurisdiction,
            "recording": (
                {
                    "path": "",
                    "channel_layout": session.recording.channel_layout,
                    "status": session.recording.status,
                }
                if session.recording
                else None
            ),
            "analysis": analysis,
            "report_config": report_config or {},
            "scoring_options": {
                "english_weight": english_weight,
                "language_gate": language_gate,
            },
        }
    )


def generate(
    interview: InterviewResponse,
    session: SessionResponse,
    candidate: VirtualCandidate | None = None,
    analysis: dict[str, Any] | None = None,
    *,
    jurisdiction: str = "IN",
    english_weight: float | None = None,
    language_gate: bool = True,
    report_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the bundle, run the engine, and return the report as plain JSON."""
    bundle = build_bundle(
        interview,
        session,
        candidate,
        analysis,
        jurisdiction=jurisdiction,
        english_weight=english_weight,
        language_gate=language_gate,
        report_config=report_config,
    )
    report = build_report(bundle)
    dumped: dict[str, Any] = report.model_dump(mode="json")
    return dumped


def build_analysis_context(
    interview: InterviewResponse,
    session: SessionResponse,
    candidate: VirtualCandidate | None = None,
    expectation: dict[str, Any] | None = None,
) -> AnalysisContext:
    """The brief the analysis agent works from.

    Assembled from what already exists rather than generated: the job card, the
    rubric, and — the part that carries most of the weight — *who the manager
    was actually facing*. Adaptation cannot be assessed without the persona's
    traits, speech profile and answer policy, so those go in the brief rather
    than being inferred from the audio.
    """
    persona = persona_block(session, candidate)
    archetype = (
        archetypes.get(session.persona_key)
        if session.persona_key in archetypes.ARCHETYPES
        else None
    )
    return AnalysisContext(
        job_title=interview.job_title,
        job_description=interview.jd,
        skills_required=list(interview.skills_required),
        clarity_facts=[
            {"key": f.key, "statement": f.statement}
            for f in interview.clarity_facts
            if f.statement.strip()
        ],
        language_setting=getattr(interview, "language", ""),
        persona_label=persona["label"],
        persona_description=archetype.description if archetype else "",
        interviewer_challenge=archetype.interviewer_challenge if archetype else "",
        persona_traits=archetype.trait_bounds_json if archetype else {},
        persona_speech=dict(archetype.speech) if archetype else {},
        persona_answer_policy=dict(archetype.answer_policy) if archetype else {},
        persona_knowledge_band=list(archetype.knowledge_band) if archetype else [],
        must_discover=persona["must_discover"],
        session_beats=persona["session_beats"],
        interviewer_failure_modes=(list(archetype.interviewer_failure_modes) if archetype else []),
        rubric=[
            {"id": c.id, "label": c.label, "weight": c.weight, "covers": c.covers}
            for c in DEFAULT_RUBRIC.criteria
        ],
        interview_expectation=expectation,
    )
