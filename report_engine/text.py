"""Lexical helpers shared by the signal modules.

Deterministic and dependency-free on purpose: the whole engine's promise is
that re-running it on a stored session reproduces the same numbers, and a
tokeniser that changes with a library upgrade would quietly break that.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")

#: Closed-class words carry no topical content, so they are removed before any
#: overlap comparison. Kept small and explicit rather than pulled from a corpus.
_STOPWORD_BLOCK = """
    a about all also am an and any are as at be been but by can could did do does
    for from had has have he her him his how i if in into is it its just me my no
    not of on or our out so some than that the their them then there these they
    this to too us was we were what when where which who why will with would you
    your yours ok okay yeah yes right sure well
    """

STOPWORDS: frozenset[str] = frozenset(_STOPWORD_BLOCK.split())


def words(text: str) -> list[str]:
    """Lowercased word tokens."""
    return _WORD.findall(text.lower())


def content_words(text: str) -> set[str]:
    """Topical tokens: lowercased, stopword-stripped, one-character tokens dropped."""
    return {w for w in words(text) if w not in STOPWORDS and len(w) > 1}


def sentences(text: str) -> list[str]:
    """Split into sentence-ish units, keeping terminal punctuation.

    ASR punctuation is unreliable, so this is deliberately forgiving: it splits
    on terminators and never merges across them.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def jaccard(left: set[str], right: set[str]) -> float:
    """Overlap of two token sets, 0.0 when either is empty."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def matches_any(text: str, patterns: list[re.Pattern[str]]) -> re.Match[str] | None:
    """First pattern that hits, or None."""
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            return found
    return None


def compile_all(sources: list[str]) -> list[re.Pattern[str]]:
    """Case-insensitive compile of a phrase list."""
    return [re.compile(s, re.IGNORECASE) for s in sources]
