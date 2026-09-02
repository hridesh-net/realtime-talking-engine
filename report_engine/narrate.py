"""The sentences code can write from the measurements alone.

A scorecard a manager acts on has to say what they *did*, not which detector
fired. This module composes that layer — the summary, one narrative per
criterion, and up to three plain-language bullets under each — from numbers that
are already computed. It invents nothing: every bullet names the signal it was
written about, and every claim in it is a restatement of that signal's score.

It is the deterministic counterpart to :mod:`report_engine.judge`. Without a
judge these sentences *are* the report's prose, which is what keeps the offline
path a complete report rather than a table with the headings missing. With a
judge they are the fallback for any claim the evidence check vetoed, so a
rejected sentence degrades to a stiffer true one rather than to a blank.
"""

from __future__ import annotations

from report_engine.coach import for_signal, in_perspective
from report_engine.schema import AssessmentReport, Bullet, CriterionScore, SignalResult

#: A signal at or above this sub-score earns the criterion something and is
#: written as a strength. Shared with `score._findings` by intent: a bullet and a
#: finding disagreeing about whether the same signal went well would be a bug the
#: reader sees.
POSITIVE_FLOOR = 7.5

#: Below this it cost the criterion something and is written as a gap.
NEGATIVE_CEILING = 6.0

#: Bullets per criterion card. Three is the sample layout's room, and it is also
#: as many behaviours as a reader will act on for one competency.
BULLET_COUNT = 3

#: A criterion at or above this score leads with what went well; below it, the
#: card gives the gaps the extra line. The reader of a weak criterion needs the
#: problem first.
LEADS_WITH_STRENGTH = 6.5


def out_of_four(score: float | None) -> str:
    """A 0-10 sub-score on the four-point scale the scorecard is read in.

    Presentation only — nothing downstream reads this back. The rubric's own
    arithmetic stays on the 0-10 scale it was calibrated on, because rescaling
    the numbers rather than their display would mean re-deriving every threshold
    in the spec against a scale no study used.
    """
    return "—" if score is None else f"{score / 10 * 4:.1f}"


def apply(report: AssessmentReport, perspective: str = "manager") -> None:
    """Write every composed sentence onto the report, in place."""
    for criterion in report.criteria:
        criterion.bullets = bullets_for(criterion, perspective)
        criterion.narrative = narrative_for(criterion)
    report.summary = summary_for(report, perspective)


def bullets_for(criterion: CriterionScore, perspective: str = "manager") -> list[Bullet]:
    """Up to three behaviours, strongest first, weakest last."""
    ranked = sorted(
        (s for s in criterion.signals if s.measurable and s.weight > 0 and s.sub_score is not None),
        key=lambda s: (s.sub_score or 0.0, s.weight),
        reverse=True,
    )
    positive = [b for b in (_line(s, "positive", perspective) for s in ranked) if b]
    negative = [b for b in (_line(s, "negative", perspective) for s in reversed(ranked)) if b]

    if not positive or not negative:
        return (positive or negative)[:BULLET_COUNT]

    # A weak criterion gets the extra line for what went wrong; a strong one
    # gets it for what went right. The card should read the way the score does.
    score = criterion.score if criterion.score is not None else 0.0
    gaps = 1 if score >= LEADS_WITH_STRENGTH else 2
    return positive[: BULLET_COUNT - gaps] + negative[:gaps]


def _line(signal: SignalResult, polarity: str, perspective: str) -> Bullet | None:
    """One bullet, or None when this signal does not belong on this side."""
    score = signal.sub_score or 0.0
    if polarity == "positive" and score < POSITIVE_FLOOR:
        return None
    if polarity == "negative" and score >= NEGATIVE_CEILING:
        return None
    coaching = for_signal(signal.id)
    text = coaching.strength if polarity == "positive" else coaching.gap
    if not text:
        return None
    return Bullet(
        text=in_perspective(text, perspective),
        polarity=polarity,
        signal_id=signal.id,
    )


def narrative_for(criterion: CriterionScore) -> str:
    """What the score rests on — but only when that is not already on the card.

    Deliberately *not* a restatement of the bullets. Code cannot write the
    sample's paragraph without repeating the three lines underneath it, so the
    honest split is to let the bullets carry the behaviour and let this carry how
    much of the criterion could actually be seen. When everything was measurable
    it carries nothing, and returns empty rather than restating the score printed
    two inches to the right. The judge replaces it with prose that does both.
    """
    if criterion.score is None:
        return criterion.confidence_reason or "Nothing for this criterion was measurable."
    if criterion.confidence != "high" and criterion.confidence_reason:
        return f"Read at {criterion.confidence} confidence — {criterion.confidence_reason}."
    return ""


def summary_for(report: AssessmentReport, perspective: str = "manager") -> str:
    """The paragraph the report opens with."""
    scored = [c for c in report.criteria if c.score is not None]
    if report.readiness_index is None or not scored:
        return (
            "No criterion in this session produced a score, so there is no readiness "
            "index. The sections below say which signals could not be measured and why."
        )

    subject = {"manager": "You", "coach": "They"}.get(perspective, "The manager")
    strongest = max(scored, key=lambda c: c.score or 0.0)
    weakest = min(scored, key=lambda c: c.score or 0.0)

    parts = [
        f"{subject} finished at {report.readiness_index}/100 — {report.band.lower()} — "
        f"across {len(scored)} weighted "
        f"{'criterion' if len(scored) == 1 else 'criteria'}."
    ]
    if strongest.id != weakest.id:
        parts.append(
            f"Strongest was {strongest.label} at {out_of_four(strongest.score)}/4; "
            f"weakest was {weakest.label} at {out_of_four(weakest.score)}/4."
        )
    if report.development_areas:
        # The gap, not its rehearsable alternative: the alternative is printed
        # verbatim under Areas to improve, and most are written as a quoted line
        # to say, which reads badly folded into a sentence.
        priority = report.development_areas[0].headline.rstrip(".")
        parts.append(f"Closest development priority: {priority[0].lower()}{priority[1:]}.")
    return " ".join(parts)
