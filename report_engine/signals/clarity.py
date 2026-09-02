"""Hiring with Clarity signals — spec section 5.B.

Evidence base: realistic job previews reduce voluntary turnover (r = -.06,
Phillips 1998) and the mechanism is perceived organisational honesty rather
than met expectations, with face-to-face oral previews outperforming written
ones (Earnest, Allen & Landis 2011). Information given to the candidate is
also a procedural-justice driver of offer acceptance (Hausknecht, Day &
Thomas 2004, N = 48,750).
"""

from __future__ import annotations

import re

from report_engine import transfer
from report_engine.schema import ChecklistItem, SignalResult
from report_engine.segment import CLOSE, OPEN
from report_engine.signals.context import Context
from report_engine.text import compile_all, content_words, jaccard, sentences

CRITERION = "clarity"

_AGENDA = compile_all(
    [
        r"\bwe('ll| will| are going to) (spend|take|use)\b",
        r"\b(this|the) (call|interview|chat) (will|should) (take|last|run)\b",
        r"\bnext (\d+|thirty|twenty|forty|fifteen)\s*(minutes|mins)\b",
        r"\bfirst (i'?ll|we'?ll|i will)\b",
        r"\bhere'?s how (this|it) (will |'ll )?(work|go)\b",
        r"\bplan for (today|this call)\b",
        r"\bstart(ing)? with\b.*\bthen\b",
    ]
)

_NEXT_STEPS = compile_all(
    [
        r"\bnext steps?\b",
        r"\bwe('ll| will) (be in touch|get back|let you know|revert|call you)\b",
        r"\byou('ll| will) hear (back )?from\b",
        r"\b(hr|recruit\w*) will (reach|contact|call)\b",
        r"\bsecond round\b",
        r"\bmove (you )?forward\b",
    ]
)

_TIMELINE = compile_all(
    [
        r"\bby (monday|tuesday|wednesday|thursday|friday|next week|end of)\b",
        r"\bwithin (a|two|three|\d+)\s*(day|days|week|weeks)\b",
        r"\bin (a|two|three|\d+)\s*(day|days|week|weeks)\b",
        r"\bthis week\b",
        r"\bnext week\b",
        r"\b\d+\s*(working )?days\b",
    ]
)

_DOWNSIDE = compile_all(
    [
        r"\b(it|this|the (job|role)) (can|will) be (hard|tough|demanding|stressful)\b",
        r"\bthe (hard|tough|difficult) part\b",
        r"\bhonest(ly)?\b.{0,40}\b(hard|tough|not easy|demanding|pressure)\b",
        r"\bnot going to (lie|pretend|sugar)\b",
        r"\bsome (people|candidates) (find|struggle)\b",
        r"\bthe downside\b",
        r"\bwhat (people|most) don'?t (like|enjoy)\b",
        r"\blong hours\b",
        r"\bhigh (pressure|attrition|turnover)\b",
    ]
)


def extract(ctx: Context) -> list[SignalResult]:
    """Every clarity signal for this session."""
    return [
        _fact_coverage(ctx),
        _candidate_question_answer_rate(ctx),
        _agenda_set(ctx),
        _next_steps(ctx),
        _downside(ctx),
        _invite_fraction(ctx),
    ]


def _base(signal_id: str, label: str, weight: float, basis: str) -> SignalResult:
    return SignalResult(id=signal_id, label=label, criterion=CRITERION, weight=weight, basis=basis)


def _fact_coverage(ctx: Context) -> SignalResult:
    """The spec's "4 of 5 role facts conveyed"."""
    out = _base(
        "clarity_fact_coverage",
        "Role facts conveyed",
        weight=2.0,
        basis="The job card's checklist. A fact with an empty statement is not "
        "on this interview's list and is neither counted nor scored against",
    )
    facts = [f for f in ctx.bundle.job_card.clarity_facts if f.statement.strip()]
    if not facts:
        out.reason = "the job card carried no clarity facts"
        return out

    conveyed = 0
    missed: list[str] = []
    for fact in facts:
        cues = content_words(fact.statement)
        found = False
        for turn in ctx.manager_turns:
            for sentence in sentences(turn.text):
                if jaccard(content_words(sentence), cues) >= 0.15:
                    conveyed += 1
                    out.evidence.append(ctx.evidence(turn.index, sentence))
                    found = True
                    break
            if found:
                break
        if not found:
            missed.append(fact.key)
        out.checklist.append(ChecklistItem(label=fact.key, covered=found))

    value = conveyed / len(facts)
    out.value = round(value, 3)
    out.display = f"{conveyed} of {len(facts)} role facts conveyed"
    if missed:
        out.display += f" — missed: {', '.join(missed)}"
    out.sub_score = transfer.hit_rate(value)
    out.evidence = out.evidence[:3]
    return out


def _candidate_question_answer_rate(ctx: Context) -> SignalResult:
    """Did the candidate's questions get substantive answers?"""
    out = _base(
        "candidate_question_answer_rate",
        "Candidate questions answered",
        weight=1.5,
        basis="SOURCED (Hausknecht, Day & Thomas 2004 — information provision "
        "predicts offer acceptance and recommendation intent)",
    )
    asked: list[tuple[int, str]] = []
    for turn in ctx.candidate_turns:
        for sentence in sentences(turn.text):
            if sentence.strip().endswith("?"):
                asked.append((turn.index, sentence.strip()))

    if not asked:
        out.reason = "the candidate asked no questions"
        return out

    answered = 0
    for index, question in asked:
        reply = next((t for t in ctx.manager_turns if t.index > index), None)
        cues = content_words(question)
        if reply and (jaccard(content_words(reply.text), cues) >= 0.08 or len(reply.text) > 120):
            answered += 1
            out.evidence.append(ctx.evidence(reply.index, reply.text))

    value = answered / len(asked)
    out.value = round(value, 3)
    out.display = f"{answered} of {len(asked)} candidate questions answered"
    out.sub_score = transfer.hit_rate(value)
    out.evidence = out.evidence[:2]
    return out


def _cue_signal(
    ctx: Context,
    signal_id: str,
    label: str,
    weight: float,
    basis: str,
    patterns: list[re.Pattern[str]],
    *,
    segment: str | None = None,
    positive_only: bool = False,
) -> SignalResult:
    """Boolean cue detection over manager turns, optionally scoped to a segment."""
    out = _base(signal_id, label, weight, basis)
    turns = [
        t for t in ctx.manager_turns if segment is None or ctx.segments.get(t.index) == segment
    ]
    for turn in turns:
        for sentence in sentences(turn.text):
            if any(p.search(sentence) for p in patterns):
                out.value = 1.0
                out.display = "yes"
                out.sub_score = 10.0
                out.evidence.append(ctx.evidence(turn.index, sentence))
                return out

    out.value = 0.0
    out.display = "no"
    # A positive-only marker never costs a manager points; it only earns them.
    out.sub_score = None if positive_only else 0.0
    if positive_only:
        out.reason = "positive marker only — absence is not penalised"
    return out


def _agenda_set(ctx: Context) -> SignalResult:
    return _cue_signal(
        ctx,
        "agenda_set",
        "Agenda and duration stated",
        1.0,
        "SOURCED construct (Campion component 5; shipped as a scored signal by "
        "interview-intelligence products)",
        _AGENDA,
        segment=OPEN,
    )


def _next_steps(ctx: Context) -> SignalResult:
    """Next steps plus a timeline. Both, because "we'll be in touch" is not a close."""
    out = _cue_signal(
        ctx,
        "next_steps_stated",
        "Next steps and timeline at the close",
        1.5,
        "SOURCED (Hausknecht et al. 2004 — the information/feedback justice facet)",
        _NEXT_STEPS,
    )
    if out.sub_score == 10.0:
        has_timeline = any(p.search(t.text) for t in ctx.manager_turns for p in _TIMELINE)
        if not has_timeline:
            out.sub_score = 6.0
            out.display = "next steps stated, but no timeline"
    else:
        closing = [t for t in ctx.manager_turns if ctx.segments.get(t.index) == CLOSE]
        out.reason = "no closing next-steps statement found" if closing else "no close detected"
    return out


def _downside(ctx: Context) -> SignalResult:
    return _cue_signal(
        ctx,
        "downside_disclosed",
        "Honest preview of the hard parts",
        1.0,
        "SOURCED (Earnest, Allen & Landis 2011 — perceived organisational "
        "honesty is the mechanism behind realistic job previews)",
        _DOWNSIDE,
        positive_only=True,
    )


def _invite_fraction(ctx: Context) -> SignalResult:
    """How late in the session the candidate was invited to ask questions."""
    out = _base(
        "invite_questions_fraction",
        "Invited the candidate's questions",
        weight=1.0,
        basis="CALIBRATION. Note the genuine tension: Campion component 7 "
        "recommends deferring candidate questions; candidate-experience research "
        "rewards inviting them. Only never inviting is penalised",
    )
    invite = next(
        (i for i, s in sorted(ctx.segments.items()) if s == "CANDIDATE_Q"),
        None,
    )
    if invite is None:
        out.value = 0.0
        out.display = "never invited"
        out.sub_score = 0.0
        return out

    turn = next((t for t in ctx.turns if t.index == invite), None)
    fraction = (turn.elapsed_ms / ctx.duration_ms) if turn and ctx.duration_ms else 0.0
    out.value = round(fraction, 3)
    out.display = f"invited at {fraction:.0%} through the session"
    out.sub_score = 10.0
    out.evidence = [ctx.evidence(invite, turn.text if turn else "")]
    return out
