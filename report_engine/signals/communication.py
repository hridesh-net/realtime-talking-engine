"""Communication & Presence signals — spec section 5.D.

Talk share is measured in the ASSESS segment only. The open and the close are
where role-clarity behaviour lives and where manager talk *should* spike;
penalising it there would score the same behaviour twice, once as a clarity
positive and once as a communication negative.
"""

from __future__ import annotations

import re

from report_engine import transfer
from report_engine.schema import SignalResult
from report_engine.segment import ASSESS
from report_engine.signals.context import Context
from report_engine.text import compile_all, sentences, words

CRITERION = "communication"

_GREETING = compile_all(
    [
        r"\b(good (morning|afternoon|evening)|hello|hi there|welcome)\b",
        r"\bthanks? (for )?(joining|coming|making the time|taking the time)\b",
        r"\bnice to (meet|see) you\b",
    ]
)

_SELF_INTRO = compile_all(
    [
        r"\bi'?m\s+[A-Z][a-z]+",
        r"\bmy name is\b",
        r"\bi (head|lead|manage|run|look after)\b",
        r"\bi'?m the\b",
    ]
)

_FILLERS = re.compile(r"\b(um|uh|erm|hmm|like|you know|i mean|basically|actually)\b", re.IGNORECASE)


def extract(ctx: Context) -> list[SignalResult]:
    """Every communication signal for this session."""
    return [
        _talk_share(ctx),
        _longest_monologue(ctx),
        _compound_rate(ctx),
        _greeting(ctx),
        _self_intro(ctx),
        _pace_advisory(ctx),
    ]


def _base(signal_id: str, label: str, weight: float, basis: str) -> SignalResult:
    return SignalResult(id=signal_id, label=label, criterion=CRITERION, weight=weight, basis=basis)


def _talk_share(ctx: Context) -> SignalResult:
    """Manager share of words during assessment."""
    out = _base(
        "manager_talk_share",
        "Talk-to-listen ratio (assessment only)",
        weight=2.0,
        basis="No peer-reviewed optimum exists for selection interviews. "
        "INDUSTRY proxies: Gong's 25k+ sales calls put the ideal at ~43% with "
        "win-rate falloff past ~65%; BrightHire's hiring guidance is ~20/80. "
        "CALIBRATION bands 20-40%, decaying to 65%",
    )
    assess = [t for t in ctx.turns if ctx.segments.get(t.index) == ASSESS]
    manager = sum(len(words(t.text)) for t in assess if t.speaker == "manager")
    candidate = sum(len(words(t.text)) for t in assess if t.speaker == "candidate")
    total = manager + candidate
    if total == 0:
        out.reason = "no assessment segment was detected"
        return out

    value = manager / total
    out.value = round(value, 3)
    unit = "speaking time" if ctx.is_voice else "words (text session — word share, not time)"
    out.display = f"manager {value:.0%} / candidate {1 - value:.0%} of {unit}"
    out.sub_score = transfer.plateau(value, 0.20, 0.40, 0.65)
    return out


def _longest_monologue(ctx: Context) -> SignalResult:
    """The manager's longest single turn."""
    out = _base(
        "longest_monologue",
        "Longest manager turn",
        weight=1.0,
        basis="INDUSTRY (shipped by Gong and BrightHire as a coaching signal); "
        "CALIBRATION threshold 120 words",
    )
    if not ctx.manager_turns:
        out.reason = "the manager said nothing"
        return out
    longest = max(ctx.manager_turns, key=lambda t: len(words(t.text)))
    count = len(words(longest.text))
    out.value = float(count)
    out.display = f"{count} words"
    out.sub_score = transfer.linear_down(float(count), 120.0, 320.0)
    if count > 120:
        out.evidence = [ctx.evidence(longest.index, longest.text)]
    return out


def _compound_rate(ctx: Context) -> SignalResult:
    """Double-barrelled questions — two asks in one breath."""
    out = _base(
        "compound_question_rate",
        "Compound questions",
        weight=1.0,
        basis="Rubric text: 'clear single questions, no compounds'. A compound "
        "question lets the candidate answer the easy half",
    )
    if not ctx.acts:
        out.reason = "no questions were asked"
        return out
    hits = [a for a in ctx.acts if a.type == "double_barrelled"]
    value = len(hits) / len(ctx.acts)
    out.value = round(value, 3)
    out.display = f"{len(hits)} of {len(ctx.acts)} questions asked two things at once"
    out.sub_score = transfer.linear_down(value, 0.0, 0.30)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in hits[:2]]
    return out


def _greeting(ctx: Context) -> SignalResult:
    out = _base("greeting", "Greeted the candidate", 1.0, "Rubric text; BRD criterion 4")
    for turn in ctx.manager_turns[:3]:
        for sentence in sentences(turn.text):
            if any(p.search(sentence) for p in _GREETING):
                out.value, out.display, out.sub_score = 1.0, "yes", 10.0
                out.evidence = [ctx.evidence(turn.index, sentence)]
                return out
    out.value, out.display, out.sub_score = 0.0, "no", 0.0
    return out


def _self_intro(ctx: Context) -> SignalResult:
    out = _base("self_intro", "Introduced themselves", 1.0, "Rubric text; BRD criterion 4")
    for turn in ctx.manager_turns[:3]:
        for sentence in sentences(turn.text):
            if any(p.search(sentence) for p in _SELF_INTRO):
                out.value, out.display, out.sub_score = 1.0, "yes", 10.0
                out.evidence = [ctx.evidence(turn.index, sentence)]
                return out
    out.value, out.display, out.sub_score = 0.0, "no", 0.0
    return out


def _pace_advisory(ctx: Context) -> SignalResult:
    """Pace and fillers. Shown, never scored — the wizard specification is explicit.

    The research also says the folk metric is wrong: filled-pause frequency
    *rises* with proficiency (C1 8.6/min vs A2 3.1/min, Tavakoli et al.) and
    normalised per syllable does not discriminate level at all (r = -.08, n.s.,
    Yan et al.). Counting "um" measures a habit, not a competence.
    """
    out = SignalResult(
        id="pace_and_fillers",
        label="Pace and fillers (advisory)",
        criterion=CRITERION,
        weight=0.0,
        basis="ADVISORY, NEVER SCORED — wizard specification. Filled-pause rate "
        "does not discriminate proficiency (Yan et al., r = -.08 n.s.)",
    )
    manager_words = [w for t in ctx.manager_turns for w in words(t.text)]
    if not manager_words:
        out.reason = "the manager said nothing"
        return out
    fillers = sum(len(_FILLERS.findall(t.text)) for t in ctx.manager_turns)
    per_hundred = fillers / len(manager_words) * 100
    out.value = round(per_hundred, 2)
    out.display = f"{fillers} fillers across {len(manager_words)} words ({per_hundred:.1f}/100)"
    out.reason = "advisory only — never contributes to a score"
    return out
