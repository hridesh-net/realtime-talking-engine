"""The analysis agent's offline gate.

Everything here runs without a model or an API key: the harness is pure, and it
owns the parts that must never drift — where a window's timestamps land, which
anchors are rejected, and how the two halves of the judgement are weighted.

The one exception is the duration test at the bottom, which builds a real WebM
and shells out to `ffmpeg`/`ffprobe`. That is still offline — ffmpeg is a local
subprocess, not a vendor — and the behaviour it pins can only be seen through
the real decoder. It skips when ffmpeg is absent.
"""

import json
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from analysis_agent import harness, prompts
from analysis_agent.audio import OVERLAP_MS, WINDOW_MS, duration_ms, plan
from analysis_agent.schema import (
    ANALYSIS_INSTRUCTIONS_VERSION,
    EXPECTATION_COVERAGE_WEIGHT,
    PERSONA_RESPONSE_WEIGHT,
    AnalysisContext,
)


def _window(**over):
    base = {
        "spoken_languages": ["english"],
        "transcript": [],
        "questions": [],
        "topic_flags": [],
        "silences": [],
        "interruptions": [],
        "discovery": [],
        "delivery": {
            "question_clarity": 5,
            "explanation_quality": 5,
            "tone_trajectory": "",
            "pace_note": "",
            "confidence": "medium",
        },
        "criteria": [],
    }
    base.update(over)
    return base


# ------------------------------------------------------------- windowing ----


def test_a_short_recording_is_one_window():
    assert plan(90_000) == [(0, 90_000)]


def test_windows_overlap_so_an_exchange_on_a_boundary_is_heard_whole():
    spans = plan(600_000)
    assert len(spans) > 1
    for (start, span), (next_start, _) in pairwise(spans):
        assert next_start < start + span, "windows must overlap"
        assert start + span - next_start == OVERLAP_MS


def test_windows_cover_the_whole_recording():
    total = 1_000_000
    spans = plan(total)
    assert spans[0][0] == 0
    assert spans[-1][0] + spans[-1][1] == total


def test_no_window_is_longer_than_the_configured_span():
    assert all(span <= WINDOW_MS for _, span in plan(2_000_000))


# ------------------------------------------------------ anchors and time ----


def test_window_timestamps_are_shifted_onto_the_recording_clock():
    answers = [
        (
            0,
            240_000,
            _window(
                questions=[
                    {
                        "at_ms": 10_000,
                        "text": "first",
                        "text_en": "first",
                        "type": "open",
                        "is_probe": False,
                        "clarity": 5,
                        "confidence": "high",
                    }
                ]
            ),
        ),
        (
            220_000,
            120_000,
            _window(
                questions=[
                    {
                        "at_ms": 10_000,
                        "text": "second",
                        "text_en": "second",
                        "type": "open",
                        "is_probe": False,
                        "clarity": 5,
                        "confidence": "high",
                    }
                ]
            ),
        ),
    ]
    out = harness.merge(answers, audio_duration_ms=340_000, model_used="m")
    assert [q.at_ms for q in out.questions] == [10_000, 230_000]


def test_an_anchor_past_the_end_of_its_own_window_is_rejected():
    """A late window's overshoot must not hide under earlier windows' headroom."""
    answers = [
        (
            220_000,
            120_000,
            _window(
                questions=[
                    {
                        "at_ms": 200_000,
                        "text": "impossible",
                        "text_en": "",
                        "type": "open",
                        "is_probe": False,
                        "clarity": 5,
                        "confidence": "high",
                    }
                ]
            ),
        ),
    ]
    out = harness.merge(answers, audio_duration_ms=340_000, model_used="m")
    assert out.questions == []
    assert out.dropped_anchors == 1


def test_the_same_utterance_heard_by_two_overlapping_windows_appears_once():
    turn = {
        "start_ms": 5_000,
        "end_ms": 7_000,
        "speaker": "manager",
        "text": "who all are there in your family",
        "text_en": "",
        "confidence": "high",
    }
    answers = [
        (0, 240_000, _window(transcript=[{**turn, "start_ms": 225_000, "end_ms": 227_000}])),
        (220_000, 120_000, _window(transcript=[turn])),
    ]
    out = harness.merge(answers, audio_duration_ms=340_000, model_used="m")
    assert len(out.transcript) == 1


# ------------------------------------------------- the two halves, 60/40 ----


def test_reading_the_candidate_outweighs_working_through_the_plan():
    assert PERSONA_RESPONSE_WEIGHT > EXPECTATION_COVERAGE_WEIGHT
    assert pytest.approx(1.0) == PERSONA_RESPONSE_WEIGHT + EXPECTATION_COVERAGE_WEIGHT


def test_the_session_judgement_is_composed_in_code_not_by_the_model():
    """And coverage is recomputed from the counts, not taken on the model's word."""
    answers = [
        (
            0,
            240_000,
            _window(
                persona_response={
                    "read_the_candidate": 8,
                    "adapted_approach": 8,
                    "handled_the_hard_moment": 8,
                    "rating": 8,
                    "reasoning": "",
                    "evidence_at_ms": [],
                    "confidence": "high",
                },
                expectation_coverage={
                    "rating": 3,
                    "reachable_items": 4,
                    "covered_items": 1,
                    "reasoning": "",
                    "confidence": "high",
                },
            ),
        )
    ]
    out = harness.merge(answers, audio_duration_ms=240_000, model_used="m")
    # The model claimed 3/10 while reporting 1 of 4 covered. The counts win: a
    # rating is an opinion, `covered / reachable` is arithmetic, and code owning
    # the arithmetic is what makes the number checkable.
    assert out.expectation_coverage.rating == 2
    assert out.session_judgement == pytest.approx(8 * 0.6 + 2 * 0.4)


def test_a_manager_who_read_the_room_and_closed_early_is_not_marked_down_for_coverage():
    """The case the design exists for: correct early close, little covered."""
    answers = [
        (
            0,
            240_000,
            _window(
                persona_response={
                    "read_the_candidate": 9,
                    "adapted_approach": 9,
                    "handled_the_hard_moment": 9,
                    "rating": 9,
                    "reasoning": "read it early",
                    "evidence_at_ms": [],
                    "confidence": "high",
                },
                # Only one item was ever reachable, and it was covered.
                expectation_coverage={
                    "rating": 10,
                    "reachable_items": 1,
                    "covered_items": 1,
                    "reasoning": "",
                    "unreachable_because": "closed early, rightly",
                    "confidence": "high",
                },
                early_end={
                    "ended_early": True,
                    "at_ms": 90_000,
                    "evidence_before_deciding": 8,
                    "closed_civilly": True,
                    "justified": True,
                    "reasoning": "",
                    "confidence": "high",
                },
            ),
        )
    ]
    out = harness.merge(answers, audio_duration_ms=240_000, model_used="m")
    assert out.early_end.ended_early and out.early_end.justified
    assert out.session_judgement >= 9.0, "an evidenced early close must not score badly"


def test_coverage_is_scored_against_reachable_items_not_the_whole_plan():
    answers = [
        (
            0,
            240_000,
            _window(
                expectation_coverage={
                    "rating": 0,
                    "reachable_items": 2,
                    "covered_items": 2,
                    "reasoning": "",
                    "confidence": "high",
                }
            ),
        )
    ]
    out = harness.merge(answers, audio_duration_ms=240_000, model_used="m")
    assert out.expectation_coverage.rating == 10


def test_covered_can_never_exceed_reachable():
    answers = [
        (
            0,
            240_000,
            _window(
                expectation_coverage={
                    "rating": 10,
                    "reachable_items": 2,
                    "covered_items": 9,
                    "reasoning": "",
                    "confidence": "high",
                }
            ),
        )
    ]
    out = harness.merge(answers, audio_duration_ms=240_000, model_used="m")
    assert out.expectation_coverage.covered_items == 2


# ------------------------------------------------------------- discovery ----


def test_a_surfaced_finding_in_any_window_wins_over_not_surfaced():
    item = {
        "id": "claim_tested",
        "is_restraint_item": False,
        "at_ms": 1_000,
        "evidence": "",
        "confidence": "high",
    }
    answers = [
        (0, 240_000, _window(discovery=[{**item, "status": "not_surfaced"}])),
        (220_000, 120_000, _window(discovery=[{**item, "status": "surfaced"}])),
    ]
    out = harness.merge(answers, audio_duration_ms=340_000, model_used="m")
    assert [d.status for d in out.discovery] == ["surfaced"]


def test_volunteered_does_not_outrank_surfaced():
    """Surfaced needs the manager to have asked; volunteered is the candidate."""
    item = {"id": "x", "is_restraint_item": False, "at_ms": 0, "evidence": "", "confidence": "high"}
    answers = [
        (0, 240_000, _window(discovery=[{**item, "status": "surfaced"}])),
        (220_000, 120_000, _window(discovery=[{**item, "status": "volunteered"}])),
    ]
    out = harness.merge(answers, audio_duration_ms=340_000, model_used="m")
    assert out.discovery[0].status == "surfaced"


# ---------------------------------------------------------- instructions ----


def test_the_instructions_ship_with_the_package():
    text = prompts.instructions()
    assert len(text) > 5_000
    assert ANALYSIS_INSTRUCTIONS_VERSION in text


def test_the_instructions_state_the_channel_map():
    """Speaker attribution is a fact from the stereo split, never a guess."""
    text = prompts.instructions().lower()
    assert "left" in text and "manager" in text
    assert "never guess who is speaking" in text


def test_the_instructions_forbid_scoring_and_candidate_assessment():
    text = prompts.instructions().lower()
    assert "never produce a final score" in text
    assert "never assess the candidate" in text


def test_the_instructions_say_an_early_close_can_be_correct():
    text = prompts.instructions().lower()
    assert "ending early is not a failure by default" in text


def test_the_persona_the_manager_faced_reaches_the_prompt():
    """Adaptation cannot be judged without knowing who was in the room."""
    ctx = AnalysisContext(
        persona_label="The evasive candidate",
        persona_traits={"honesty": [2, 4]},
        persona_answer_policy={"on_pressure": "deflects"},
    )
    block = prompts.context_block(ctx)
    assert "The evasive candidate" in block
    assert "honesty" in block
    assert "on_pressure" in block


# ------------------------------------------------------- duration, on video ----


def _build_video_fixture(path: Path) -> None:
    """A live-mode VP8+Opus WebM: 150 s of video over 100 s of audio.

    `-live 1` is what makes this fixture worth building rather than mocking: it
    writes the WebM the way `MediaRecorder` does, as a stream with no duration in
    the header, so `ffprobe -show_format` reports none and `duration_ms` is
    forced down its decode fallback — the path the browser's recordings always
    take.
    """
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=150:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=100",
            "-c:v",
            "libvpx",
            "-c:a",
            "libopus",
            "-live",
            "1",
            "-f",
            "webm",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe not on PATH; duration_ms shells out to both",
)
def test_duration_of_a_video_recording_is_the_length_of_its_audio(tmp_path):
    """A camera track longer than the audio must not stretch the reported length.

    The manager's camera starts before the mic is armed and stops after the call
    ends, so the container's video is genuinely longer than its audio. The decode
    fallback takes the *last* `time=` ffmpeg prints; if that came from the video
    stream the analysis would plan a window past the end of the audio and anchor
    claims at moments with nothing in them.

    On the ffmpeg here (8.x) the un-flagged command already reports the audio
    length, so this does not prove `-vn` is load-bearing on *this* machine. The
    assertion is the behavioural contract: the deployed host installs an
    unpinned static build from johnvansickle.com, ffmpeg's progress reporting has
    changed between majors, and whatever version lands there has to answer
    100 s for this file.
    """
    fixture = tmp_path / "camera-and-mic.webm"
    _build_video_fixture(fixture)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "duration" not in json.loads(probe.stdout)["format"], (
        "the fixture must have no header duration, or it never reaches the fallback"
    )

    assert duration_ms(fixture) == pytest.approx(100_000, abs=100)
