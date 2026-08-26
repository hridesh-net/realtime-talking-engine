"""The language gate — spec section 3.4.

BRD D-6: frontline interviews are frequently Hindi or Hindi-English code-mixed,
which breaks question typing, the protected-topic lexicon and STAR extraction
at once. The mix is *always* detected and reported; the operator's toggle only
decides whether a non-English session is refused or scored with a warning.
"""

from __future__ import annotations

import re

from report_engine.schema import LanguageCheck, Turn
from report_engine.text import words

#: Devanagari. A single hit is decisive — nothing in an English transcript
#: produces one accidentally.
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

#: Romanised Hindi function words. Function words are the right probe because
#: they survive code-mixing: a manager may borrow English nouns wholesale and
#: still frame every sentence in Hindi.
_ROMAN_HINDI_BLOCK = """
    aap aapka aapko hai hain ho hoga hona kya kyun kaise kaha kab kitna kitne
    nahi nahin mera meri mujhe hum humein tum tumhara yeh woh koi kuch bahut
    thoda accha theek karna karta karte kiya raha rahe rahi tha thi the toh bhi
    par lekin aur ya jab tab abhi phir liye wala wali sakta sakte sakti chahiye
    """
_ROMAN_HINDI: frozenset[str] = frozenset(_ROMAN_HINDI_BLOCK.split())

#: High-frequency English function words. Same logic in reverse.
_ENGLISH_MARKERS_BLOCK = """
    the and is are was were you your that this with have has for from what
    when how why can could would should about there their they them will not
    but which who our out into been being does did doing
    """
_ENGLISH_MARKERS: frozenset[str] = frozenset(_ENGLISH_MARKERS_BLOCK.split())

#: Below this share of English function words the English rule set is unsafe.
#: CALIBRATION — no published cut point exists for code-mixed interview speech.
ENGLISH_SHARE_FLOOR = 0.85


def check(turns: list[Turn], *, gate: bool) -> LanguageCheck:
    """Detect the manager's language mix and decide whether to gate the session."""
    manager_text = " ".join(t.text for t in turns if t.speaker == "manager")
    tokens = words(manager_text)

    if _DEVANAGARI.search(manager_text):
        return LanguageCheck(detected="hi", english_token_share=0.0, confidence="high", gated=gate)

    if not tokens:
        return LanguageCheck(
            detected="unknown", english_token_share=0.0, confidence="low", gated=gate
        )

    hindi = sum(1 for w in tokens if w in _ROMAN_HINDI)
    english = sum(1 for w in tokens if w in _ENGLISH_MARKERS)
    function_words = hindi + english
    # No function words in either language means the sample is too short or too
    # unusual to judge. Say "unknown" rather than defaulting to English.
    if function_words == 0:
        return LanguageCheck(
            detected="unknown", english_token_share=0.0, confidence="low", gated=False
        )

    share = english / function_words
    confidence = "high" if function_words >= 25 else "low"
    detected = "en" if share >= ENGLISH_SHARE_FLOOR else "hi-en"
    return LanguageCheck(
        detected=detected,
        english_token_share=round(share, 3),
        confidence=confidence,
        gated=gate and share < ENGLISH_SHARE_FLOOR,
    )
