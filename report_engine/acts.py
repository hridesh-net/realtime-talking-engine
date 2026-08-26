"""Question-act extraction and typing — spec section 3.2 and 3.3.

Turns are too coarse to score: one manager turn routinely holds a preamble, a
question, and a second question. The question act is the unit of analysis.

Every rule here is a pattern, never a model call. That is what makes the counts
reproducible.
"""

from __future__ import annotations

import re

from report_engine.schema import QuestionAct, Turn
from report_engine.text import compile_all, content_words, jaccard, sentences

#: Overlap with the preceding candidate turn above which a question counts as a
#: probe. CALIBRATION — the direction is sourced (probing raises information
#: yield: Memon, Meissner & Fraser 2010), the cut point is not.
PROBE_OVERLAP = 0.10

_ELICIT = compile_all(
    [
        r"^\s*(so\s+)?tell me\b",
        r"^\s*walk me through\b",
        r"^\s*describe\b",
        r"^\s*explain\b",
        r"^\s*give me (an example|a sense)\b",
        r"^\s*talk me through\b",
        r"^\s*(can|could|would) you (tell|help|walk|explain|describe|give)\b",
        r"^\s*help me understand\b",
    ]
)

# Precedence matters: a leading behavioural question is still leading.
_LEADING = compile_all(
    [
        r",\s*(right|correct|yeah|no|isn't it|aren't you|don't you|wouldn't you)\s*\?",
        r"^\s*so you('re| are| were|'ve| have)?\s+(not|never|n't)\b",
        r"\bi (assume|presume|take it)\b",
        r"^\s*surely\b",
        r"\byou probably\b",
        r"\bdon't you think\b",
        r"\bwouldn't you agree\b",
    ]
)

_BEHAVIOURAL = compile_all(
    [
        r"\btell me about a time\b",
        r"\bdescribe a (situation|time|moment|case)\b",
        r"\bgive me an example of (a time |when )?\b",
        r"\bwalk me through a (time|situation|project|deal)\b",
        r"\b(can|could) you recall\b",
        r"\bwhen have you\b",
        r"\bhave you ever\b",
        r"\btell me about (a|an|your last|your most)\b",
        r"\bwhat did you do when\b",
    ]
)

_SITUATIONAL = compile_all(
    [
        r"\bwhat would you do\b",
        r"\bhow would you (handle|approach|deal|manage)\b",
        r"\bif you were\b",
        r"\bsuppose\b",
        r"\bimagine\b",
        r"\bwhat if\b",
    ]
)

#: ASR routinely drops the question mark off spoken questions, so punctuation
#: alone under-counts on any voice session. These recover the two shapes that
#: are unambiguous without it: an auxiliary-fronted clause ("can you tell me"),
#: and a wh-word followed closely by an auxiliary or pronoun ("how did you deal",
#: "what all type of complaints"). Both were missed on a real recording before
#: this existed, including a behavioural question, which moved the score.
_UNPUNCTUATED_QUESTION = compile_all(
    [
        r"^\s*(do|did|does|are|is|was|were|have|has|had|can|could|will|would|should)\s+(you|your|we)\b",
        r"\b(what|when|where|who|whom|why|how|which|whose)\b[^.?!]{0,40}?"
        r"\b(do|did|does|are|is|was|were|have|has|had|can|could|will|would|should|you|your)\b",
    ]
)

_PROBE_CUES = compile_all(
    [
        r"\byou (said|mentioned|told me)\b",
        r"\bwhat exactly\b",
        r"\bwhich one\b",
        r"\bhow many\b",
        r"\bwhat was the number\b",
        r"\bwhat was your (part|role|contribution)\b",
        r"\bcan you be (more )?specific\b",
        r"\bsay more\b",
        r"\bfor example\b",
        r"\bwhy (was|is|did|do) that\b",
    ]
)

_CLOSED_OPENER_BLOCK = (
    "do did does are is was were have has had can could will would should shall am"
)
_CLOSED_OPENERS = frozenset(_CLOSED_OPENER_BLOCK.split())
_WH_OPENER_BLOCK = "what when where who whom why how which whose"
_WH_OPENERS = frozenset(_WH_OPENER_BLOCK.split())

_AUX = re.compile(r"^\s*(so|and|but|ok|okay|right|now|alright)[,\s]+", re.IGNORECASE)


def _strip_filler_opener(text: str) -> str:
    """Drop a discourse-marker opener so the first real word can be classified."""
    return _AUX.sub("", text).strip()


def is_question(text: str) -> bool:
    """Whether a sentence functions as a question or an elicitation.

    Deliberately does not rely on the question mark: on a voice session the
    punctuation is the transcriber's guess, not the speaker's.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    core = _strip_filler_opener(stripped)
    if any(p.search(core) for p in _ELICIT):
        return True
    return any(p.search(core) for p in _UNPUNCTUATED_QUESTION)


def classify(text: str) -> str:
    """The question act's type, in strict precedence order (spec section 3.3)."""
    core = _strip_filler_opener(text)
    if any(p.search(text) for p in _LEADING):
        return "leading"
    if _is_double_barrelled(text):
        return "double_barrelled"
    if any(p.search(core) for p in _BEHAVIOURAL):
        return "behavioural"
    if any(p.search(core) for p in _SITUATIONAL):
        return "situational"
    first = (core.split() or [""])[0].strip("'\",.").lower()
    if first in _WH_OPENERS or any(p.search(core) for p in _ELICIT):
        return "open_other"
    if first in _CLOSED_OPENERS:
        return "closed"
    return "open_other"


def _is_double_barrelled(text: str) -> bool:
    """Two asks in one breath — penalised as a compound question."""
    if text.count("?") > 1:
        return True
    core = _strip_filler_opener(text).lower()
    # Two wh-clauses joined by a coordinator: "what did you do and why did it work?"
    wh_after_join = re.findall(r"\b(?:and|or)\s+(\w+)", core)
    heads = [w for w in wh_after_join if w in _WH_OPENERS]
    return bool(heads) and any(core.startswith(w) for w in _WH_OPENERS)


def extract(turns: list[Turn]) -> list[QuestionAct]:
    """Every question the manager asked, typed, probe-tagged and topic-clustered.

    Segment and protected-topic labels are filled in by their own modules; this
    function owns extraction, typing, probe detection and topic clustering.
    """
    acts: list[QuestionAct] = []
    previous_candidate = ""
    topic_id = 0
    depth = 0
    last_topic_tokens: set[str] = set()

    for turn in turns:
        if turn.speaker == "candidate":
            previous_candidate = turn.text
            continue

        for sentence in sentences(turn.text):
            if not is_question(sentence):
                continue

            tokens = content_words(sentence)
            prior = content_words(previous_candidate)
            probe = jaccard(tokens, prior) >= PROBE_OVERLAP or any(
                p.search(sentence) for p in _PROBE_CUES
            )

            # A probe continues the current topic; anything else opens a new one.
            if probe and last_topic_tokens:
                depth += 1
            else:
                topic_id += 1
                depth = 0
                last_topic_tokens = tokens

            acts.append(
                QuestionAct(
                    turn_index=turn.index,
                    at_ms=turn.elapsed_ms,
                    text=sentence.strip(),
                    type=classify(sentence),
                    is_probe=probe,
                    probe_depth=depth,
                    topic_id=topic_id,
                )
            )

    return acts


def root_questions(acts: list[QuestionAct]) -> list[QuestionAct]:
    """The first act of each topic — the questions probes hang off."""
    return [a for a in acts if a.probe_depth == 0]
