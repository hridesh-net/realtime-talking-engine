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

#: Non-Latin scripts an interview in this market may be conducted in. A single
#: hit is decisive — nothing in an English transcript produces one accidentally.
#:
#: Devanagari alone was not enough: a real session turned out to be part Urdu,
#: which is written in **Arabic** script, and the detector scored it purely on
#: the Latin half without ever noticing the Urdu turn.
_NON_LATIN = re.compile(
    "["
    "\u0600-\u06ff"  # Arabic / Urdu
    "\u0900-\u097f"  # Devanagari - Hindi, Marathi
    "\u0980-\u09ff"  # Bengali
    "\u0a00-\u0a7f"  # Gurmukhi - Punjabi
    "\u0a80-\u0aff"  # Gujarati
    "\u0b00-\u0b7f"  # Odia
    "\u0b80-\u0bff"  # Tamil
    "\u0c00-\u0c7f"  # Telugu
    "\u0c80-\u0cff"  # Kannada
    "\u0d00-\u0d7f"  # Malayalam
    "]"
)

#: Romanised Hindi function words. Function words are the right probe because
#: they survive code-mixing: a manager may borrow English nouns wholesale and
#: still frame every sentence in Hindi.
_ROMAN_HINDI_BLOCK = """
    aap aapka aapko hai hain hoga hona kya kyun kaise kaha kab kitna kitne
    nahi nahin mera meri mujhe humein tumhara yeh woh koi kuch bahut
    thoda accha theek karna karta karte kiya raha rahe rahi thi toh bhi
    lekin aur jab tab abhi phir liye wala wali sakta sakte sakti chahiye
    """
#: Deliberately excluded, because they are also ordinary English words and a
#: transcript full of them is not evidence of Hindi: **the** (Hindi "थे"), which
#: is the single commonest English word and on its own made
#: "Walk me through the last time the store missed the target" score as
#: code-mixed; also *par*, *hum*, *ya*, *tha*, *ho*, *tum*. Precision matters
#: more than recall here - a false positive used to refuse to score a session.
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
    """Detect the manager's language mix and decide whether to gate the session.

    The share is computed from the Latin-script tokens either way. A session
    that is mostly English with one Urdu turn is exactly that, and reporting it
    as "0% English" would misdescribe it — the script hit changes the verdict,
    not the arithmetic.
    """
    manager_text = " ".join(t.text for t in turns if t.speaker == "manager")
    tokens = words(manager_text)

    hindi = sum(1 for w in tokens if w in _ROMAN_HINDI)
    english = sum(1 for w in tokens if w in _ENGLISH_MARKERS)
    function_words = hindi + english
    share = round(english / function_words, 3) if function_words else 0.0

    # A non-Latin script is decisive on its own: no English transcript produces
    # one accidentally, however English the rest of the turn reads.
    if _NON_LATIN.search(manager_text):
        return LanguageCheck(
            detected="non-latin",
            english_token_share=share,
            confidence="high",
            gated=gate,
        )

    if not tokens:
        return LanguageCheck(
            detected="unknown", english_token_share=0.0, confidence="low", gated=gate
        )

    # No function words in either language means the sample is too short or too
    # unusual to judge. Say "unknown" rather than defaulting to English.
    if function_words == 0:
        return LanguageCheck(
            detected="unknown", english_token_share=0.0, confidence="low", gated=False
        )

    confidence = "high" if function_words >= 25 else "low"
    detected = "en" if share >= ENGLISH_SHARE_FLOOR else "hi-en"
    return LanguageCheck(
        detected=detected,
        english_token_share=share,
        confidence=confidence,
        gated=gate and share < ENGLISH_SHARE_FLOOR,
    )
