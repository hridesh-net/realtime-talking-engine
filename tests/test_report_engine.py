"""The report engine's offline gate.

The load-bearing test is determinism: re-running the engine on a stored session
must produce byte-identical output, because "last month's 62" and "this month's
62" are only the same 62 if it does.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from candidate_agent import archetypes
from evaluation_agent.rubric import DEFAULT_RUBRIC
from report_engine.acts import classify, extract, is_question
from report_engine.render import to_html, to_json
from report_engine.schema import SessionBundle, Turn
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


# ------------------------------------------------------------- determinism ----


def test_the_same_bundle_produces_byte_identical_output():
    first = to_json(build_report(_bundle()))
    second = to_json(build_report(_bundle()))
    assert first == second


def test_html_is_reproducible_too():
    assert to_html(build_report(_bundle())) == to_html(build_report(_bundle()))


def test_the_readiness_index_is_a_whole_number_in_range():
    report = build_report(_bundle())
    assert report.readiness_index is not None
    assert 0 <= report.readiness_index <= 100
    assert report.band in {b.label for b in DEFAULT_RUBRIC.bands}


# ----------------------------------------------------------------- typing ----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tell me about a time you missed a target.", "behavioural"),
        ("What would you do if a customer walked out?", "situational"),
        ("So you're not comfortable with cold calls, right?", "leading"),
        ("Did you hit your numbers?", "closed"),
        ("What was your part in that, specifically?", "open_other"),
        ("And what was your current CTC, and what are you looking for?", "double_barrelled"),
    ],
)
def test_question_types_are_classified_by_rule(text, expected):
    assert classify(text) == expected


def test_leading_beats_behavioural_in_precedence():
    """A leading behavioural question is still leading — it manufactures its answer."""
    assert classify("Tell me about a time you smashed a target, you must have, right?") == "leading"


@pytest.mark.parametrize(
    "text",
    [
        "Can you help me with a brief introduction of yours and give me your background",
        "Like, let's say if you had a difficult customer, how did you deal with that",
        "And how does the, like, network related, what all type of complaints",
    ],
)
def test_questions_are_found_without_a_question_mark(text):
    """ASR drops the punctuation; on a voice session it is the transcriber's guess."""
    assert is_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "Okay, that sounds about great.",
        "We will definitely come back to you on the next steps.",
        "But, like, I would like to end the interview right now.",
        "Let me know if my window is visible to you.",
    ],
)
def test_statements_are_not_mistaken_for_questions(text):
    assert not is_question(text)


def test_framing_balance_is_reported_but_never_scored():
    """One session cannot tell differential framing from a single risk question."""
    report = build_report(_bundle())
    signal = next(
        s for c in report.criteria for s in c.signals if s.id == "promotion_prevention_balance"
    )
    assert signal.sub_score is None
    assert signal.weight == 0.0


def test_a_restraint_signal_is_not_scored_as_though_it_were_a_question():
    """`cooperative_trap` is mostly "do not ask" items; crediting a question inverts it."""
    persona = {
        "archetype_key": "cooperative_trap",
        "label": "The cooperative candidate",
        "must_discover": [
            {
                "id": "protected_detail_not_pursued",
                "signal": "The volunteered personal detail was acknowledged and left alone",
                "weight": 1.0,
                "how_to_surface": "Move back to the role without asking a single follow-up on it",
            }
        ],
        "session_beats": [],
        "stresses": {"fairness": 4},
    }
    report = build_report(_bundle(persona=persona))
    signal = next(s for c in report.criteria for s in c.signals if s.id == "discovery_attempted")
    assert signal.sub_score is None
    assert "restraint" in signal.reason


def test_a_probe_references_the_answer_before_it():
    turns = [
        Turn(index=0, speaker="manager", text="Walk me through last quarter.", elapsed_ms=0),
        Turn(index=1, speaker="candidate", text="We lifted conversion a lot.", elapsed_ms=1000),
        Turn(index=2, speaker="manager", text="What was the conversion number?", elapsed_ms=2000),
    ]
    acts = extract(turns)
    assert [a.is_probe for a in acts] == [False, True]
    assert acts[1].probe_depth == 1
    assert acts[0].topic_id == acts[1].topic_id


# ------------------------------------------------------------- the signals ----


def test_the_planted_protected_topics_are_caught():
    report = build_report(_bundle())
    flagged = {a.protected_topic for a in report.question_acts if a.protected_topic}
    assert flagged == {"gender_role", "salary_history"}


def test_a_protected_topic_lowers_fairness_but_caps_nothing():
    """The standing product rule: nothing caps, fails or overrides a score."""
    report = build_report(_bundle())
    fairness = next(c for c in report.criteria if c.id == "fairness")
    assert fairness.score is not None and fairness.score < 5.0
    assert report.readiness_index is not None and report.readiness_index > 0
    other = [c.score for c in report.criteria if c.id != "fairness" and c.score is not None]
    assert max(other) > 7.0, "a fairness hit must not drag the other criteria down"


def test_an_unmeasurable_signal_is_never_scored_as_zero():
    report = build_report(_bundle())
    voice_only = [
        s for c in report.criteria for s in c.signals if s.id == "intrusive_interruption_rate"
    ]
    assert voice_only and voice_only[0].sub_score is None
    assert "not measurable in a text session" in voice_only[0].reason


def test_positive_only_markers_do_not_penalise_absence():
    report = build_report(_bundle())
    for signal_id in ("accommodation_offered", "name_confirmed"):
        signal = next(s for c in report.criteria for s in c.signals if s.id == signal_id)
        assert signal.value == 0.0
        assert signal.sub_score is None, f"{signal_id} penalised a manager for an absent bonus"


def test_pace_and_fillers_are_measured_but_never_scored():
    """The wizard specification is explicit, and the research agrees."""
    report = build_report(_bundle())
    signal = next(s for c in report.criteria for s in c.signals if s.id == "pace_and_fillers")
    assert signal.value is not None
    assert signal.sub_score is None
    assert signal.weight == 0.0


def test_every_finding_carries_a_quote_that_exists_in_the_transcript():
    bundle = _bundle()
    report = build_report(bundle)
    corpus = "\n".join(t.text for t in bundle.turns)
    for finding in [*report.strengths, *report.gaps]:
        for evidence in finding.evidence:
            quote = evidence.quote.split("] ")[-1]
            assert quote[:60] in corpus, f"unanchored quote in {finding.signal_id}"


# ------------------------------------------------------------ the toggles ----


def test_english_weighting_rescales_the_rubric_and_keeps_the_ordering():
    plain = build_report(_bundle())
    weighted = build_report(_bundle(scoring_options={"english_weight": 0.10}))

    plain_weights = {c.id: c.weight for c in plain.criteria}
    weighted_weights = {c.id: c.weight for c in weighted.criteria}

    assert "communication_english" in weighted_weights
    assert weighted_weights["communication_english"] == pytest.approx(0.10)
    assert sum(weighted_weights.values()) == pytest.approx(1.0)
    for criterion_id, weight in plain_weights.items():
        assert weighted_weights[criterion_id] == pytest.approx(weight * 0.9)


def test_the_english_weight_is_stamped_so_reports_stay_comparable():
    assert build_report(_bundle()).provenance.english_weight is None
    weighted = build_report(_bundle(scoring_options={"english_weight": 0.10}))
    assert weighted.provenance.english_weight == 0.10


def test_pure_english_is_never_mistaken_for_code_mixed():
    """Regression on a false positive that refused real sessions.

    "the" was in the romanised-Hindi list (Hindi "the"), so an ordinary English
    sentence containing it scored as code-mixed and was gated.
    """
    from report_engine import language as lang

    turns = [
        Turn(
            index=0,
            speaker="manager",
            text="Walk me through the last time the store missed the target.",
            elapsed_ms=0,
        )
    ]
    check = lang.check(turns, gate=True)
    assert check.detected == "en"
    assert not check.gated


def test_the_hindi_and_english_wordlists_do_not_overlap():
    """An ambiguous word in both lists biases every transcript toward code-mixed."""
    from report_engine.language import _ENGLISH_MARKERS, _ROMAN_HINDI

    assert not (_ROMAN_HINDI & _ENGLISH_MARKERS)


def test_non_latin_script_is_detected_beyond_devanagari():
    """A real session was part Urdu, which is Arabic script, and slipped through."""
    from report_engine import language as lang

    turns = [
        Turn(index=0, speaker="manager", text="تمہیں کیوں لگتا ہے کہ تم صحیح فٹ ہو", elapsed_ms=0)
    ]
    assert lang.check(turns, gate=False).detected == "non-latin"


def test_a_non_english_session_is_scored_by_default_not_refused():
    """An interview happens in whatever language the room speaks."""
    turns = [
        {
            "index": i,
            "speaker": "manager" if i % 2 == 0 else "candidate",
            "text": "Aap apne bare mein kuch bataiye, aapko kya lagta hai yeh role kaise hai",
            "elapsed_ms": i * 1000,
        }
        for i in range(8)
    ]
    report = build_report(_bundle(turns=turns))
    assert not report.unscoreable
    assert report.readiness_index is not None
    assert any("still been scored" in w for w in report.validity_warnings)


def test_a_non_english_session_marks_english_dependent_criteria_low_confidence():
    """Scored is not the same as equally trustworthy."""
    turns = [
        {
            "index": i,
            "speaker": "manager" if i % 2 == 0 else "candidate",
            "text": "Aap apne bare mein kuch bataiye, aapko kya lagta hai yeh role kaise hai",
            "elapsed_ms": i * 1000,
        }
        for i in range(8)
    ]
    report = build_report(_bundle(turns=turns))
    scored = [c for c in report.criteria if c.score is not None]
    assert scored
    assert all(c.confidence == "low" for c in scored)
    assert all("English patterns" in c.confidence_reason for c in scored)


def test_the_gate_can_still_be_turned_on_deliberately():
    turns = [
        {
            "index": i,
            "speaker": "manager" if i % 2 == 0 else "candidate",
            "text": "Aap apne bare mein kuch bataiye, aapko kya lagta hai yeh role kaise hai",
            "elapsed_ms": i * 1000,
        }
        for i in range(8)
    ]
    report = build_report(_bundle(turns=turns, scoring_options={"language_gate": True}))
    assert report.unscoreable == "language_unsupported"
    assert report.readiness_index is None


def test_language_is_always_reported_even_when_it_passes():
    report = build_report(_bundle())
    assert report.language is not None
    assert report.language.detected == "en"
    assert not report.language.gated


# --------------------------------------------------------------------- cli ----


def test_the_cli_runs_offline_and_writes_both_formats(tmp_path):
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(_bundle().model_dump_json())
    html_path, json_path = tmp_path / "r.html", tmp_path / "r.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "report_engine",
            str(bundle_path),
            "-o",
            str(html_path),
            "--json",
            str(json_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "<title>" in html_path.read_text()
    assert json.loads(json_path.read_text())["readiness_index"] is not None


# ------------------------------------------------------ the control plane ----


def test_the_bundle_reads_a_composed_personas_scorecard_off_the_candidate():
    """A `dyn-` persona has no catalog entry; its ground truth is on the candidate."""
    from control_plane.reporting import persona_block

    session = SimpleNamespace(persona_key="dyn-abc123", candidate_id="vc-1")
    candidate = SimpleNamespace(
        archetype_label="Composed persona",
        interviewer_scorecard=SimpleNamespace(
            must_discover=[
                SimpleNamespace(
                    id="depth_vs_effort",
                    signal="Separates skill ceiling from effort",
                    weight=0.3,
                    how_to_surface="Offer an easy win and see if real depth appears",
                )
            ]
        ),
    )
    block = persona_block(session, candidate)
    assert block["archetype_key"] == "dyn-abc123"
    assert len(block["must_discover"]) == 1
    # Composed personas are assembled from trait presets, not written to stress
    # a criterion, so there is no scripted beat list and no stress map to copy.
    assert block["session_beats"] == []
    assert block["stresses"] == {}


def test_an_unknown_persona_yields_an_empty_block_rather_than_raising():
    from control_plane.reporting import persona_block

    session = SimpleNamespace(persona_key="dyn-gone", candidate_id="vc-1")
    block = persona_block(session, None)
    assert block["must_discover"] == []


def test_a_catalog_persona_still_comes_from_the_catalog():
    from control_plane.reporting import persona_block

    session = SimpleNamespace(persona_key="inflated_resume", candidate_id="vc-1")
    block = persona_block(session, None)
    assert block["label"] == "The inflated resume"
    assert len(block["must_discover"]) == 4
    assert block["stresses"]["structure"] == 4


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Network Field Engineer", "technical"),
        ("Operations Coordinator", "operations"),
        ("Assistant Store Manager", "sales"),
    ],
)
def test_role_family_is_derived_deterministically_from_the_title(title, family):
    from control_plane.reporting import role_family_for

    assert role_family_for(title) == family
