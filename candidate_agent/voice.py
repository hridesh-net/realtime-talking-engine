"""Compiles a persona's engine contract into a realtime voice session config.

The voice counterpart to :mod:`candidate_agent.session`, and the same
determinism split: **code owns** the instructions, the voice, the speaking rate,
and how eagerly the model decides the interviewer has stopped talking; **the
model owns** only what it says.

Nothing here imports a vendor SDK, and nothing here knows a vendor's voice
names. The caller passes the list of voices its provider supports and this
module picks one *deterministically from the persona*, so the same candidate
sounds like the same person every session — the audio equivalent of
``seed_fingerprint``.

The session document this builds is the vendor's shape (OpenAI Realtime, verified
2026-08-22). That is a deliberate coupling: there is one realtime provider wired
today, and inventing a neutral schema to translate into exactly one target would
be indirection without a second implementation to justify it. When a second
provider lands, this is the seam to split.
"""

from __future__ import annotations

from collections.abc import Sequence

from candidate_agent.engine_contract import pick_voice
from candidate_agent.prompts import build_voice_system_prompt
from candidate_agent.schema import EngineContract

#: Speaking rate per persona pace. The realtime API takes a multiplier; these
#: are deliberately narrow — past about ±20% the voice stops sounding human.
_SPEED = {"slow": 0.85, "measured": 1.0, "fast": 1.15}

#: How readily the model decides the interviewer has finished a turn. A persona
#: that talks over people gets a hair trigger; a slow one waits.
_EAGERNESS = {"slow": "low", "measured": "medium", "fast": "high"}

#: Transcription model for the interviewer's own speech. Their words are half
#: the evidence the evaluation layer reads, so this is not optional.
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

#: ISO-639-1 hint for the transcriber, per interview language.
#:
#: Hinglish maps to **None on purpose**. The vendor's `languages` (plural)
#: parameter is rejected by every transcription model — verified against the
#: live API on 2026-08-22 for `gpt-4o-mini-transcribe`, `gpt-4o-transcribe` and
#: `whisper-1` — so a code-mixed session can only be pinned to one language or
#: to none. Pinning either one systematically mangles the other half of the
#: sentence, so auto-detection is the least-wrong option until a transcriber
#: accepts a language set.
_TRANSCRIBE_LANGUAGE: dict[str, str | None] = {
    "english_indian": "en",
    "hindi": "hi",
    "hinglish": None,
}


def build_realtime_session(
    contract: EngineContract,
    *,
    voices: Sequence[str],
) -> dict[str, object]:
    """Compile the vendor session document for one persona's voice session.

    Args:
        contract: The persona's compiled engine contract.
        voices: Voice names the target provider accepts.

    Returns:
        A session document ready to hand to
        :meth:`~llm.base.RealtimeBroker.mint`, minus the model id.
    """
    directives = contract.voice_directives or {}
    pace = str(directives.get("pace", "measured"))

    # A persona that barges in needs the model to jump on the interviewer's
    # pauses; otherwise pace decides. Kept separate from _SPEED so the two can
    # diverge without one silently dragging the other.
    eagerness = "high" if directives.get("may_interrupt") else _EAGERNESS.get(pace, "medium")

    transcription: dict[str, object] = {"model": TRANSCRIBE_MODEL}
    hint = _TRANSCRIBE_LANGUAGE.get(str(directives.get("language", "english_indian")))
    if hint:
        transcription["language"] = hint

    return {
        "instructions": build_voice_system_prompt(
            contract.system_prompt,
            {
                "turn_policy": contract.turn_policy,
                "voice_directives": contract.voice_directives,
            },
        ),
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "transcription": transcription,
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": eagerness,
                    "create_response": True,
                    # The human must always be able to cut the persona off —
                    # interrupting a rambler is a skill the session exists to
                    # train, and it cannot be trained if the audio ignores it.
                    "interrupt_response": True,
                },
            },
            "output": {
                "voice": pick_voice(contract.candidate_id, voices),
                "speed": _SPEED.get(pace, 1.0),
            },
        },
    }
