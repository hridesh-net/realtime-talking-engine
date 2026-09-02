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

Two providers now, so the seam this file's docstring used to anticipate is
split: :func:`build_realtime_session` compiles OpenAI Realtime's session
document (WebRTC, an SDP offer, a client secret), :func:`build_gemini_live_session`
compiles Gemini Live's (WebSocket, an ephemeral token, raw PCM), and
:func:`build_voice_session` dispatches. Both documents are still the vendor's
own shape rather than a neutral schema translated twice — what is shared is the
*decisions*, which is the part that has to stay identical: the same compiled
prompt, the same opening line, the same persona voice, the same "the human can
always interrupt" rule.

:func:`session_facts` reads back the handful of things the browser is told about
a compiled session. It lives here because the document shapes are owned here;
the control plane should not have to know where a given vendor keeps its voice
name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from candidate_agent.engine_contract import pick_voice
from candidate_agent.prompts import build_voice_system_prompt
from candidate_agent.schema import EngineContract

#: Speaking rate per persona pace. The realtime API takes a multiplier; these
#: are deliberately narrow — past about ±20% the voice stops sounding human.
_SPEED = {"slow": 0.85, "measured": 1.0, "fast": 1.15}

#: How readily the model decides the interviewer has finished a turn. A persona
#: that talks over people gets a hair trigger; a slow one waits.
_EAGERNESS = {"slow": "low", "measured": "medium", "fast": "high"}

#: Gemini Live has no semantic turn detection to hand a word like "eager" to —
#: it has a silence timer. Same intent expressed in milliseconds: a slow talker
#: gets a longer pause before the model assumes the interviewer is done. Below
#: about 500 ms the model cuts people off mid-sentence; past about 800 ms the
#: conversation starts to feel laggy.
_SILENCE_MS = {"slow": 800, "measured": 650, "fast": 500}

#: Padding kept in front of detected speech, so a turn does not lose its first
#: syllable to the detector.
PREFIX_PADDING_MS = 200

#: Transcription model for the interviewer's own speech on the OpenAI path.
#: Their words are half the evidence the evaluation layer reads, so this is not
#: optional — only configurable. The caller injects the configured id
#: (`llm.factory.resolve_transcribe_model`); this is the fallback for hand-built
#: callers and tests.
TRANSCRIBE_MODEL = "gpt-4o-transcribe"

#: What the UI shows as the transcription source when the talker transcribes
#: itself. Gemini Live emits both sides' transcripts inside the session, so
#: there is no separate STT model to name.
IN_SESSION_STT = "gemini-live (in-session)"

#: Vendor-side denoising on the OpenAI path. ``near_field`` is the headset /
#: laptop-mic profile, which is what a manager on a video call is using. This is
#: applied to what the *model hears*; the recording tapped in the browser stays
#: raw, because it is the evidence the report engine checks quotes against.
NOISE_REDUCTION = "near_field"

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


@dataclass(frozen=True)
class SessionFacts:
    """What the browser is told about a session it did not compile.

    None of it is secret and none of it authors persona behaviour — it is the
    status line ("who is talking, who is transcribing, is denoising on") plus
    the connect parameters a WebSocket client has to pass for itself. The
    instructions, the ceilings and the scorecard are not here and never will be.
    """

    #: The voice the persona speaks in. Stable across every session.
    voice: str
    #: Who turns the interviewer's speech into text.
    stt_source: str
    #: Vendor-side noise reduction profile, empty when the vendor applies none.
    noise_reduction: str
    #: Connect parameters the browser passes to the vendor's SDK verbatim.
    client_config: dict[str, object] = field(default_factory=dict)


def build_realtime_session(
    contract: EngineContract,
    *,
    voices: Sequence[str],
    transcribe_model: str = TRANSCRIBE_MODEL,
) -> dict[str, object]:
    """Compile the OpenAI Realtime session document for one persona.

    Args:
        contract: The persona's compiled engine contract.
        voices: Voice names the target provider accepts.
        transcribe_model: Speech-to-text model for the interviewer's own audio.

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

    transcription: dict[str, object] = {"model": transcribe_model, "prompt": _vocabulary(contract)}
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
            opening_line=contract.opening_line,
        ),
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "transcription": transcription,
                # Denoising the interviewer's mic before the model hears it.
                # The stored recording is tapped separately in the browser and
                # is deliberately not processed — see NOISE_REDUCTION.
                "noise_reduction": {"type": NOISE_REDUCTION},
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


def build_gemini_live_session(
    contract: EngineContract,
    *,
    voices: Sequence[str],
) -> dict[str, object]:
    """Compile the Gemini Live session document for one persona.

    Three keys, and the split between them is the security model:
    ``system_instruction`` and ``voice`` are sealed into the ephemeral token by
    :class:`~llm.gemini_live.GeminiLiveBroker` and never leave the server;
    ``client_config`` is handed to the browser verbatim, because a WebSocket
    client has to pass its own connect config and none of these fields author
    behaviour. Its keys are the Live API's wire names, so the browser can use it
    as-is.

    Args:
        contract: The persona's compiled engine contract.
        voices: Voice names the target provider accepts.
    """
    directives = contract.voice_directives or {}
    pace = str(directives.get("pace", "measured"))

    return {
        "system_instruction": build_voice_system_prompt(
            contract.system_prompt,
            {
                "turn_policy": contract.turn_policy,
                "voice_directives": contract.voice_directives,
            },
            opening_line=contract.opening_line,
        ),
        # The voice was chosen at cast time and stored, so the persona sounds
        # the same here as it does in the Go engine's pre-synthesized stalls.
        # `pick_voice` is the fallback for contracts compiled before the field
        # existed — same rule, same roster, same answer.
        "voice": contract.tts_voice_id or pick_voice(contract.candidate_id, voices),
        "client_config": {
            # AUDIO only: the Live API refuses a session asking for both
            # modalities, and text arrives through the transcriptions below.
            "responseModalities": ["AUDIO"],
            # Both sides transcribed in-session. The interviewer's words are
            # half the evidence the evaluation layer reads; the persona's are
            # the other half.
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            # An audio-only Live session is capped at ~15 minutes and the server
            # warns before cutting it. Asking for resumption is what makes that
            # a reconnect rather than the end of the interview.
            "sessionResumption": {},
            # Lets the browser seed the one synthetic turn that gets the persona
            # to speak first. Only legal before the first real turn.
            "historyConfig": {"initialHistoryInClientContent": True},
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "prefixPaddingMs": PREFIX_PADDING_MS,
                    "silenceDurationMs": _SILENCE_MS.get(pace, _SILENCE_MS["measured"]),
                },
                # The human must always be able to cut the persona off. Same
                # rule as `interrupt_response` on the OpenAI path.
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
            },
        },
    }


#: Provider name -> session-document compiler, normalised to one call shape so
#: the dispatcher below is a lookup rather than a chain of provider tests. A
#: table for the same reason `llm.factory` keeps one: adding a provider is a row,
#: not an edit to the caller.
_SESSION_BUILDERS: dict[str, Callable[[EngineContract, Sequence[str], str], dict[str, object]]] = {
    "gemini": lambda contract, voices, _transcribe: build_gemini_live_session(
        contract, voices=voices
    ),
    "openai": lambda contract, voices, transcribe: build_realtime_session(
        contract, voices=voices, transcribe_model=transcribe
    ),
}


def build_voice_session(
    contract: EngineContract,
    *,
    provider: str,
    voices: Sequence[str],
    transcribe_model: str = TRANSCRIBE_MODEL,
) -> dict[str, object]:
    """Compile the session document for whichever provider is wired up.

    Args:
        contract: The persona's compiled engine contract.
        provider: The broker's provider name.
        voices: Voice names that provider accepts.
        transcribe_model: OpenAI-path speech-to-text model; ignored on Gemini,
            which transcribes inside the session.

    Raises:
        ValueError: No session shape is known for ``provider``. Loudly, rather
            than defaulting: silently compiling one vendor's document for
            another's endpoint fails at mint time with a shape error that says
            nothing about the cause.
    """
    builder = _SESSION_BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"no voice session shape for provider {provider!r}")
    return builder(contract, voices, transcribe_model)


def session_facts(session: Mapping[str, object]) -> SessionFacts:
    """Read back the client-visible facts about a compiled session document.

    Shape-driven rather than provider-driven on purpose: the caller has a
    document, not a branch, and adding a third provider should not mean adding
    a third `if` in the control plane.
    """
    client_config = session.get("client_config")
    if isinstance(client_config, dict):
        # A document carrying its own client config is one whose talker
        # transcribes itself; there is no separate STT model to name.
        return SessionFacts(
            voice=str(session.get("voice", "")),
            stt_source=IN_SESSION_STT,
            noise_reduction="",
            client_config=client_config,
        )

    audio = session.get("audio")
    audio = audio if isinstance(audio, dict) else {}
    output = audio.get("output")
    output = output if isinstance(output, dict) else {}
    inp = audio.get("input")
    inp = inp if isinstance(inp, dict) else {}
    transcription = inp.get("transcription")
    transcription = transcription if isinstance(transcription, dict) else {}
    reduction = inp.get("noise_reduction")
    reduction = reduction if isinstance(reduction, dict) else {}

    return SessionFacts(
        voice=str(output.get("voice", "")),
        stt_source=str(transcription.get("model", "")),
        noise_reduction=str(reduction.get("type", "")),
        client_config={},
    )


def _vocabulary(contract: EngineContract) -> str:
    """A transcription hint listing the skills this interview will name.

    Transcribers mangle domain nouns they have no reason to expect — "Kafka"
    becomes "Kavka", "gRPC" becomes "GRPC" or "jee arr pee see" — and those are
    exactly the words the evaluation layer looks for. The vendor takes a free
    text `prompt` as a vocabulary bias; the skills are already in the contract,
    so this is code composing a hint, not a model authoring one. Sorted, so the
    same contract always produces the same string.
    """
    skills = sorted(contract.knowledge_ceiling)
    if not skills:
        return "Job interview."
    return f"Job interview covering: {', '.join(skills)}."
