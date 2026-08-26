"""Structured Interviewing signals — spec section 5.A.

Evidence base: structured interviews validate at r = .42 against ~.19 for
unstructured (Sackett, Zhang, Berry & Lievens 2022), and Huffcutt & Arthur
(1994) show validity climbing .20 -> .35 -> .56 -> .57 across four structure
levels. The Level III to IV gain is +.01, so probing is not penalised here:
banning follow-ups buys nothing.
"""

from __future__ import annotations

from report_engine import transfer
from report_engine.acts import root_questions
from report_engine.schema import SignalResult
from report_engine.signals.context import Context, load_pack
from report_engine.text import compile_all, content_words, jaccard

CRITERION = "structure"

#: Candidate-answer cues for the Result element of STAR. Numbers count: a result
#: that cannot be quantified is usually a claim, not a result.
_RESULT_CUES = compile_all(
    [
        r"\bas a result\b",
        r"\bwe ended up\b",
        r"\bwhich (meant|led to|got us)\b",
        r"\bin the end\b",
        r"\bfinally\b",
        r"\b\d+\s*(%|percent|lakh|crore|k\b)",
        r"\bwent (up|down) (by|to)\b",
        r"\bclosed\b",
        r"\bhit\b",
    ]
)


def extract(ctx: Context) -> list[SignalResult]:
    """Every structure signal for this session."""
    return [
        _discovery_attempted(ctx),
        _behavioural_share(ctx),
        _probe_rate(ctx),
        _star_result_rate(ctx),
        _closed_share(ctx),
        _leading_count(ctx),
        _competency_coverage(ctx),
        _question_count(ctx),
    ]


def _base(signal_id: str, label: str, weight: float, basis: str) -> SignalResult:
    return SignalResult(id=signal_id, label=label, criterion=CRITERION, weight=weight, basis=basis)


#: `must_discover` items are not all "surface it by asking", and two different
#: authors write them:
#:
#: * A **catalog archetype** writes from the interviewer's side, so most items
#:   read "Ask for the mechanism, the number, or the decision behind it". Some
#:   are deliberate restraint - "Move back to the role *without* asking a single
#:   follow-up" - and scoring those by question-overlap credits the manager for
#:   doing exactly the wrong thing.
#: * A **composed persona** is written from the candidate's side by the casting
#:   agent: "Offer an easy win and see if real depth appears". Those are stage
#:   directions for the persona, not questions for the manager, so no amount of
#:   question-matching can measure them.
#:
#: Only items that describe a question the interviewer should ask are counted.
_RESTRAINT_CUES = compile_all(
    [
        r"\bwithout\b",
        r"\brather than\b",
        r"\binstead of\b",
        r"\bnot\b",
        r"\bnever\b",
        r"\bleave it\b",
        r"\bmove (back|on)\b",
    ]
)
_ASK_CUES = compile_all([r"^\s*(ask|probe|compare|request|push|challenge)\b"])


def _is_ask_item(how_to_surface: str) -> bool:
    """Whether this item describes a question the interviewer should ask.

    Deliberately an allowlist. Anything that is not recognisably an instruction
    to ask something is left to the judge, because the failure mode of guessing
    wrong here is a score that means the opposite of what it says.
    """
    if any(p.search(how_to_surface) for p in _RESTRAINT_CUES):
        return False
    return any(p.search(how_to_surface) for p in _ASK_CUES)


def _discovery_attempted(ctx: Context) -> SignalResult:
    """Did the manager aim a question at each thing the persona is hiding?

    The persona's `must_discover` list is the fixed denominator that makes two
    managers comparable (spec section 1). Two honest limits on what is counted
    here:

    * Whether a signal was actually *surfaced* needs reading comprehension and
      belongs to the judge. Whether it was *asked about* is countable.
    * Only the items whose `how_to_surface` describes asking are counted at all.
      A persona like `cooperative_trap` is mostly restraint items - the correct
      behaviour is to *not* ask - and crediting a question there would invert
      the measurement. The display says how much of the persona's weight this
      signal could actually reach.
    """
    out = _base(
        "discovery_attempted",
        "Aimed at what the candidate was hiding",
        weight=2.0,
        basis="Persona ground truth - fixed denominator, spec section 1. "
        "Counts only the ask-shaped items; restraint and statement items are "
        "judge-only",
    )
    targets = ctx.bundle.persona.must_discover
    if not targets:
        out.reason = "the bundle carried no persona must-discover list"
        return out

    askable = [t for t in targets if _is_ask_item(t.how_to_surface)]
    total_weight = sum(t.weight for t in targets)
    ask_weight = sum(t.weight for t in askable)
    if not askable:
        out.reason = (
            f"none of this persona's {len(targets)} signals describes a question "
            "the interviewer should ask - they are restraint items, or stage "
            "directions for the persona - so only the judge can assess them"
        )
        return out

    hit_weight = 0.0
    for target in askable:
        cues = content_words(f"{target.signal} {target.how_to_surface}")
        for act in ctx.acts:
            if jaccard(content_words(act.text), cues) >= 0.08:
                hit_weight += target.weight
                out.evidence.append(ctx.evidence(act.turn_index, act.text))
                break

    value = hit_weight / ask_weight
    out.value = round(value, 3)
    coverage = ask_weight / total_weight if total_weight else 0.0
    out.display = f"{value:.0%} of the ask-shaped signals were asked about"
    if coverage < 1.0:
        out.display += (
            f" (only {coverage:.0%} of this persona's weight is ask-shaped; "
            "the rest is restraint, judged separately)"
        )
    out.sub_score = transfer.hit_rate(value)
    return out


def _behavioural_share(ctx: Context) -> SignalResult:
    """Past-behaviour questions as a share of all questions."""
    out = _base(
        "behavioural_share",
        "Behavioural (STAR) questions",
        weight=1.5,
        basis="SOURCED direction (past-behaviour r=.56 vs situational .45, "
        "Taylor & Small 2002); CALIBRATION cut point 0.40",
    )
    if not ctx.acts:
        out.reason = "no questions were asked"
        return out
    hits = [a for a in ctx.acts if a.type == "behavioural"]
    value = len(hits) / len(ctx.acts)
    out.value = round(value, 3)
    out.display = f"{len(hits)} of {len(ctx.acts)} questions were behavioural ({value:.0%})"
    out.sub_score = transfer.linear_up(value, 0.0, 0.40)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in hits[:3]]
    return out


def _probe_rate(ctx: Context) -> SignalResult:
    """Follow-up probes per root question."""
    out = _base(
        "probe_rate",
        "Follow-up probing",
        weight=1.5,
        basis="SOURCED direction (cognitive-interview meta-analysis, Memon, "
        "Meissner & Fraser 2010); CALIBRATION cut point 1.0",
    )
    roots = root_questions(ctx.acts)
    if not roots:
        out.reason = "no questions were asked"
        return out
    probes = [a for a in ctx.acts if a.is_probe]
    value = len(probes) / len(roots)
    out.value = round(value, 3)
    out.display = f"{len(probes)} probes across {len(roots)} topics ({value:.2f} per topic)"
    out.sub_score = transfer.linear_up(value, 0.0, 1.0)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in probes[:3]]
    return out


def _star_result_rate(ctx: Context) -> SignalResult:
    """How often a behavioural question actually reached a Result."""
    out = _base(
        "star_result_rate",
        "Behavioural answers that reached a Result",
        weight=1.0,
        basis="CALIBRATION. STAR completeness is a practitioner construct (DDI), "
        "not a validated mediator of interview validity — reported, not over-weighted",
    )
    behavioural = [a for a in ctx.acts if a.type == "behavioural"]
    if not behavioural:
        out.reason = "no behavioural questions were asked"
        return out

    reached = 0
    for act in behavioural:
        answer = next(
            (t for t in ctx.candidate_turns if t.index > act.turn_index),
            None,
        )
        if answer and any(p.search(answer.text) for p in _RESULT_CUES):
            reached += 1
            out.evidence.append(ctx.evidence(answer.index, answer.text))

    value = reached / len(behavioural)
    out.value = round(value, 3)
    out.display = f"{reached} of {len(behavioural)} behavioural answers reached a result"
    out.sub_score = transfer.linear_up(value, 0.0, 0.6)
    out.evidence = out.evidence[:2]
    return out


def _closed_share(ctx: Context) -> SignalResult:
    """Closed questions as a share of all questions. Lower is better."""
    out = _base(
        "closed_share",
        "Closed-question load",
        weight=1.0,
        basis="SOURCED direction (open questions yield longer, more accurate "
        "answers — Oxburgh, Myklebust & Grant 2010); CALIBRATION band 0.35-0.70",
    )
    if not ctx.acts:
        out.reason = "no questions were asked"
        return out
    hits = [a for a in ctx.acts if a.type == "closed"]
    value = len(hits) / len(ctx.acts)
    out.value = round(value, 3)
    out.display = f"{len(hits)} of {len(ctx.acts)} questions were closed ({value:.0%})"
    out.sub_score = transfer.linear_down(value, 0.35, 0.70)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in hits[:2]]
    return out


def _leading_count(ctx: Context) -> SignalResult:
    """Leading questions, which manufacture the answer they expect."""
    out = _base(
        "leading_count",
        "Leading questions",
        weight=1.0,
        basis="SOURCED direction (Snyder & Swann 1978 — confirmatory questioning "
        "produces confirming behaviour)",
    )
    hits = [a for a in ctx.acts if a.type == "leading"]
    out.value = float(len(hits))
    out.display = f"{len(hits)} leading question(s)"
    out.sub_score = transfer.penalty_count(len(hits), step=3.0)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in hits[:3]]
    return out


def _competency_coverage(ctx: Context) -> SignalResult:
    """How much of the role family's competency list was touched."""
    out = _base(
        "competency_coverage",
        "Competency coverage",
        weight=1.5,
        basis="SOURCED (Campion, Palmer & Campion 1997, component 1: job-analysis-based content)",
    )
    configured = [s for s in ctx.bundle.report_config.skills if s.strip()]
    if configured:
        # An org that named its own competencies knows the role better than a
        # shipped role-family list does. Cues are derived from the skill name
        # itself, which is cruder than the curated pack and is why the pack
        # remains the default rather than the fallback of last resort.
        family = [
            {"id": s.lower().replace(" ", "_"), "label": s, "cues": _cues_for(s)}
            for s in configured
        ]
    else:
        pack = load_pack("competencies")
        family = pack["families"].get(ctx.bundle.job_card.role_family)
    if not family:
        out.reason = f"no competency list for role family '{ctx.bundle.job_card.role_family}'"
        return out

    asked = " ".join(a.text for a in ctx.acts).lower()
    covered = [c for c in family if any(str(cue) in asked for cue in c["cues"])]
    value = len(covered) / len(family)
    out.value = round(value, 3)
    missed = [str(c["label"]) for c in family if c not in covered]
    out.display = f"{len(covered)} of {len(family)} competencies touched"
    if missed:
        out.display += f" — missed: {', '.join(missed)}"
    out.sub_score = transfer.linear_up(value, 0.4, 1.0)
    return out


def _cues_for(skill: str) -> list[str]:
    """Match cues for a skill the org named itself.

    Stopwords are dropped so "Target orientation" matches a question about
    targets without also matching every sentence containing "orientation".
    """
    return [w for w in content_words(skill) if len(w) > 3]


def _question_count(ctx: Context) -> SignalResult:
    """Total root questions — more questions sample more behaviour."""
    out = _base(
        "question_count",
        "Questions asked",
        weight=0.5,
        basis="SOURCED direction (Campion component 5: more questions = better "
        "behaviour sample); CALIBRATION band 4-12",
    )
    roots = root_questions(ctx.acts)
    out.value = float(len(roots))
    out.display = f"{len(roots)} distinct questions, {len(ctx.acts)} including probes"
    out.sub_score = transfer.plateau(float(len(roots)), 8.0, 20.0, 40.0)
    return out
