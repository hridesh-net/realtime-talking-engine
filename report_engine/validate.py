"""Evidence-span verification — the judge veto. Spec section 6.

The judge writes prose and makes claims; this module decides which of them are
allowed into the report. Nothing here trusts the model, and nothing here reads a
number out of what it wrote.

Three rules, all from the spec:

1. **Every evidence span must appear verbatim in the transcript.** A span that
   does not is a fabrication, and the claim resting on it is dropped. A dropped
   `must_discover` verdict degrades to *unmeasurable*, never to ``False`` — the
   judge failing to evidence something is not evidence that it did not happen.
2. **A ``surfaced: true`` needs the manager to have asked.** The span must be
   preceded by a manager question act in the same topic. A candidate
   volunteering something is not discovery, and crediting it would score the
   manager for the candidate's behaviour.
3. **Numbers are never parsed from prose.** This module returns validated
   booleans and validated sentences; :mod:`report_engine.score` computes every
   number from them, exactly as it does on the deterministic path.

Whitespace is normalised before matching and case is ignored, because a
transcript's casing and line breaks are the transcriber's guess rather than
anything the speaker did. Word order, wording and punctuation are not
normalised: those are the parts a fabricated quote gets wrong.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from report_engine.schema import Evidence, QuestionAct, Turn

#: Longest span accepted. A judge that quotes half the interview is not citing a
#: moment, and `Evidence.quote` is capped at 400 characters anyway.
MAX_SPAN = 400

#: Shortest span accepted. "yes" appears verbatim in almost every transcript, so
#: a span that short verifies against the wrong turn as easily as the right one
#: and proves nothing.
MIN_SPAN = 12

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Whitespace-collapsed, case-folded, NFKC — the form spans are matched in."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


@dataclass
class Verdict:
    """What happened to one judge claim, and why."""

    accepted: bool
    reason: str = ""
    evidence: Evidence | None = None


@dataclass
class Transcript:
    """The transcript as the veto reads it: an index from span to turn."""

    turns: list[Turn]
    acts: list[QuestionAct] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalise every turn once; spans are matched against this form."""
        self._normalised = [(t, _norm(t.text)) for t in self.turns]

    def verify(self, span: str) -> Verdict:
        """Find a span verbatim in some turn, or reject the claim resting on it."""
        cleaned = span.strip()
        if len(cleaned) < MIN_SPAN:
            return Verdict(False, f"evidence span is shorter than {MIN_SPAN} characters")
        if len(cleaned) > MAX_SPAN:
            return Verdict(False, f"evidence span is longer than {MAX_SPAN} characters")

        needle = _norm(cleaned)
        for turn, haystack in self._normalised:
            if needle in haystack:
                return Verdict(
                    True,
                    evidence=Evidence(
                        turn_index=turn.index,
                        at_ms=turn.elapsed_ms,
                        speaker=turn.speaker,
                        quote=cleaned[:MAX_SPAN],
                    ),
                )
        return Verdict(False, "evidence span does not appear verbatim in the transcript")

    def asked_before(self, evidence: Evidence) -> Verdict:
        """Whether this moment is the candidate answering a question the manager asked.

        Two checks, and the spec's "in the same topic" is not a third. Topics are
        clustered *from the manager's own questions*, so the nearest preceding
        act is in the evidence's topic by construction — asserting it would be a
        test that cannot fail. What carries the weight is:

        * The **candidate** has to be the one who said it. A judge citing the
          manager's own question as proof that something was surfaced is citing
          the asking, not the answering, and that is the likelier mistake.
        * A **manager question** has to precede it, or the candidate volunteered
          it, and volunteering is not discovery.
        """
        if evidence.speaker != "candidate":
            return Verdict(
                False,
                "the span is the manager speaking; discovery is what the candidate revealed",
            )
        if not any(a.turn_index < evidence.turn_index for a in self.acts):
            return Verdict(False, "no manager question precedes this moment")
        return Verdict(True, evidence=evidence)


#: Text between a pair of quotation marks — straight or curly. A judge quoting
#: the manager saying "a hundred and fifty percent" must not be rejected for the
#: number inside someone else's sentence.
_QUOTED = re.compile(r"[\"\u201c\u2018\'][^\"\u201c\u201d\u2018\u2019\']*[\"\u201d\u2019\']")

#: Longest prose the report will print from the judge, by slot. These are layout
#: limits with teeth: the scorecard is four cards and a summary on one page, and
#: a criterion narrative that runs to a paragraph pushes a card onto the next
#: one. The prompt asks for brevity and this is what makes the asking binding.
MAX_PROSE = 900
MAX_SUMMARY = 420
MAX_NARRATIVE = 340
MAX_BULLET = 160


def check_prose(text: str, limit: int = MAX_PROSE) -> Verdict:
    """Rule 3, from the other side: the judge may not state a number.

    Every number on the page is computed by code and printed beside the prose
    that describes it. A judge free to write numbers too can contradict them, and
    the reader has no way to tell which one is the measurement. So prose carrying
    a digit outside a quotation is rejected and the composed sentence stands.
    """
    cleaned = text.strip()
    if not cleaned:
        return Verdict(False, "empty")
    if len(cleaned) > limit:
        return Verdict(False, f"longer than {limit} characters")
    if any(ch.isdigit() for ch in _QUOTED.sub("", cleaned)):
        return Verdict(False, "states a number; every number is computed and printed by code")
    return Verdict(True)


def check_span(transcript: Transcript, span: str) -> Verdict:
    """Rule 1 alone: the span is real."""
    return transcript.verify(span)


def check_surfaced(transcript: Transcript, span: str) -> Verdict:
    """Rules 1 and 2: the span is real *and* the manager asked for it.

    Returns a rejecting verdict with a reason on either failure. The caller
    turns a rejection into `unmeasurable`, never into ``surfaced=False``.
    """
    verdict = transcript.verify(span)
    if not verdict.accepted or verdict.evidence is None:
        return verdict
    return transcript.asked_before(verdict.evidence)
