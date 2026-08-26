"""Aggregation — the only place numbers are combined. Spec section 4.

Unmeasurable signals are dropped and the remaining weights renormalised, never
scored as zero. No criterion caps, fails or overrides another: the report is an
analytical estimate, not a gate.
"""

from __future__ import annotations

import re
from typing import Any

from report_engine import acts as acts_module
from report_engine import language, segment
from report_engine.coach import for_signal
from report_engine.schema import (
    AssessmentReport,
    CriterionScore,
    Finding,
    Provenance,
    QuestionAct,
    Rubric,
    SessionBundle,
    SignalResult,
)
from report_engine.signals import Context, extract_all
from report_engine.signals.context import load_pack

#: Below this share of a criterion's total signal weight, the criterion's score
#: is reported with low confidence and the report names what was missing.
CONFIDENCE_FLOOR = 0.5

#: Kluger & DeNisi's mechanism argues against volume: diffuse feedback shifts
#: attention from the task to the self. Three is convention, not a finding.
MAX_DEVELOPMENT_AREAS = 3


def build_report(bundle: SessionBundle) -> AssessmentReport:
    """Turn one session bundle into one report. Deterministic end to end."""
    options = bundle.scoring_options
    pack = load_pack(bundle.jurisdiction.lower())

    report = AssessmentReport(
        session_id=bundle.session.session_id,
        manager_name=bundle.session.manager_name,
        persona_label=bundle.persona.label or bundle.persona.archetype_key,
        job_title=bundle.job_card.job_title,
        modality=bundle.session.modality,
        provenance=Provenance(
            rubric_version=bundle.rubric.version,
            english_weight=options.english_weight,
            language_gate=options.language_gate,
            jurisdiction=bundle.jurisdiction,
            pack_version=pack["pack_version"],
        ),
    )

    report.language = language.check(bundle.turns, gate=options.language_gate)
    if report.language.gated:
        report.unscoreable = "language_unsupported"
        return report

    english = report.language.detected == "en"
    if not english:
        report.validity_warnings.append(
            f"This interview was not conducted entirely in English "
            f"(detected '{report.language.detected}', "
            f"{report.language.english_token_share:.0%} English function words). "
            "It has still been scored. What that costs is named per criterion: "
            "anything counted from English question patterns or English phrase "
            "lists measures less than it claims to here, and those criteria are "
            "marked low confidence."
        )

    question_acts = acts_module.extract(bundle.turns)
    segments = segment.assign(bundle.turns, question_acts)
    for act in question_acts:
        act.segment = segments.get(act.turn_index, segment.ASSESS)
    _label_protected(question_acts, pack)

    ctx = Context(bundle=bundle, acts=question_acts, segments=segments)
    signals = extract_all(ctx)
    for signal in signals:
        signal.dedupe_evidence()

    report.duration_ms = ctx.duration_ms
    report.question_acts = question_acts
    report.criteria = _score_criteria(bundle.rubric, signals, options.english_weight)
    if not english:
        _downgrade_for_language(report.criteria, report.language.detected)
    report.readiness_index = _readiness(report.criteria)
    if report.readiness_index is not None:
        report.band = bundle.rubric.band_for(report.readiness_index)

    report.strengths, report.gaps = _findings(signals)
    report.development_areas = report.gaps[:MAX_DEVELOPMENT_AREAS]
    report.next_practice, report.next_practice_reason = _next_practice(bundle, report.criteria)
    return report


def _label_protected(question_acts: list[QuestionAct], pack: dict[str, Any]) -> None:
    """Stamp the protected-topic category onto the acts that tripped it."""
    compiled = [
        (c["id"], re.compile(p, re.IGNORECASE)) for c in pack["categories"] for p in c["patterns"]
    ]
    for act in question_acts:
        for cat_id, pattern in compiled:
            if pattern.search(act.text):
                act.protected_topic = cat_id
                break


def _effective_weights(rubric: Rubric, english_weight: float | None) -> dict[str, float]:
    """Rubric weights, scaled by (1 - w) when English is weighted in — spec 4.1."""
    weights = {c.id: c.weight for c in rubric.criteria}
    if english_weight:
        weights = {k: v * (1.0 - english_weight) for k, v in weights.items()}
        weights["communication_english"] = english_weight
    return weights


def _score_criteria(
    rubric: Rubric, signals: list[SignalResult], english_weight: float | None
) -> list[CriterionScore]:
    """One score per criterion, from its measurable signals only."""
    weights = _effective_weights(rubric, english_weight)
    labels = {c.id: c.label for c in rubric.criteria}
    labels.setdefault("communication_english", "Communication & Presentation (English)")

    out: list[CriterionScore] = []
    for criterion_id, weight in weights.items():
        mine = [s for s in signals if s.criterion == criterion_id]
        # Pair the score with its signal so the narrowing survives into the sum.
        scored: list[tuple[SignalResult, float]] = [
            (s, s.sub_score) for s in mine if s.sub_score is not None and s.weight > 0
        ]
        total_weight = sum(s.weight for s in mine if s.weight > 0)
        got_weight = sum(s.weight for s, _ in scored)

        entry = CriterionScore(
            id=criterion_id,
            label=labels.get(criterion_id, criterion_id),
            weight=round(weight, 4),
            signals=mine,
        )
        if not scored:
            entry.confidence = "none"
            entry.confidence_reason = (
                "no signal for this criterion could be measured in this session"
            )
            out.append(entry)
            continue

        entry.score = round(sum(sub * s.weight for s, sub in scored) / got_weight, 2)
        coverage = got_weight / total_weight if total_weight else 0.0
        if coverage < CONFIDENCE_FLOOR:
            missing = [s.label for s in mine if not s.measurable and s.weight > 0]
            entry.confidence = "low"
            entry.confidence_reason = (
                f"only {coverage:.0%} of this criterion's evidence was measurable"
                + (f" — missing: {', '.join(missing)}" if missing else "")
            )
        elif coverage < 1.0:
            entry.confidence = "medium"
            entry.confidence_reason = f"{coverage:.0%} of this criterion's evidence was measurable"
        out.append(entry)

    return out


def _downgrade_for_language(criteria: list[CriterionScore], detected: str) -> None:
    """Mark criteria whose evidence leans on English as low confidence.

    The score still stands - refusing to produce one was the old behaviour and
    it left a manager with nothing. What changes is the claim made about it: a
    criterion counted from English question patterns has measured less of a
    code-mixed interview than of an English one, and the report should not
    present the two as equally solid.
    """
    for entry in criteria:
        scored = [s for s in entry.signals if s.measurable and s.weight > 0]
        if not scored:
            continue
        affected = [s for s in scored if s.language_sensitive]
        if not affected:
            continue
        share = sum(s.weight for s in affected) / sum(s.weight for s in scored)
        entry.confidence = "low"
        entry.confidence_reason = (
            f"{share:.0%} of this criterion's evidence is counted from English "
            f"patterns, and this session was detected as '{detected}'"
            + (f". {entry.confidence_reason}" if entry.confidence_reason else "")
        )


def _readiness(criteria: list[CriterionScore]) -> int | None:
    """Weighted 0-100 index across the criteria that produced a score."""
    scored = [(c, c.score) for c in criteria if c.score is not None]
    if not scored:
        return None
    total = sum(c.weight for c, _ in scored)
    if total <= 0:
        return None
    return round(10.0 * sum(score * c.weight for c, score in scored) / total)


def _findings(signals: list[SignalResult]) -> tuple[list[Finding], list[Finding]]:
    """Strengths and gaps, selected by score and phrased at behaviour level."""
    scored = [s for s in signals if s.measurable and s.weight > 0]
    ranked = sorted(scored, key=lambda s: (s.sub_score or 0.0, s.weight), reverse=True)

    strengths: list[Finding] = []
    for signal in ranked:
        if (signal.sub_score or 0) < 7.5 or len(strengths) >= 4:
            break
        coaching = for_signal(signal.id)
        if not coaching.strength:
            continue
        strengths.append(
            Finding(
                signal_id=signal.id,
                headline=coaching.strength,
                detail=signal.display,
                evidence=signal.evidence[:2],
            )
        )

    gaps: list[Finding] = []
    for signal in reversed(ranked):
        if (signal.sub_score or 0) >= 6.0 or len(gaps) >= 4:
            break
        coaching = for_signal(signal.id)
        if not coaching.gap:
            continue
        gaps.append(
            Finding(
                signal_id=signal.id,
                headline=coaching.gap,
                detail=signal.display,
                alternative=coaching.alternative,
                evidence=signal.evidence[:2],
            )
        )

    return strengths, gaps


def _next_practice(bundle: SessionBundle, criteria: list[CriterionScore]) -> tuple[str, str]:
    """The persona that most stresses the weakest criterion. Fully deterministic."""
    scored = [(c, c.score) for c in criteria if c.score is not None]
    if not scored:
        return "", ""
    weakest, weakest_score = min(scored, key=lambda pair: pair[1])
    stress = bundle.persona.stresses.get(weakest.id, 0)
    return (
        weakest.id,
        f"Weakest criterion is {weakest.label} at {weakest_score}/10. "
        f"Practise against a persona that stresses it harder than "
        f"'{bundle.persona.label or bundle.persona.archetype_key}' did "
        f"(stress level {stress}/4 on this criterion).",
    )
