"""The judge layer's gate — spec section 6.

The deterministic engine is pinned by byte-identical regression in
`test_report_engine.py`. A judge cannot be pinned that way, so this file tests
the thing that *is* fixed about it: what the veto lets through.

Every test here drives `judge.overlay` with hand-written model output. No model
is called, and none needs to be — `overlay` is the whole of the judge except the
network hop, and keeping it pure is what makes the veto testable at all.
"""

import json
from pathlib import Path

import pytest

from candidate_agent import archetypes
from evaluation_agent.rubric import DEFAULT_RUBRIC
from report_engine import judge, validate
from report_engine.schema import SessionBundle
from report_engine.score import build_report

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "demo_turns.json"


def _bundle(**overrides) -> SessionBundle:
    raw = json.loads(FIXTURE.read_text())
    archetype = archetypes.get(raw.pop("persona_key"))
    raw["persona"] = {
        "archetype_key": archetype.key,
        "label": archetype.label,
        "must_discover": [s.__dict__ for s in archetype.must_discover],
        "session_beats": list(archetype.session_beats),
        "stresses": dict(archetype.stresses),
    }
    raw["rubric"] = DEFAULT_RUBRIC.model_dump()
    raw.update(overrides)
    return SessionBundle.model_validate(raw)


def _turn(bundle: SessionBundle, speaker: str):
    """The first turn by this speaker — a source of spans that really exist."""
    return next(t for t in bundle.turns if t.speaker == speaker)


def _judged(bundle: SessionBundle, raw: dict):
    return judge.overlay(build_report(bundle), bundle, raw, model_id="test-model")


EMPTY: dict = {"summary": "", "criteria": [], "findings": [], "must_discover": []}


# ------------------------------------------------------------------ spans ----


def test_a_span_that_is_not_in_the_transcript_is_rejected():
    bundle = _bundle()
    transcript = validate.Transcript(turns=bundle.turns)
    verdict = transcript.verify("I asked about her plans to start a family soon")
    assert not verdict.accepted
    assert "verbatim" in verdict.reason


def test_a_real_span_is_accepted_and_anchored_to_its_turn():
    bundle = _bundle()
    turn = _turn(bundle, "manager")
    verdict = validate.Transcript(turns=bundle.turns).verify(turn.text[:40])
    assert verdict.accepted
    assert verdict.evidence is not None
    assert verdict.evidence.turn_index == turn.index
    assert verdict.evidence.speaker == "manager"


def test_casing_and_spacing_do_not_break_a_real_quote():
    """A transcript's casing and line breaks are the transcriber's guess."""
    bundle = _bundle()
    span = _turn(bundle, "manager").text[:40]
    mangled = f"  {span.upper()}  ".replace(" ", "   ")
    assert validate.Transcript(turns=bundle.turns).verify(mangled).accepted


def test_a_span_too_short_to_identify_a_moment_is_rejected():
    bundle = _bundle()
    assert not validate.Transcript(turns=bundle.turns).verify("yes").accepted


# ------------------------------------------------------- surfaced verdicts ----


def test_a_fabricated_surfacing_claim_is_dropped_not_counted_as_a_miss():
    """Rule 1: an unevidenced verdict degrades to unmeasurable, never to False."""
    bundle = _bundle()
    target = bundle.persona.must_discover[0]
    report = _judged(
        bundle,
        EMPTY
        | {
            "must_discover": [
                {
                    "id": target.id,
                    "surfaced": True,
                    "evidence_span": "she told me she had run the whole region single handed",
                }
            ]
        },
    )
    signal = _surfaced(report)
    assert signal is not None
    assert not signal.measurable, "a dropped verdict must not become a measured zero"
    assert "no must-discover verdict survived" in signal.reason


def test_surfacing_credited_to_the_managers_own_words_is_rejected():
    """Rule 2: discovery is what the candidate revealed, not what the manager asked."""
    bundle = _bundle()
    manager_turn = _turn(bundle, "manager")
    verdict = validate.check_surfaced(
        validate.Transcript(turns=bundle.turns, acts=build_report(bundle).question_acts),
        manager_turn.text[:60],
    )
    assert not verdict.accepted
    assert "manager speaking" in verdict.reason


def test_a_candidate_answer_after_a_question_is_accepted():
    bundle = _bundle()
    report = build_report(bundle)
    first_act = min(a.turn_index for a in report.question_acts)
    answer = next(t for t in bundle.turns if t.speaker == "candidate" and t.index > first_act)
    verdict = validate.check_surfaced(
        validate.Transcript(turns=bundle.turns, acts=report.question_acts), answer.text[:60]
    )
    assert verdict.accepted
    assert verdict.evidence is not None
    assert verdict.evidence.speaker == "candidate"


def test_a_verdict_for_an_unknown_item_is_ignored():
    bundle = _bundle()
    report = _judged(
        bundle,
        EMPTY
        | {
            "must_discover": [
                {"id": "not-a-real-item", "surfaced": True, "evidence_span": "x" * 20}
            ]
        },
    )
    signal = _surfaced(report)
    assert signal is not None and not signal.measurable


def test_an_evidenced_surfacing_becomes_a_judged_signal_and_moves_the_score():
    """Rule 3: the boolean is validated, then code recomputes every number from it."""
    bundle = _bundle()
    plain = build_report(bundle)
    report = _judged(bundle, EMPTY | {"must_discover": _all_surfaced(bundle, plain)})

    signal = _surfaced(report)
    assert signal is not None and signal.measurable
    assert signal.source == "judged"

    before = next(c for c in plain.criteria if c.id == "structure").score
    after = next(c for c in report.criteria if c.id == "structure").score
    assert before != after, "a judged signal must reach the criterion it belongs to"
    assert plain.readiness_index != report.readiness_index


def _all_surfaced(bundle: SessionBundle, report) -> list[dict]:
    """Every must_discover item claimed surfaced, on one real candidate answer."""
    first_act = min(a.turn_index for a in report.question_acts)
    answer = next(t for t in bundle.turns if t.speaker == "candidate" and t.index > first_act)
    return [
        {"id": item.id, "surfaced": True, "evidence_span": answer.text[:60]}
        for item in bundle.persona.must_discover
    ]


def _surfaced(report):
    return next(
        (s for c in report.criteria for s in c.signals if s.id == judge.SURFACED_SIGNAL_ID),
        None,
    )


# -------------------------------------------------------------------- prose ----


@pytest.mark.parametrize(
    "text",
    [
        "You covered 4 of 5 role facts before closing.",
        "Talk ratio was 38%, which is healthy.",
        "Two gaps and 1 strength stood out.",
    ],
)
def test_prose_stating_a_number_is_rejected(text):
    """Numbers are computed and printed by code; prose that also states one can disagree."""
    verdict = validate.check_prose(text)
    assert not verdict.accepted
    assert "number" in verdict.reason


def test_a_number_inside_a_quotation_is_someone_elses_words():
    assert validate.check_prose(
        'You let "I was doing about 150% of target" go without a follow-up.'
    ).accepted


def test_a_narrative_longer_than_the_card_is_cut_not_printed():
    """The scorecard is four cards on one page; a paragraph pushes one off it."""
    bundle = _bundle()
    long_narrative = "You explained the role and answered the questions clearly. " * 8
    assert len(long_narrative) > validate.MAX_NARRATIVE
    report = _judged(
        bundle,
        EMPTY | {"criteria": [{"id": "clarity", "narrative": long_narrative, "bullets": []}]},
    )
    judged = next(c for c in report.criteria if c.id == "clarity")
    assert judged.narrative != long_narrative.strip()


def test_a_narrative_within_the_limit_is_printed():
    bundle = _bundle()
    written = "You explained the shift pattern and the incentive before asking for a commitment."
    report = _judged(
        bundle,
        EMPTY | {"criteria": [{"id": "clarity", "narrative": written, "bullets": []}]},
    )
    assert next(c for c in report.criteria if c.id == "clarity").narrative == written


def test_rejected_prose_leaves_the_composed_sentence_standing():
    bundle = _bundle()
    plain = build_report(bundle)
    report = _judged(bundle, EMPTY | {"summary": "You scored 60 out of 100 overall."})
    assert report.summary == plain.summary
    assert report.summary, "a veto must never leave the section blank"


def test_accepted_prose_replaces_the_composed_sentence():
    bundle = _bundle()
    written = "You ran a warm, well-structured round and explained the role clearly."
    report = _judged(bundle, EMPTY | {"summary": written})
    assert report.summary == written


# ----------------------------------------------------------------- bullets ----


def test_a_bullet_needs_a_real_quote_and_a_signal_that_exists():
    bundle = _bundle()
    plain = build_report(bundle)
    clarity = next(c for c in plain.criteria if c.id == "clarity")
    real_span = _turn(bundle, "manager").text[:40]

    report = _judged(
        bundle,
        EMPTY
        | {
            "criteria": [
                {
                    "id": "clarity",
                    "narrative": "You explained the shifts and the incentive clearly.",
                    "bullets": [
                        {
                            "signal_id": clarity.signals[0].id,
                            "polarity": "positive",
                            "text": "You walked through targets early.",
                            "evidence_span": real_span,
                        },
                        {
                            "signal_id": "no_such_signal",
                            "polarity": "negative",
                            "text": "You invented a signal.",
                            "evidence_span": real_span,
                        },
                        {
                            "signal_id": clarity.signals[0].id,
                            "polarity": "negative",
                            "text": "You said something that was never said.",
                            "evidence_span": "and then I promised her a company car",
                        },
                    ],
                }
            ]
        },
    )
    judged = next(c for c in report.criteria if c.id == "clarity")
    assert [b.text for b in judged.bullets] == ["You walked through targets early."]
    assert judged.narrative == "You explained the shifts and the incentive clearly."


def test_a_criterion_whose_bullets_all_fail_keeps_the_composed_ones():
    bundle = _bundle()
    plain = build_report(bundle)
    composed = next(c for c in plain.criteria if c.id == "clarity").bullets
    report = _judged(
        bundle,
        EMPTY
        | {
            "criteria": [
                {
                    "id": "clarity",
                    "narrative": "",
                    "bullets": [
                        {
                            "signal_id": "clarity_fact_coverage",
                            "polarity": "positive",
                            "text": "Made up.",
                            "evidence_span": "a sentence nobody in this interview said",
                        }
                    ],
                }
            ]
        },
    )
    assert [b.text for b in next(c for c in report.criteria if c.id == "clarity").bullets] == [
        b.text for b in composed
    ]


# ---------------------------------------------------------------- findings ----


def test_the_judge_writes_the_findings_code_selected_and_cannot_add_one():
    bundle = _bundle()
    plain = build_report(bundle)
    selected = {f.signal_id for f in plain.strengths + plain.gaps}
    target = plain.gaps[0]

    report = _judged(
        bundle,
        EMPTY
        | {
            "findings": [
                {
                    "signal_id": target.signal_id,
                    "headline": "You moved on before the answer was finished.",
                    "detail": "The first answer was accepted as given.",
                    "evidence_span": _turn(bundle, "manager").text[:40],
                },
                {
                    "signal_id": "a_signal_the_judge_wanted_to_add",
                    "headline": "You should also hear about this.",
                    "detail": "Invented.",
                    "evidence_span": _turn(bundle, "manager").text[:40],
                },
            ]
        },
    )
    assert {f.signal_id for f in report.strengths + report.gaps} == selected
    rewritten = next(f for f in report.gaps if f.signal_id == target.signal_id)
    assert rewritten.headline == "You moved on before the answer was finished."


def test_every_quote_on_a_judged_report_is_still_in_the_transcript():
    """The property the whole veto exists to hold."""
    bundle = _bundle()
    plain = build_report(bundle)
    report = _judged(
        bundle,
        {
            "summary": "You explained the role well and stopped probing one step early.",
            "criteria": [],
            "findings": [
                {
                    "signal_id": f.signal_id,
                    "headline": "You did a thing worth naming.",
                    "detail": "It showed up more than once.",
                    "evidence_span": "a line that appears nowhere in this session at all",
                }
                for f in plain.strengths + plain.gaps
            ],
            "must_discover": [],
        },
    )
    haystack = validate.Transcript(turns=bundle.turns)
    for finding in report.strengths + report.gaps + report.development_areas:
        for evidence in finding.evidence:
            # The bias signal stamps its category onto the quote it carries —
            # "[Salary history] ..." — so the anchor is what follows the label,
            # the same convention `test_report_engine` reads it by.
            quote = evidence.quote.split("] ")[-1]
            assert haystack.verify(quote).accepted, finding.signal_id


# ------------------------------------------------------------- provenance ----


def test_a_judged_report_says_so_and_an_unjudged_one_does_not():
    bundle = _bundle()
    assert build_report(bundle).provenance.judge_model == ""
    report = _judged(bundle, EMPTY)
    assert report.provenance.judge_model == "test-model"
    assert report.provenance.judge_version == judge.JUDGE_INSTRUCTIONS_VERSION


def test_an_unscoreable_session_is_returned_untouched():
    bundle = _bundle(scoring_options={"language_gate": True})
    turns = [
        {
            "index": i,
            "speaker": "manager" if i % 2 == 0 else "candidate",
            "text": "Aap apne bare mein kuch bataiye aur batayein ki yeh role kaisa lagta hai",
            "elapsed_ms": i * 1000,
        }
        for i in range(8)
    ]
    bundle = _bundle(turns=turns, scoring_options={"language_gate": True})
    report = build_report(bundle)
    assert report.unscoreable
    assert judge.overlay(report, bundle, EMPTY, model_id="test-model") is report


# ----------------------------------------------------------------- prompt ----


def test_the_prompt_carries_the_transcript_the_persona_and_the_measurements():
    bundle = _bundle()
    text = judge.prompt_for(build_report(bundle), bundle)
    assert bundle.job_card.job_title in text
    assert bundle.persona.must_discover[0].id in text
    assert _turn(bundle, "candidate").text[:40] in text
    assert "do not restate these numbers" in text


def test_the_judge_is_told_it_may_not_choose_the_findings():
    bundle = _bundle()
    plain = build_report(bundle)
    text = judge.prompt_for(plain, bundle)
    assert "Do not add or drop any" in text
    for finding in plain.strengths + plain.gaps:
        assert finding.signal_id in text
