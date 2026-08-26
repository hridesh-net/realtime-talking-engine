"""Signals derived from the audio analysis — spec section 6, the assessed half.

These are not counted from the transcript; they come from a model reading the
recording. That is a real difference in standing, so every signal here is marked
`source="assessed"` and the report shows the two halves apart.

Code still owns every number. The analysis supplies ratings and observations;
the arithmetic that turns them into sub-scores happens here, and an anchor the
harness already rejected never reaches this module.
"""

from __future__ import annotations

from typing import Any

from report_engine import transfer
from report_engine.schema import AnalysisInput, Evidence, SignalResult

#: The analysis weighs handling *this candidate* above working through the plan
#: (60/40, applied in `analysis_agent`). The report carries that through rather
#: than re-deciding it, so one number does not contradict the other.
PERSONA_WEIGHT = 3.0
COVERAGE_WEIGHT = 2.0


def extract(analysis: AnalysisInput | None) -> list[SignalResult]:
    """Assessed signals, or an empty list when no analysis has been run."""
    if analysis is None:
        return []
    return [
        _persona_response(analysis),
        _early_end(analysis),
        _expectation_coverage(analysis),
        _flagged_topics(analysis),
        _question_clarity(analysis),
        _explanation_quality(analysis),
    ]


def _base(signal_id: str, label: str, criterion: str, weight: float, basis: str) -> SignalResult:
    return SignalResult(
        id=signal_id,
        label=label,
        criterion=criterion,
        weight=weight,
        basis=basis,
        source="assessed",
    )


def _anchors(analysis: AnalysisInput, at: list[int], quote: str = "") -> list[Evidence]:
    """Turn analysis timestamps into report evidence."""
    out: list[Evidence] = []
    for ms in at[:3]:
        text = quote or _text_at(analysis, ms)
        out.append(Evidence(turn_index=-1, at_ms=int(ms), speaker="manager", quote=text[:400]))
    return out


def _text_at(analysis: AnalysisInput, ms: int) -> str:
    """The transcribed turn covering a timestamp, so an anchor reads as a quote."""
    for turn in analysis.transcript:
        if int(turn.get("start_ms", 0)) <= ms <= int(turn.get("end_ms", 0)):
            return str(turn.get("text_en") or turn.get("text") or "")
    return ""


def _rating(block: dict[str, Any], key: str = "rating", default: int = 0) -> int:
    try:
        return int(block.get(key, default))
    except (TypeError, ValueError):
        return default


def _persona_response(analysis: AnalysisInput) -> SignalResult:
    """Did the manager read this candidate and adapt to them?"""
    out = _base(
        "persona_response",
        "Handled this candidate",
        "structure",
        PERSONA_WEIGHT,
        "ASSESSED from the recording against the persona's traits and answer "
        "policy. The dominant half of the analysis: adapting to the person in "
        "front of you is harder and worth more than working through a plan",
    )
    block = analysis.persona_response
    if not block:
        out.reason = "no analysis has been run for this session"
        return out
    rating = _rating(block)
    out.value = float(rating)
    parts = [
        f"read {_rating(block, 'read_the_candidate')}",
        f"adapted {_rating(block, 'adapted_approach')}",
        f"hard moment {_rating(block, 'handled_the_hard_moment')}",
    ]
    out.display = f"{rating}/10 — " + ", ".join(parts)
    misread = block.get("misread_signals") or []
    if misread:
        out.display += f" · missed: {'; '.join(str(m) for m in misread[:2])}"
    out.sub_score = float(rating)
    out.evidence = _anchors(analysis, list(block.get("evidence_at_ms") or []))
    return out


def _early_end(analysis: AnalysisInput) -> SignalResult:
    """Whether closing early — if it happened — was the right call.

    Scored only when the interview *was* closed early. A session that ran to a
    natural end has nothing to assess here, and scoring it zero would penalise
    the ordinary case.
    """
    out = _base(
        "early_end_judgement",
        "Judgement in closing early",
        "structure",
        1.5,
        "ASSESSED. Closing early on an evidenced read is good interviewing, not "
        "an abandoned interview — what separates them is whether there was "
        "evidence before the decision, and whether the close was civil",
    )
    block = analysis.early_end
    if not block:
        out.reason = "no analysis has been run for this session"
        return out
    if not block.get("ended_early"):
        out.value = 0.0
        out.display = "ran to a natural end"
        out.reason = "the interview was not closed early, so there is nothing to judge here"
        return out

    evidence_first = _rating(block, "evidence_before_deciding", 5)
    civil = bool(block.get("closed_civilly", True))
    justified = bool(block.get("justified", True))
    out.value = float(evidence_first)
    verdict = "justified" if justified else "premature"
    out.display = (
        f"closed early and {verdict} — evidence before deciding {evidence_first}/10, "
        f"{'civil' if civil else 'abrupt'} close"
    )
    out.sub_score = transfer.linear_up(float(evidence_first), 0.0, 8.0) if justified else 2.0
    if not civil:
        out.sub_score = max(0.0, (out.sub_score or 0.0) - 3.0)
    out.evidence = _anchors(analysis, [int(block.get("at_ms", 0))])
    return out


def _expectation_coverage(analysis: AnalysisInput) -> SignalResult:
    """How much of what was *reachable* got covered."""
    out = _base(
        "expectation_coverage",
        "Covered what was reachable",
        "structure",
        COVERAGE_WEIGHT,
        "ASSESSED. Scored against items that were still reachable, not the whole "
        "plan: items the manager rightly never got to are not gaps",
    )
    block = analysis.expectation_coverage
    if not block:
        out.reason = "no analysis has been run for this session"
        return out
    reachable = _rating(block, "reachable_items")
    covered = _rating(block, "covered_items")
    rating = _rating(block)
    out.value = float(rating)
    out.display = f"{covered} of {reachable} reachable items" if reachable else f"{rating}/10"
    because = str(block.get("unreachable_because") or "").strip()
    if because:
        out.display += f" · {because[:120]}"
    out.sub_score = float(rating)
    return out


def _flagged_topics(analysis: AnalysisInput) -> SignalResult:
    """Protected, high-risk or stereotyped moments the analysis heard.

    This is the signal the deterministic pass cannot do on code-mixed speech: an
    English lexicon matches nothing in a Hindi question, which is how a session
    containing three protected-topic questions scored a perfect fairness mark.
    """
    out = _base(
        "assessed_topic_flags",
        "Protected or stereotyped moments (heard)",
        "fairness",
        4.0,
        "ASSESSED from the audio in whatever language it was spoken. The counted "
        "detector reads English patterns only and misses the same question asked "
        "in Hindi",
    )
    flags = [f for f in analysis.topic_flags if f.get("raised_by") == "manager"]
    pursued = [f for f in flags if f.get("pursued_by_manager", True)]
    out.value = float(len(pursued))
    if not flags:
        out.display = "none heard"
    else:
        kinds = sorted({str(f.get("category", "")) for f in pursued or flags})
        out.display = f"{len(pursued)} raised by the manager: {', '.join(kinds)[:140]}"
    out.sub_score = transfer.penalty_count(len(pursued), step=4.0)
    out.evidence = [
        Evidence(
            turn_index=-1,
            at_ms=int(f.get("at_ms", 0)),
            speaker="manager",
            quote=f"[{f.get('category', '')}] {f.get('quote_en') or f.get('quote', '')}"[:400],
        )
        for f in (pursued or flags)[:3]
    ]
    return out


def _question_clarity(analysis: AnalysisInput) -> SignalResult:
    """Could a frontline candidate answer these questions on first hearing?"""
    out = _base(
        "question_clarity",
        "Question clarity",
        "communication",
        2.0,
        "ASSESSED from the audio. A question the manager had to re-ask because "
        "it did not land is direct evidence",
    )
    rating = _rating(analysis.delivery, "question_clarity", -1)
    if rating < 0:
        out.reason = "no analysis has been run for this session"
        return out
    out.value = float(rating)
    out.display = f"{rating}/10"
    out.sub_score = float(rating)
    return out


def _explanation_quality(analysis: AnalysisInput) -> SignalResult:
    """Was the role explained concretely, and were questions actually answered?"""
    out = _base(
        "explanation_quality",
        "Explaining the role",
        "clarity",
        2.0,
        "ASSESSED from the audio: whether what the manager said about pay, "
        "shifts and process was concrete and checkable",
    )
    rating = _rating(analysis.delivery, "explanation_quality", -1)
    if rating < 0:
        out.reason = "no analysis has been run for this session"
        return out
    out.value = float(rating)
    out.display = f"{rating}/10"
    out.sub_score = float(rating)
    return out
