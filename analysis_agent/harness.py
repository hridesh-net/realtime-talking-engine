"""Merging and validating what the model returns, window by window.

Code owns everything arithmetic here. The model observes one window at a time
and reports timestamps relative to that window; this module shifts them into the
recording's own clock, throws away anchors that fall outside the recording, and
reconciles the windows into one analysis.

Keeping the merge here rather than asking the model to do it is what makes the
result reproducible from the same window answers, and it is the only place an
anchor can be rejected.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from analysis_agent.schema import (
    EXPECTATION_COVERAGE_WEIGHT,
    PERSONA_RESPONSE_WEIGHT,
    AnalysedTurn,
    CriterionAssessment,
    DeliveryObservation,
    DiscoveryObservation,
    EarlyEndAssessment,
    ExpectationCoverageAssessment,
    InterruptionObservation,
    PersonaResponseAssessment,
    QuestionObservation,
    SessionAnalysis,
    SilenceObservation,
    TopicFlag,
)

#: Two observations from overlapping windows are the same event when they land
#: within this of each other and say the same thing.
DUPLICATE_MS = 4_000

#: Anchors may exceed the recording by this much before being rejected, to
#: absorb ordinary rounding rather than confabulation.
ANCHOR_SLACK_MS = 2_000

#: Better-evidenced discovery statuses win when windows disagree. "surfaced"
#: outranks the rest because it is the only one requiring positive evidence.
_DISCOVERY_RANK = {"surfaced": 3, "volunteered": 2, "unclear": 1, "not_surfaced": 0}


class _Anchored(Protocol):
    """An observation carrying a timestamp — the only field the collector touches."""

    at_ms: int


_AnchoredT = TypeVar("_AnchoredT", bound=_Anchored)


def _shift(value: int, offset: int) -> int:
    return max(0, int(value) + offset)


def _same(left: str, right: str) -> bool:
    """Whether two quotes are the same utterance heard twice."""
    a, b = left.strip().lower(), right.strip().lower()
    if not a or not b:
        return a == b
    return a[:40] == b[:40]


def merge(
    answers: list[tuple[int, int, dict[str, Any]]],
    *,
    audio_duration_ms: int,
    model_used: str,
) -> SessionAnalysis:
    """Fold per-window answers into one analysis on the recording's clock.

    `answers` is `(offset_ms, window_duration_ms, raw_json)` per window, in
    order. The window duration is carried because an anchor is validated against
    **the audio it came from**, not merely against the whole recording: a late
    window's overshoot would otherwise hide under the headroom of the windows
    before it, which is exactly how a 352s timestamp survived a 346s recording.
    """
    out = SessionAnalysis(
        model_used=model_used,
        windows=len(answers),
        audio_duration_ms=audio_duration_ms,
    )
    limit = audio_duration_ms + ANCHOR_SLACK_MS
    dropped = 0
    languages: list[str] = []
    notes: list[str] = []
    deliveries: list[tuple[int, DeliveryObservation]] = []
    ratings: dict[str, list[CriterionAssessment]] = {}

    for offset, window_ms, raw in answers:
        window_limit = window_ms + ANCHOR_SLACK_MS
        for raw_name in raw.get("spoken_languages", []) or []:
            # Windows disagree on capitalisation, and "Hindi, English, hindi,
            # english" reads as a bug to anyone shown it.
            name = str(raw_name).strip().lower()
            if name and name not in languages:
                languages.append(name)
        note = (raw.get("quality_notes") or "").strip()
        if note and note not in notes:
            notes.append(note)

        for item in raw.get("transcript", []) or []:
            turn = AnalysedTurn.model_validate(item)
            if turn.start_ms > window_limit:
                dropped += 1
                continue
            turn.start_ms = _shift(turn.start_ms, offset)
            turn.end_ms = min(_shift(turn.end_ms, offset), limit)
            if turn.start_ms > limit:
                dropped += 1
                continue
            if any(
                t.speaker == turn.speaker
                and abs(t.start_ms - turn.start_ms) <= DUPLICATE_MS
                and _same(t.text, turn.text)
                for t in out.transcript
            ):
                continue
            out.transcript.append(turn)

        dropped += _collect(
            raw.get("questions"),
            QuestionObservation.model_validate,
            out.questions,
            offset,
            window_limit,
            limit,
            "text",
        )
        dropped += _collect(
            raw.get("topic_flags"),
            TopicFlag.model_validate,
            out.topic_flags,
            offset,
            window_limit,
            limit,
            "quote",
        )
        dropped += _collect(
            raw.get("silences"),
            SilenceObservation.model_validate,
            out.silences,
            offset,
            window_limit,
            limit,
            "",
        )
        dropped += _collect(
            raw.get("interruptions"),
            InterruptionObservation.model_validate,
            out.interruptions,
            offset,
            window_limit,
            limit,
            "quote",
        )

        for item in raw.get("discovery", []) or []:
            found = DiscoveryObservation.model_validate(item)
            found.at_ms = _shift(found.at_ms, offset)
            existing = next((d for d in out.discovery if d.id == found.id), None)
            if existing is None:
                out.discovery.append(found)
            elif _DISCOVERY_RANK.get(found.status, 0) > _DISCOVERY_RANK.get(existing.status, 0):
                out.discovery[out.discovery.index(existing)] = found

        if raw.get("delivery"):
            deliveries.append(
                (
                    max(1, len(raw.get("transcript") or [])),
                    DeliveryObservation.model_validate(raw["delivery"]),
                )
            )

        for item in raw.get("criteria", []) or []:
            got = CriterionAssessment.model_validate(item)
            got.evidence_at_ms = [
                _shift(anchor, offset) for anchor in got.evidence_at_ms if anchor <= window_limit
            ]
            ratings.setdefault(got.id, []).append(got)

    out.transcript.sort(key=lambda t: t.start_ms)
    out.questions.sort(key=lambda q: q.at_ms)
    out.topic_flags.sort(key=lambda f: f.at_ms)
    out.spoken_languages = languages
    out.quality_notes = " ".join(notes)
    out.delivery = _merge_delivery(deliveries)
    out.persona_response = _merge_persona(
        [
            PersonaResponseAssessment.model_validate(r["persona_response"])
            for _, _, r in answers
            if r.get("persona_response")
        ],
        [o for o, _, r in answers if r.get("persona_response")],
    )
    out.expectation_coverage = _merge_coverage(
        [
            ExpectationCoverageAssessment.model_validate(r["expectation_coverage"])
            for _, _, r in answers
            if r.get("expectation_coverage")
        ]
    )
    out.early_end = _merge_early_end(
        [
            (o, EarlyEndAssessment.model_validate(r["early_end"]))
            for o, _, r in answers
            if r.get("early_end")
        ],
        limit,
    )
    out.session_judgement = round(
        out.persona_response.rating * PERSONA_RESPONSE_WEIGHT
        + out.expectation_coverage.rating * EXPECTATION_COVERAGE_WEIGHT,
        2,
    )
    out.criteria = _merge_criteria(ratings)
    out.dropped_anchors = dropped
    return out


def _collect(
    items: list[dict[str, Any]] | None,
    parse: Callable[[dict[str, Any]], _AnchoredT],
    into: list[_AnchoredT],
    offset: int,
    window_limit: int,
    limit: int,
    text_field: str,
) -> int:
    """Validate, shift, reject out-of-range and de-duplicate. Returns drops."""
    dropped = 0
    for item in items or []:
        parsed = parse(item)
        if parsed.at_ms > window_limit:
            dropped += 1
            continue
        parsed.at_ms = _shift(parsed.at_ms, offset)
        if parsed.at_ms > limit:
            dropped += 1
            continue
        if any(
            abs(existing.at_ms - parsed.at_ms) <= DUPLICATE_MS
            and (
                not text_field
                or _same(getattr(existing, text_field, ""), getattr(parsed, text_field, ""))
            )
            for existing in into
        ):
            continue
        into.append(parsed)
    return dropped


def _merge_delivery(entries: list[tuple[int, DeliveryObservation]]) -> DeliveryObservation:
    """Weight each window's delivery read by how much was said in it."""
    if not entries:
        return DeliveryObservation()
    total = sum(weight for weight, _ in entries)
    clarity = sum(d.question_clarity * w for w, d in entries) / total
    explanation = sum(d.explanation_quality * w for w, d in entries) / total
    shifts = [s for _, d in entries for s in d.tone_shifts]
    trajectory = " ".join(
        d.tone_trajectory.strip() for _, d in entries if d.tone_trajectory.strip()
    )
    pace = " ".join(d.pace_note.strip() for _, d in entries if d.pace_note.strip())
    weakest = min(
        (d.confidence for _, d in entries), key=lambda c: ("low", "medium", "high").index(c)
    )
    return DeliveryObservation(
        question_clarity=round(clarity),
        explanation_quality=round(explanation),
        tone_trajectory=trajectory[:2000],
        tone_shifts=shifts,
        pace_note=pace[:1000],
        confidence=weakest,
    )


def _merge_criteria(ratings: dict[str, list[CriterionAssessment]]) -> list[CriterionAssessment]:
    """One assessment per criterion, averaged across the windows that saw it."""
    merged: list[CriterionAssessment] = []
    for criterion_id, entries in ratings.items():
        rating = round(sum(e.rating for e in entries) / len(entries))
        reasoning = " ".join(e.reasoning.strip() for e in entries if e.reasoning.strip())
        anchors = sorted({a for e in entries for a in e.evidence_at_ms})
        weakest = min(
            (e.confidence for e in entries), key=lambda c: ("low", "medium", "high").index(c)
        )
        merged.append(
            CriterionAssessment(
                id=criterion_id,
                rating=rating,
                reasoning=reasoning[:4000],
                evidence_at_ms=anchors,
                confidence=weakest,
            )
        )
    return merged


def _weakest(values: list[str]) -> str:
    order = ("low", "medium", "high")
    return min(values, key=order.index) if values else "medium"


def _merge_persona(
    entries: list[PersonaResponseAssessment], offsets: list[int]
) -> PersonaResponseAssessment:
    """One read of how the manager handled this candidate, across the windows.

    Averaged rather than taking the last window: adaptation happens throughout,
    and a manager who read the candidate well early and drifted later did both.
    """
    if not entries:
        return PersonaResponseAssessment()
    n = len(entries)
    anchors = sorted(
        {a + off for entry, off in zip(entries, offsets, strict=True) for a in entry.evidence_at_ms}
    )
    return PersonaResponseAssessment(
        read_the_candidate=round(sum(e.read_the_candidate for e in entries) / n),
        adapted_approach=round(sum(e.adapted_approach for e in entries) / n),
        handled_the_hard_moment=round(sum(e.handled_the_hard_moment for e in entries) / n),
        rating=round(sum(e.rating for e in entries) / n),
        reasoning=" ".join(e.reasoning.strip() for e in entries if e.reasoning.strip())[:4000],
        misread_signals=[s for e in entries for s in e.misread_signals],
        evidence_at_ms=anchors,
        confidence=_weakest([e.confidence for e in entries]),
    )


def _merge_coverage(
    entries: list[ExpectationCoverageAssessment],
) -> ExpectationCoverageAssessment:
    """Coverage summed across windows, not averaged.

    An item covered in window one stays covered; averaging the ratings of a
    window that saw it and a window that did not would understate the manager.
    """
    if not entries:
        return ExpectationCoverageAssessment()
    reachable = max(e.reachable_items for e in entries)
    covered = min(reachable, max(e.covered_items for e in entries))
    # The model's own rating is deliberately discarded when it gave counts: a
    # rating is an opinion, `covered / reachable` is arithmetic, and code owning
    # the arithmetic is what makes the number checkable. It is only a fallback
    # for a window that could not count anything.
    rating = round(10 * covered / reachable) if reachable else max(e.rating for e in entries)
    return ExpectationCoverageAssessment(
        rating=rating,
        reachable_items=reachable,
        covered_items=covered,
        reasoning=" ".join(e.reasoning.strip() for e in entries if e.reasoning.strip())[:4000],
        unreachable_because=" ".join(
            e.unreachable_because.strip() for e in entries if e.unreachable_because.strip()
        )[:2000],
        confidence=_weakest([e.confidence for e in entries]),
    )


def _merge_early_end(
    entries: list[tuple[int, EarlyEndAssessment]], limit: int
) -> EarlyEndAssessment:
    """The close happens once, in whichever window heard it."""
    ended = [(offset, e) for offset, e in entries if e.ended_early]
    if not ended:
        return EarlyEndAssessment(ended_early=False)
    offset, entry = ended[-1]
    entry.at_ms = min(_shift(entry.at_ms, offset), limit)
    return entry
