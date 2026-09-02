---
type: Module
title: candidate_agent/voice.py
description: Compiles a persona's contract into a realtime voice session for either provider — deterministic voice, speed, opening line, and turn detection.
resource: /candidate_agent/voice.py
tags: [candidate, voice, realtime, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T18:20:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-01T00:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:20:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /candidate_agent/voice.py
  - resource: /candidate_agent/prompts.py
  - resource: /tests/test_voice.py
---
# candidate_agent/voice.py

```python
_SPEED      = {"slow": 0.85, "measured": 1.0, "fast": 1.15}   # openai
_EAGERNESS  = {"slow": "low", "measured": "medium", "fast": "high"}  # openai
_SILENCE_MS = {"slow": 800, "measured": 650, "fast": 500}     # gemini VAD
PREFIX_PADDING_MS = 200
TRANSCRIBE_MODEL  = "gpt-4o-transcribe"          # fallback; injected in practice
IN_SESSION_STT    = "gemini-live (in-session)"
NOISE_REDUCTION   = "near_field"                 # openai, vendor-side
#: ISO-639-1 hint for the transcriber, per interview language.
#: "hinglish" maps to None ON PURPOSE — see below.
_TRANSCRIBE_LANGUAGE = {"english_indian": "en", "hindi": "hi", "hinglish": None}

@dataclass(frozen=True)
class SessionFacts:
    voice: str; stt_source: str; noise_reduction: str
    client_config: dict[str, object]

def pick_voice(candidate_id: str, voices: Sequence[str]) -> str
def build_realtime_session(contract, *, voices,
                           transcribe_model=TRANSCRIBE_MODEL) -> dict[str, object]
def build_gemini_live_session(contract, *, voices) -> dict[str, object]
def build_voice_session(contract, *, provider, voices,
                        transcribe_model=TRANSCRIBE_MODEL) -> dict[str, object]
def session_facts(session: Mapping[str, object]) -> SessionFacts
```

The voice counterpart to
[`session.py`](/concepts/modules/candidate-agent-session.md), and the same
determinism split: **code owns** the instructions, the voice, the speaking rate,
and how eagerly the model decides the interviewer has stopped talking; **the
model owns** only what it says.

## Voice choice is a persona property, not a setting

`pick_voice` hashes `candidate_id` — itself `vc-<sha256(seed)[:12]>` — and
indexes into the provider's voice tuple. So a re-cast of the same
`(interview, archetype)` keeps the same voice: the audio equivalent of
`seed_fingerprint`. Two managers practising against "Ravi Sharma" hear the same
person, which is the comparability requirement the whole repo is built around.

**This makes the provider's voice ordering part of the contract.** Reordering
`OpenAIRealtimeBroker.voices` or `GEMINI_LIVE_VOICES` silently reassigns every
existing persona's voice; an architecture test asserts the tuple is non-empty
and duplicate-free, but nothing can catch a reorder — treat it like a schema
migration.

On the Gemini path `pick_voice` is only the *fallback*: the compiled contract
already carries `tts_voice_id`, chosen at cast time from the same roster, and
`build_gemini_live_session` prefers it. Same rule, same list, same answer — but
it also matches the voice the Go engine pre-synthesized the stall clips in.

Empty voice list raises `ValueError` rather than defaulting. A provider that
advertises no voices is misconfigured, and picking one silently would hide it.

## Why this module knows the vendors' session shapes

Each builder returns its vendor's document shape directly, and `_SESSION_BUILDERS`
maps provider name → builder so `build_voice_session` is a lookup rather than a
chain of provider tests. (That is not only taste: `test_ocp_new_provider_needs_no_agent_change`
fails any `== "gemini"` literal in this package.)

This is where the seam this file's docstring anticipated was actually split, and
the answer was **not** a neutral schema. What the two paths share is the
*decisions* — the same compiled prompt, the same opening line, the same persona
voice, the same "the human can always interrupt" rule — which is the part that
has to stay identical. A neutral schema translated twice would have added a
layer whose only job was to be translated away, and the two documents genuinely
have almost no fields in common.

The vendor SDKs stay in `llm/`: `build_gemini_live_session` returns a plain dict
whose nested keys are the Live API's own wire names, and `GeminiLiveBroker`
translates it into typed SDK objects. `candidate_agent` imports one thing from
`llm` — the voice roster — and nothing that touches a network.

`session_facts` reads the client-visible half back out of whichever document it
is handed (voice, STT source, vendor noise reduction, `client_config`), so the
control plane never branches on a provider name and never learns where a given
vendor keeps its voice.

## Two properties no persona may switch off

* **Barge-in** — `interrupt_response: True` on OpenAI, `activityHandling: START_OF_ACTIVITY_INTERRUPTS` on Gemini. The human must always be able to cut the persona off. Interrupting a rambler is a skill the session exists to train, and it cannot be trained if the audio ignores it.
* **Transcription of the interviewer** — a `transcription` model on OpenAI, `inputAudioTranscription` on Gemini. Their own speech is half the evidence the evaluation layer reads. A voice session without it produces a half-transcript.

`test_the_human_can_always_interrupt_and_is_always_transcribed` and
`test_gemini_transcribes_both_sides_and_can_survive_the_session_cap` hold both.

## The opening line

`build_voice_system_prompt` takes `opening_line` and appends a `THE FIRST THING
YOU SAY` block — appended, never interpolated into the compiled contract, same
rule as the preamble. Both builders pass `contract.opening_line`, so the two
providers deliver the same first utterance.

Until 2026-09-01 the voice path never mentioned it: the line was authored at
cast time, stored, written as turn 0 in *text* mode, and silently dropped in
voice, so every spoken interview opened with an improvised generic greeting. A
contract with an empty `opening_line` gets no block at all, which keeps
hand-built contracts and older fixtures compiling unchanged.

## Transcription vocabulary and noise reduction (OpenAI path)

`_vocabulary` composes the transcriber's `prompt` in code from
`sorted(contract.knowledge_ceiling)` — "Job interview covering: …". Transcribers
mangle exactly the domain nouns the evaluation layer looks for ("Kafka" →
"Kavka"), and the skills are already in the contract, so this is code composing
a hint rather than a model authoring one. Sorted, so one contract always
produces one string.

`audio.input.noise_reduction: {"type": "near_field"}` denoises what the *model*
hears — the headset/laptop-mic profile. It does not touch the stored recording,
which the browser taps separately and deliberately leaves raw.

## The transcription language hint — and the Hinglish hole

The contract's `voice_directives.language` (v1.1) becomes the transcriber's
`language` hint via `_TRANSCRIBE_LANGUAGE`. **Hinglish sends no hint at all, on
purpose.** The vendor's `languages` (plural) parameter is rejected by
`gpt-4o-mini-transcribe`, `gpt-4o-transcribe` and `whisper-1` alike — verified
against the live API on 2026-08-22 — so a code-mixed session can only be pinned
to one language or to none, and pinning either half systematically mangles the
other. Auto-detection is the least-wrong option until a transcriber accepts a
language set. When one does, this map is the place to change.

## The eagerness / speed / silence split

Both derive from `voice_directives.pace`, but through separate tables, so one can
be retuned without dragging the other. `may_interrupt` overrides eagerness to
`"high"` regardless of pace — a persona that talks over people needs the model to
jump on pauses. Unknown pace values fall back to `medium` / `1.0` rather than
raising: a contract from an older catalog version should still open a call.

Gemini Live has no semantic eagerness to hand a word to — it has a silence
timer — so `_SILENCE_MS` expresses the same intent in milliseconds: a slow
talker gets longer before the model assumes the interviewer is done. The range
is bounded by feel rather than by the API: below ~500 ms the model cuts people
off mid-sentence, past ~800 ms the conversation drags.
`test_gemini_turn_detection_follows_pace_and_stays_conversational` pins both the
band and the ordering.

`voice_directives.target_pause_before_answer_ms` reaches the model only as prose
in the preamble. Neither vendor's VAD has a knob for "wait this long before
answering", so this is a request, not an enforcement — the honest gap the Go
engine's Thinker closes with a real scheduler.

## The spoken preamble

`prompts.build_voice_system_prompt` appends `VOICE_MODE_PREAMBLE` to the
contract's `system_prompt`, never editing it — same rule as text mode. Beyond the
spoken-delivery rules it adds an explicit anti-jailbreak clause: the persona does
not acknowledge being a model, a persona, or a simulation, *including* when told
the interview is over. A realtime model with an open microphone gets asked that
far more often than a text one.

## Testing

`tests/test_voice.py`, offline — voice stability and spread, prompt
verbatimness, opening-line delivery, pace mapping on both providers, the
interrupt/transcription invariants, the unknown-pace fallback, dispatch by
provider (and the `ValueError` for an unknown one), roster identity, and that
`client_config` carries neither the prompt nor the opening line. No vendor call:
the broker is a fake, one per provider.

`tests/test_gemini_live_mint.py` is the `--live` counterpart — a smoke test that
the vendor still accepts a whole `LiveConnectConfig` inside
`live_connect_constraints` on the configured model id, which is the one thing
the offline suite cannot see.
