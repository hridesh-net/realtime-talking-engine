"""The judge layer — spec section 6. One model call per session.

The judge writes sentences. It does not score, it does not select, and nothing
it says reaches the report without passing :mod:`report_engine.validate`.

What it is allowed to author:

* the **summary** — printed in the working rather than on the manager's
  pages, which open at the four competencies
* one **narrative** and up to three **bullets** per criterion
* the **headline and detail** of the strengths and gaps *code already selected*
* a **surfaced** verdict per ``must_discover`` item, each with a verbatim span

What it is not allowed to do, enforced rather than requested:

* **Choose which signals get written about.** Selection stays where §7 puts it —
  strengths are the highest sub-scores with valid evidence, gaps the lowest, and
  the judge is handed that list rather than asked for one.
* **State a number.** Every number is printed beside its prose by the renderer,
  computed by code. A judge that also writes numbers can disagree with them, and
  the reader has no way to tell which is right. Prose carrying a digit outside a
  quotation is rejected.
* **Cite a moment that did not happen.** Every span is matched verbatim against
  the transcript, and a `surfaced` verdict additionally has to be the candidate
  answering a question the manager asked.

A rejected claim falls back to the sentence
:mod:`report_engine.narrate` composed from the measurement, so a veto costs the
report some polish and never costs it a section.

**This package imports no first-party module, `llm` included.** The model
arrives as a structural type — anything with `generate_json` satisfies
:class:`JudgeModel`, and `llm.base.StructuredModel` does. Keeping the judge
duck-typed is what lets `report_engine` stay the one package in the repo that
depends on nothing, which is the property that makes
``python -m report_engine bundle.json`` genuinely standalone.
"""

from __future__ import annotations

from typing import Any, Protocol

from report_engine import narrate, validate
from report_engine.schema import (
    AssessmentReport,
    Bullet,
    Finding,
    SessionBundle,
    SignalResult,
)
from report_engine.score import build_report

#: Bumped whenever the prompt, the output schema or a veto rule changes. Stamped
#: on `Provenance.judge_version`: two reports whose prose was written under
#: different instructions are not the same artifact.
JUDGE_INSTRUCTIONS_VERSION = "v1"

#: Deterministic-adjacent, not deterministic. The regression suite pins the code
#: path with no judge at all; the judge path is tested for schema and evidence
#: validity instead — spec section 6.
TEMPERATURE = 0.1

#: The signal the judge's `must_discover` verdicts become. Distinct from
#: `discovery_attempted`, which counts whether the manager *aimed a question* at
#: each item: that one is countable and this one is not. It also reaches the
#: restraint items the counted signal deliberately excludes, which is the gap
#: `signals/structure.py` names in its own docstring.
SURFACED_SIGNAL_ID = "discovery_surfaced"


class JudgeModel(Protocol):
    """The one model method the judge needs. `llm.base.StructuredModel` satisfies it."""

    async def generate_json(
        self, *, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return one JSON object matching ``schema``."""
        ...


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_STR = {"type": "string"}

JUDGE_SCHEMA: dict[str, Any] = _obj(
    {
        "summary": _STR,
        "criteria": {
            "type": "array",
            "items": _obj(
                {
                    "id": _STR,
                    "narrative": _STR,
                    "bullets": {
                        "type": "array",
                        "items": _obj(
                            {
                                "signal_id": _STR,
                                "polarity": {"type": "string", "enum": ["positive", "negative"]},
                                "text": _STR,
                                "evidence_span": _STR,
                            },
                            ["signal_id", "polarity", "text", "evidence_span"],
                        ),
                    },
                },
                ["id", "narrative", "bullets"],
            ),
        },
        "findings": {
            "type": "array",
            "items": _obj(
                {
                    "signal_id": _STR,
                    "headline": _STR,
                    "detail": _STR,
                    "evidence_span": _STR,
                },
                ["signal_id", "headline", "detail", "evidence_span"],
            ),
        },
        "must_discover": {
            "type": "array",
            "items": _obj(
                {"id": _STR, "surfaced": {"type": "boolean"}, "evidence_span": _STR},
                ["id", "surfaced", "evidence_span"],
            ),
        },
    },
    ["summary", "criteria", "findings", "must_discover"],
)

SYSTEM = """You write the prose of an interviewer development report.

The manager being described conducted this interview against an AI candidate. \
They are the person assessed; the candidate is not.

Rules you must follow, because the report is checked against them and anything \
failing a check is thrown away:

1. Describe BEHAVIOUR, never the person. "You accepted the first answer and \
moved on" is allowed. "You are too easily impressed" is not. Feedback aimed at \
the person makes performance worse more often than it helps.
2. State NO NUMBERS. No scores, no counts, no percentages, no "two of five". \
Every number is printed next to your words by the report itself. Write "the \
growth path was never mentioned", not "four of five role facts were covered".
3. Every evidence_span must be copied VERBATIM from the transcript below — an \
exact substring of one turn, at least a dozen characters. Do not paraphrase, \
do not tidy the grammar, do not join two turns. A span that does not match \
exactly is discarded along with whatever you attached it to.
4. A must_discover item is "surfaced" only if the CANDIDATE said the thing, in \
answer to something the MANAGER asked. If the candidate volunteered it, or if \
you can only point at the manager's own question, it is not surfaced.
5. Write to the manager as "you". Keep every sentence short enough to read at a \
glance.

Say only what the transcript and the measurements support. Where you are not \
sure, say less."""


def _signal_table(report: AssessmentReport) -> str:
    """Every computed measurement, so the judge writes about what was measured."""
    lines = []
    for criterion in report.criteria:
        lines.append(f"\n[{criterion.id}] {criterion.label} — weight {criterion.weight:.0%}")
        for signal in criterion.signals:
            state = "not measurable" if not signal.measurable else signal.display
            lines.append(f"  - {signal.id} ({signal.label}): {state}")
    return "\n".join(lines)


def _transcript(bundle: SessionBundle) -> str:
    return "\n".join(
        f"[{t.elapsed_ms // 60000:02d}:{t.elapsed_ms // 1000 % 60:02d}] {t.speaker}: {t.text}"
        for t in bundle.turns
    )


def _must_discover(bundle: SessionBundle) -> str:
    if not bundle.persona.must_discover:
        return "(none recorded for this persona)"
    return "\n".join(
        f"  - {item.id}: {item.signal}"
        + (f" — surface it by: {item.how_to_surface}" if item.how_to_surface else "")
        for item in bundle.persona.must_discover
    )


def _selected(report: AssessmentReport) -> str:
    """The findings code picked. The judge writes them, it does not choose them."""
    chosen = report.strengths + report.gaps
    if not chosen:
        return "(none)"
    return "\n".join(
        f"  - {f.signal_id} ({'strength' if f in report.strengths else 'gap'}): {f.detail}"
        for f in chosen
    )


def prompt_for(report: AssessmentReport, bundle: SessionBundle) -> str:
    """The whole brief: the role, the persona's secrets, the numbers, the words."""
    return f"""ROLE INTERVIEWED FOR: {bundle.job_card.job_title}
{bundle.job_card.summary}

THE CANDIDATE WAS PLAYING: {bundle.persona.label or bundle.persona.archetype_key}
Things this candidate was holding back, which the manager had to draw out:
{_must_discover(bundle)}

MEASUREMENTS ALREADY COMPUTED (do not restate these numbers; write what they mean):
{_signal_table(report)}

FINDINGS ALREADY SELECTED — write a headline and a detail sentence for each of
these, and only these. Do not add or drop any:
{_selected(report)}

TRANSCRIPT:
{_transcript(bundle)}

Write:
- summary: ONE paragraph of at most 60 words on how the interview went and the
  single closest thing to work on. Anything longer is cut, not shortened. This
  is read by a trainer reviewing the session, not by the manager themselves.
- criteria: for each criterion id above, a narrative of AT MOST 40 WORDS and up
  to three bullets, each about one signal id from that criterion and each a
  single short sentence. Anything longer is cut, not shortened.
- findings: one entry per selected finding above, matched by signal_id.
- must_discover: one verdict per item above."""


async def apply(
    report: AssessmentReport, bundle: SessionBundle, model: JudgeModel
) -> AssessmentReport:
    """Run the judge over a scored report and return the report it earned.

    One call. A session with no numbers is returned untouched — there is nothing
    to write prose about, and the reason it was not scored is already on the page.
    """
    if report.unscoreable:
        return report
    raw = await model.generate_json(
        system=SYSTEM, prompt=prompt_for(report, bundle), schema=JUDGE_SCHEMA
    )
    return overlay(report, bundle, raw, model_id=getattr(model, "model_id", ""))


def overlay(
    report: AssessmentReport,
    bundle: SessionBundle,
    raw: dict[str, Any],
    *,
    model_id: str = "",
) -> AssessmentReport:
    """Everything after the call: validate, rescore if needed, then write prose.

    Pure and synchronous, so the veto can be tested against hand-written judge
    output without a model anywhere near it.
    """
    if report.unscoreable:
        # `apply` never calls the model for one of these, but `overlay` is public
        # and a stored judge response could still be replayed onto one. There is
        # no prose to write about a session that produced no numbers.
        return report
    transcript = validate.Transcript(turns=bundle.turns, acts=report.question_acts)

    surfaced = _surfaced_signal(transcript, bundle, raw.get("must_discover") or [])
    if surfaced is not None:
        # The verdicts changed a measurement, so every number downstream of it —
        # the criterion score, the readiness index, which findings were selected
        # — is recomputed by code from the validated booleans. Nothing is
        # patched in place, because a patched score is one code did not derive.
        report = build_report(bundle, extra_signals=[surfaced])

    _write_summary(report, raw.get("summary", ""))
    _write_criteria(report, transcript, raw.get("criteria") or [])
    _write_findings(report, transcript, raw.get("findings") or [])

    report.provenance.judge_model = model_id
    report.provenance.judge_version = JUDGE_INSTRUCTIONS_VERSION
    return report


def _surfaced_signal(
    transcript: validate.Transcript, bundle: SessionBundle, verdicts: list[dict[str, Any]]
) -> SignalResult | None:
    """The judge's `must_discover` verdicts, as one weighted signal.

    A verdict whose span fails either check is dropped from the denominator
    rather than counted against the manager: the judge failing to evidence
    something is not evidence that the manager missed it.
    """
    targets = {item.id: item for item in bundle.persona.must_discover}
    if not targets:
        return None

    out = SignalResult(
        id=SURFACED_SIGNAL_ID,
        label="What the candidate was hiding, actually drawn out",
        criterion="structure",
        weight=2.0,
        source="judged",
        basis="Persona ground truth read by the judge, spec section 6. Every "
        "verdict carries a verbatim span, and an unevidenced verdict is dropped "
        "from the denominator rather than scored as a miss",
    )

    judged_weight = 0.0
    hit_weight = 0.0
    dropped = 0
    for verdict in verdicts:
        target = targets.get(str(verdict.get("id", "")))
        if target is None:
            dropped += 1
            continue
        if not verdict.get("surfaced"):
            # A negative needs no evidence: "the manager never got to it" is a
            # claim about an absence, and absences have no span to quote.
            judged_weight += target.weight
            continue
        checked = validate.check_surfaced(transcript, str(verdict.get("evidence_span", "")))
        if not checked.accepted or checked.evidence is None:
            dropped += 1
            continue
        judged_weight += target.weight
        hit_weight += target.weight
        out.evidence.append(checked.evidence)

    if judged_weight <= 0:
        out.reason = (
            "no must-discover verdict survived the evidence check"
            if verdicts
            else "the judge returned no must-discover verdicts"
        )
        return out

    value = hit_weight / judged_weight
    out.value = round(value, 3)
    out.sub_score = round(value * 10, 2)
    out.display = f"{value:.0%} of what this candidate was hiding was actually drawn out"
    if dropped:
        out.display += f" ({dropped} unevidenced verdict(s) discarded)"
    out.evidence = out.evidence[:3]
    return out


def _clean(text: str, limit: int = validate.MAX_PROSE) -> str:
    """Prose the report may print, or empty if it broke a rule."""
    return text.strip() if validate.check_prose(text, limit).accepted else ""


def _write_summary(report: AssessmentReport, text: str) -> None:
    verdict = validate.check_prose(text, validate.MAX_SUMMARY)
    if verdict.accepted:
        report.summary = text.strip()


def _write_criteria(
    report: AssessmentReport, transcript: validate.Transcript, entries: list[dict[str, Any]]
) -> None:
    by_id = {c.id: c for c in report.criteria}
    for entry in entries:
        criterion = by_id.get(str(entry.get("id", "")))
        if criterion is None:
            continue
        narrative = _clean(str(entry.get("narrative", "")), validate.MAX_NARRATIVE)
        if narrative:
            criterion.narrative = narrative

        known = {s.id for s in criterion.signals}
        bullets: list[Bullet] = []
        for item in entry.get("bullets") or []:
            signal_id = str(item.get("signal_id", ""))
            text = _clean(str(item.get("text", "")), validate.MAX_BULLET)
            span = str(item.get("evidence_span", ""))
            if signal_id not in known or not text:
                continue
            if not validate.check_span(transcript, span).accepted:
                continue
            bullets.append(
                Bullet(
                    text=text,
                    polarity=str(item.get("polarity", "neutral")),
                    signal_id=signal_id,
                )
            )
        # All-or-nothing per criterion: a card showing one judged bullet beside
        # two composed ones reads as three claims of equal standing, and they are
        # not. Keep whichever set is whole.
        if bullets:
            criterion.bullets = bullets[: narrate.BULLET_COUNT]


def _write_findings(
    report: AssessmentReport, transcript: validate.Transcript, entries: list[dict[str, Any]]
) -> None:
    written = {str(e.get("signal_id", "")): e for e in entries}
    for finding in report.strengths + report.gaps + report.development_areas:
        entry = written.get(finding.signal_id)
        if entry is None:
            continue
        headline = _clean(str(entry.get("headline", "")))
        detail = _clean(str(entry.get("detail", "")))
        if not headline:
            continue
        finding.headline = headline
        if detail:
            finding.detail = detail
        _requote(finding, transcript, str(entry.get("evidence_span", "")))


def _requote(finding: Finding, transcript: validate.Transcript, span: str) -> None:
    """Prefer the judge's quote when it is real, keep the code-chosen one when not."""
    verdict = validate.check_span(transcript, span)
    if verdict.accepted and verdict.evidence is not None:
        others = [e for e in finding.evidence if e.turn_index != verdict.evidence.turn_index]
        finding.evidence = [verdict.evidence, *others[:1]]


__all__ = [
    "JUDGE_INSTRUCTIONS_VERSION",
    "JUDGE_SCHEMA",
    "SURFACED_SIGNAL_ID",
    "TEMPERATURE",
    "JudgeModel",
    "apply",
    "overlay",
    "prompt_for",
]
