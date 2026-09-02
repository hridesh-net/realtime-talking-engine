"""Aggregation — the only place numbers are combined. Spec section 4.

Unmeasurable signals are dropped and the remaining weights renormalised, never
scored as zero. No criterion caps, fails or overrides another: the report is an
analytical estimate, not a gate.
"""

from __future__ import annotations

import re
from typing import Any

from report_engine import acts as acts_module
from report_engine import language, narrate, segment
from report_engine.coach import for_signal, in_perspective
from report_engine.schema import (
    AssessmentReport,
    Basis,
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

#: Strengths, and gaps, shown per report. The same convention as
#: `ReportConfig.max_development_areas` and for the same reason: Kluger &
#: DeNisi's mechanism is that diffuse, high-volume feedback shifts attention from
#: the task to the self, so a longer list is not a better one. Selection is
#: unchanged — these are still the highest and lowest scoring signals with valid
#: evidence, and every signal remains in `criteria[].signals` either way.
MAX_FINDINGS_PER_SIDE = 3

#: Kluger & DeNisi's mechanism argues against volume: diffuse feedback shifts
#: attention from the task to the self. Three is convention, not a finding, and
#: it is now the default of `ReportConfig.max_development_areas` rather than a
#: constant here - an org running longer coaching sessions may want more.


def build_report(
    bundle: SessionBundle, extra_signals: list[SignalResult] | None = None
) -> AssessmentReport:
    """Turn one session bundle into one report. Deterministic end to end.

    Args:
        bundle: The session, the rubric and the persona.
        extra_signals: Measurements this module did not compute — today, the
            judge's evidence-checked `must_discover` verdicts. They join the
            counted signals *before* aggregation rather than being patched onto
            a finished report, so the criterion score, the readiness index and
            the finding selection are all still derived here, in one place, from
            the whole signal set. Passing none is the offline path and is
            byte-identical across runs.
    """
    options = bundle.scoring_options
    pack = load_pack(bundle.jurisdiction.lower())

    report = AssessmentReport(
        session_id=bundle.session.session_id,
        manager_name=bundle.session.manager_name,
        persona_label=bundle.persona.label or bundle.persona.archetype_key,
        job_title=bundle.job_card.job_title,
        modality=bundle.session.modality,
        started_at=bundle.session.started_at,
        provenance=Provenance(
            analysis_instructions_version=(
                bundle.analysis.instructions_version if bundle.analysis else ""
            ),
            analysis_model=bundle.analysis.model_used if bundle.analysis else "",
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
    signals = extract_all(ctx) + list(extra_signals or [])
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

    report.basis = _basis(bundle, report, signals)
    report.strengths, report.gaps = _findings(signals, bundle.report_config.perspective)
    report.development_areas = report.gaps[: bundle.report_config.max_development_areas]
    report.next_practice, report.next_practice_reason = _next_practice(bundle, report.criteria)
    # Last, because every sentence it writes is composed from numbers the lines
    # above have already settled.
    narrate.apply(report, bundle.report_config.perspective)
    return report


def _basis(bundle: SessionBundle, report: AssessmentReport, signals: list[SignalResult]) -> Basis:
    """A plain statement of what produced this report and what it could not see.

    Printed on the report itself. A trainer acting on a number is owed the
    difference between a count and a reading, and owed the limits in the reader's
    language rather than in a design document they will never open.
    """
    measured = [s for s in signals if s.measurable and s.source == "measured"]
    assessed = [s for s in signals if s.measurable and s.source == "assessed"]
    judged = [s for s in signals if s.measurable and s.source == "judged"]
    lines = [
        f"**{len(measured)} measured signals** — counted from the stored transcript by code. "
        "Re-running produces the same numbers.",
    ]
    cautions: list[str] = []

    if bundle.analysis:
        a = bundle.analysis
        lines.append(
            f"**{len(assessed)} assessed signals** — from listening to the recording "
            f"({a.model_used or 'a model'}, instructions {a.instructions_version}), "
            f"analysed in {a.windows} window(s)."
        )
        lines.append(
            "The analysis weighs **how the manager handled this particular candidate "
            "above how much of the plan they covered** — reading the person is harder "
            "and worth more, and closing early on a candidate who is plainly "
            "unsuited is a good decision, not an unfinished interview."
        )
        if a.spoken_languages:
            lines.append(
                "Languages heard: " + ", ".join(a.spoken_languages) + ". "
                "The assessed signals read the language actually spoken; the "
                "measured ones read English patterns only."
            )
        if a.dropped_anchors:
            cautions.append(
                f"{a.dropped_anchors} timestamps the analysis produced fell outside the "
                "recording and were discarded. Models lose track of elapsed time over long "
                "audio; anchors that survive have been checked against the recording's length."
            )
        if a.quality_notes:
            cautions.append(a.quality_notes)
    else:
        lines.append(
            "**No audio analysis has been run.** This report is the counted half "
            "alone: tone, delivery, and anything said in a language other than "
            "English are not represented in it."
        )
        cautions.append(
            "Counted detectors read English patterns. A protected-topic question "
            "asked in Hindi does not match one, so a clean fairness result here is "
            "not evidence that nothing was asked."
        )

    if judged:
        lines.append(
            f"**{len(judged)} judged signal(s)** — read out of the transcript by the "
            "report judge. Every claim under one carries a quote matched word for "
            "word against the transcript; a claim whose quote did not match was "
            "dropped rather than counted against the manager."
        )

    cautions.append(
        "Every number is an analytical estimate of how the manager interviewed. "
        "There is no pass, no fail, and no criterion that caps another."
    )
    if report.readiness_index is not None:
        cautions.append(
            "Managers who know a trainer will read this interview more defensively "
            "than they otherwise would; that is a real limit on what these numbers mean."
        )
    return Basis(lines=lines, cautions=cautions)


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
    covers = {c.id: list(c.covers) for c in rubric.criteria}

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
            covers=covers.get(criterion_id, []),
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
        # An assessed signal heard the language actually spoken, so it is not
        # weakened by the session being code-mixed - only the counted half is.
        affected = [s for s in scored if s.language_sensitive and s.source == "measured"]
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


#: Measurements that say nothing without the signal's name in front of them.
#: "no" is not a finding; "Agenda and duration stated: no" is.
_BARE = {"yes", "no", "none", "", "—"}


def _detail(signal: SignalResult) -> str:
    """The measurement, phrased so it can stand alone under a headline."""
    if signal.display.strip().lower() in _BARE:
        return f"{signal.label}: {signal.display}"
    return signal.display


def _findings(
    signals: list[SignalResult], perspective: str = "manager"
) -> tuple[list[Finding], list[Finding]]:
    """Strengths and gaps, selected by score and phrased at behaviour level."""
    scored = [s for s in signals if s.measurable and s.weight > 0]
    ranked = sorted(scored, key=lambda s: (s.sub_score or 0.0, s.weight), reverse=True)

    strengths: list[Finding] = []
    for signal in ranked:
        if (signal.sub_score or 0) < 7.5 or len(strengths) >= MAX_FINDINGS_PER_SIDE:
            break
        coaching = for_signal(signal.id)
        if not coaching.strength:
            continue
        strengths.append(
            Finding(
                signal_id=signal.id,
                headline=in_perspective(coaching.strength, perspective),
                detail=_detail(signal),
                evidence=signal.evidence[:2],
            )
        )

    gaps: list[Finding] = []
    for signal in reversed(ranked):
        if (signal.sub_score or 0) >= 6.0 or len(gaps) >= MAX_FINDINGS_PER_SIDE:
            break
        coaching = for_signal(signal.id)
        if not coaching.gap:
            continue
        gaps.append(
            Finding(
                signal_id=signal.id,
                headline=in_perspective(coaching.gap, perspective),
                detail=_detail(signal),
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
        f"{weakest.label} was weakest at {narrate.out_of_four(weakest_score)}/4. Practise "
        f"against a persona that stresses it harder than "
        f"'{bundle.persona.label or bundle.persona.archetype_key}' (stress {stress}/4).",
    )
