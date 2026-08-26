"""Segmentation — spec section 3.1.

Talk time and question mix mean different things at the open, in assessment,
and at the close. Scoring them against one budget would penalise a manager for
explaining the role, which is a different signal entirely.
"""

from __future__ import annotations

import re

from report_engine.schema import QuestionAct, Turn
from report_engine.text import compile_all

OPEN = "OPEN"
ASSESS = "ASSESS"
CANDIDATE_Q = "CANDIDATE_Q"
CLOSE = "CLOSE"

INVITE_CUES = compile_all(
    [
        r"\b(any|do you have|got any|have you got)\s+(questions|anything)\b",
        r"\bquestions for (me|us)\b",
        r"\banything you('d| would) like to ask\b",
        r"\bwhat (would you like|do you want) to (know|ask)\b",
    ]
)

CLOSE_CUES = compile_all(
    [
        r"\bnext steps?\b",
        r"\bwe('ll| will) (be in touch|get back|let you know|revert)\b",
        r"\bhear (back )?from us\b",
        r"\bthanks? (so much )?for (your time|coming|joining)\b",
        r"\bthat('s| is) all (from me|i had)\b",
        r"\bwrap (this |it )?up\b",
    ]
)


def assign(turns: list[Turn], acts: list[QuestionAct]) -> dict[int, str]:
    """Map turn index to segment.

    Boundaries collapse gracefully: with no invite cue there is no CANDIDATE_Q
    segment, and the signal that measures the invitation records that instead.
    """
    manager_turns = [t for t in turns if t.speaker == "manager"]
    if not manager_turns:
        return {t.index: OPEN for t in turns}

    # Assessment starts at the first question of any type. Restricting this to
    # open questions once left two real closed questions sitting in OPEN, which
    # then escaped the talk-share measurement entirely.
    first_probe_turn = acts[0].turn_index if acts else None
    invite_turn = _first_cue(manager_turns, INVITE_CUES)
    close_turn = _first_cue(manager_turns, CLOSE_CUES, after=invite_turn)

    boundaries: dict[int, str] = {}
    for turn in turns:
        boundaries[turn.index] = _segment_for(turn.index, first_probe_turn, invite_turn, close_turn)
    return boundaries


def _segment_for(
    index: int,
    first_probe: int | None,
    invite: int | None,
    close: int | None,
) -> str:
    if close is not None and index >= close:
        return CLOSE
    if invite is not None and index >= invite:
        return CANDIDATE_Q
    if first_probe is not None and index >= first_probe:
        return ASSESS
    return OPEN


def _first_cue(
    turns: list[Turn], cues: list[re.Pattern[str]], after: int | None = None
) -> int | None:
    for turn in turns:
        if after is not None and turn.index <= after:
            continue
        if any(c.search(turn.text) for c in cues):
            return turn.index
    return None
