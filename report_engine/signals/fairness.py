"""Fair & Inclusive signals — spec section 5.C.

Nothing here caps or fails a score. A protected-topic hit lowers this criterion
and raises a prominent flag, matching the standing product rule that the report
is an analytical estimate rather than a gate.

Adverse impact is deliberately absent: the EEOC four-fifths rule compares
selection rates across groups of applicants and is undefined for one interview.
It belongs on the cohort dashboard.
"""

from __future__ import annotations

import re

from report_engine import transfer
from report_engine.schema import SignalResult
from report_engine.signals.context import Context, load_pack
from report_engine.text import content_words, jaccard, sentences

CRITERION = "fairness"

#: Kanze, Huang, Conley & Higgins (2018): investors asked women prevention-framed
#: questions roughly 2:1, and each extra prevention question tracked ~$3.8M less
#: raised. Per session this is descriptive only — differential framing needs two
#: candidates before it is a bias claim.
_PROMOTION = re.compile(
    r"\b(achieve|achieved|grow|growth|win|winning|gain|opportunit\w+|ambiti\w+|"
    r"aspire|potential|best|succeed|success|upside|scale)\b",
    re.IGNORECASE,
)
_PREVENTION = re.compile(
    r"\b(avoid|risk|risks|safe|safety|prevent|protect|mistake|mistakes|fail|"
    r"failure|problem|problems|worry|concern|defend|lose|loss|careful)\b",
    re.IGNORECASE,
)

_ACCOMMODATION = re.compile(
    r"\b(reasonable adjustment|accommodat\w+|anything (we|i) (can|should) do to "
    r"(help|support)|do you need anything|any support you need|make this easier)\b",
    re.IGNORECASE,
)

_NAME_CHECK = re.compile(
    r"\b(am i (saying|pronouncing) (that|your name) (right|correctly)|"
    r"how do you (say|pronounce) (your name|that)|did i (get|say) that right|"
    r"what (do you|would you) (like to be|prefer to be) called|"
    r"do you go by)\b",
    re.IGNORECASE,
)


def extract(ctx: Context) -> list[SignalResult]:
    """Every fairness signal for this session."""
    return [
        _protected_topics(ctx),
        _volunteered_detail_handling(ctx),
        _confirmatory_ratio(ctx),
        _framing_balance(ctx),
        _accommodation(ctx),
        _name_confirmed(ctx),
        _interruptions(ctx),
    ]


def _base(signal_id: str, label: str, weight: float, basis: str) -> SignalResult:
    return SignalResult(id=signal_id, label=label, criterion=CRITERION, weight=weight, basis=basis)


def _protected_topics(ctx: Context) -> SignalResult:
    """Questions on protected or high-risk topics, by jurisdiction pack."""
    pack = load_pack(ctx.bundle.jurisdiction.lower())
    out = _base(
        "protected_topic_hits",
        "Protected-topic questions",
        weight=3.0,
        basis=f"LEGAL — pack {pack['pack_version']}. Category is 'unlawful or "
        "high-risk inquiry', not 'illegal question': under most law the question "
        "is evidence of intent rather than an offence in itself",
    )
    compiled = [
        (c["id"], c["label"], re.compile(p, re.IGNORECASE), c["alternative"])
        for c in pack["categories"]
        for p in c["patterns"]
    ]

    seen: set[str] = set()
    for turn in ctx.manager_turns:
        for sentence in sentences(turn.text):
            for cat_id, label, pattern, _alt in compiled:
                if pattern.search(sentence) and cat_id not in seen:
                    seen.add(cat_id)
                    out.evidence.append(ctx.evidence(turn.index, f"[{label}] {sentence}"))

    out.value = float(len(seen))
    topics = ", ".join(sorted(t.replace("_", " ") for t in seen))
    out.display = (
        "none detected"
        if not seen
        else f"{len(seen)} {'category' if len(seen) == 1 else 'categories'}: {topics}"
    )
    out.sub_score = transfer.penalty_count(len(seen), step=4.0)
    return out


def _volunteered_detail_handling(ctx: Context) -> SignalResult:
    """When the candidate volunteers a protected detail, was it left alone?

    A candidate may say anything about themselves; the rule constrains the
    interviewer, not them. The failure mode is the *well-meant* follow-up -
    `cooperative_trap` names it explicitly ("Asks a warm, well-meant follow-up
    about the personal detail"), and it is the single heaviest thing that
    persona is testing.

    Countable because both halves are: the volunteering is a protected-topic
    pattern on a candidate turn, and pursuing it is a manager question in the
    next two turns that returns to the same topic.
    """
    pack = load_pack(ctx.bundle.jurisdiction.lower())
    out = _base(
        "volunteered_detail_handling",
        "Handling of a volunteered personal detail",
        weight=2.0,
        basis="Persona ground truth (`session_beats`) crossed with the "
        f"jurisdiction pack {pack['pack_version']}. The candidate may volunteer "
        "anything; the rule constrains the interviewer",
    )
    compiled = [
        (c["id"], c["label"], re.compile(p, re.IGNORECASE))
        for c in pack["categories"]
        for p in c["patterns"]
    ]

    volunteered: list[tuple[int, str, str, str]] = []
    for turn in ctx.candidate_turns:
        for sentence in sentences(turn.text):
            for cat_id, label, pattern in compiled:
                if pattern.search(sentence):
                    volunteered.append((turn.index, cat_id, label, sentence))
                    break

    if not volunteered:
        out.reason = "the candidate volunteered no protected personal detail"
        return out

    handled = 0
    for turn_index, cat_id, label, sentence in volunteered:
        follow_ups = [t for t in ctx.manager_turns if t.index > turn_index][:2]
        indexes = {t.index for t in follow_ups}
        pursued = any(
            act.turn_index in indexes
            and (
                act.protected_topic == cat_id
                or jaccard(content_words(act.text), content_words(sentence)) >= 0.20
            )
            for act in ctx.acts
        )
        if pursued:
            offending = next(a for a in ctx.acts if a.turn_index in indexes)
            out.evidence.append(
                ctx.evidence(offending.turn_index, f"[pursued {label}] {offending.text}")
            )
        else:
            handled += 1
            out.evidence.append(ctx.evidence(turn_index, f"[{label}, left alone] {sentence}"))

    value = handled / len(volunteered)
    out.value = round(value, 3)
    out.display = (
        f"{handled} of {len(volunteered)} volunteered detail(s) acknowledged and left alone"
    )
    out.sub_score = transfer.hit_rate(value)
    return out


def _confirmatory_ratio(ctx: Context) -> SignalResult:
    """Leading questions as a share of all questions."""
    out = _base(
        "confirmatory_ratio",
        "Confirmatory questioning",
        weight=1.5,
        basis="SOURCED (Snyder & Swann 1978 — questions chosen to confirm a "
        "prior hypothesis produce the confirming behaviour they look for)",
    )
    if not ctx.acts:
        out.reason = "no questions were asked"
        return out
    leading = [a for a in ctx.acts if a.type == "leading"]
    value = len(leading) / len(ctx.acts)
    out.value = round(value, 3)
    out.display = f"{len(leading)} of {len(ctx.acts)} questions were leading ({value:.0%})"
    out.sub_score = transfer.linear_down(value, 0.0, 0.25)
    out.evidence = [ctx.evidence(a.turn_index, a.text) for a in leading[:3]]
    return out


def _framing_balance(ctx: Context) -> SignalResult:
    """Promotion versus prevention framing across the manager's questions."""
    out = _base(
        "promotion_prevention_balance",
        "Question framing (promotion vs prevention)",
        weight=0.0,
        basis="SOURCED metric (Kanze, Huang, Conley & Higgins 2018). "
        "DESCRIPTIVE per session — differential framing is only a bias claim "
        "across two or more candidates",
    )
    if not ctx.acts:
        out.reason = "no questions were asked"
        return out
    promotion = sum(1 for a in ctx.acts if _PROMOTION.search(a.text))
    prevention = sum(1 for a in ctx.acts if _PREVENTION.search(a.text))
    total = promotion + prevention
    if total == 0:
        out.reason = "no framed questions to compare"
        return out
    out.value = round(promotion / total, 3)
    out.display = f"{promotion} promotion-framed, {prevention} prevention-framed"
    # Deliberately never scored. One session cannot distinguish a manager who
    # frames questions differently for different candidates - which is the
    # actual bias finding - from one who simply asked about risk today. Scoring
    # it per session manufactures a gap out of a single question.
    out.reason = "descriptive only - differential framing is a cohort measure, not a session one"
    return out


def _accommodation(ctx: Context) -> SignalResult:
    """Offering adjustments. A bonus, never a penalty."""
    out = _base(
        "accommodation_offered",
        "Offered adjustments or support",
        weight=0.5,
        basis="LEGAL basis (ADA duty; UK Equality Act s.60 expressly permits "
        "adjustment questions). POSITIVE MARKER ONLY — no effect-size research "
        "exists, so absence is never penalised",
    )
    for turn in ctx.manager_turns:
        if _ACCOMMODATION.search(turn.text):
            out.value, out.display, out.sub_score = 1.0, "yes", 10.0
            out.evidence = [ctx.evidence(turn.index, turn.text)]
            return out
    out.value, out.display = 0.0, "not offered"
    out.reason = "positive marker only — absence is not penalised"
    return out


def _name_confirmed(ctx: Context) -> SignalResult:
    """Checking how to say the candidate's name. A bonus, never a penalty."""
    out = _base(
        "name_confirmed",
        "Checked name pronunciation",
        weight=0.5,
        basis="INDUSTRY evidence only (NameCoach / Race Equality Matters "
        "surveys); no outcome study found. POSITIVE MARKER ONLY",
    )
    for turn in ctx.manager_turns:
        if _NAME_CHECK.search(turn.text):
            out.value, out.display, out.sub_score = 1.0, "yes", 10.0
            out.evidence = [ctx.evidence(turn.index, turn.text)]
            return out
    out.value, out.display = 0.0, "not checked"
    out.reason = "positive marker only — absence is not penalised"
    return out


def _interruptions(ctx: Context) -> SignalResult:
    """Intrusive interruptions per candidate speaking-minute. Voice only."""
    out = SignalResult(
        id="intrusive_interruption_rate",
        label="Interruptions",
        criterion=CRITERION,
        modality="voice",
        weight=1.0,
        basis="SOURCED (Zimmerman & West operational definitions; Anderson & "
        "Leaper 1998 meta-analysis, intrusive-interruption d = .33)",
    )
    out.reason = (
        "not measurable in a text session"
        if not ctx.is_voice
        else "needs recording-derived timings — spec phase 7"
    )
    return out
