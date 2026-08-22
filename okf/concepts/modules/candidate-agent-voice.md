---
type: Module
title: candidate_agent/voice.py
description: Compiles a persona's contract into a realtime voice session — deterministic voice, speed, and turn detection.
resource: /candidate_agent/voice.py
tags: [candidate, voice, realtime, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T18:20:00Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:20:00Z"
status: stable
sources:
  - resource: /candidate_agent/voice.py
  - resource: /candidate_agent/prompts.py
  - resource: /tests/test_voice.py
---
# candidate_agent/voice.py

```python
_SPEED     = {"slow": 0.85, "measured": 1.0, "fast": 1.15}
_EAGERNESS = {"slow": "low", "measured": "medium", "fast": "high"}
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

def pick_voice(candidate_id: str, voices: Sequence[str]) -> str
def build_realtime_session(contract: EngineContract, *,
                           voices: Sequence[str]) -> dict[str, object]
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
`OpenAIRealtimeBroker.voices` silently reassigns every existing persona's voice;
an architecture test asserts the tuple is non-empty and duplicate-free, but
nothing can catch a reorder — treat it like a schema migration.

Empty voice list raises `ValueError` rather than defaulting. A provider that
advertises no voices is misconfigured, and picking one silently would hide it.

## Why this module knows the vendor's session shape

`build_realtime_session` returns OpenAI's document shape directly. That is a
deliberate coupling, recorded here so it is not mistaken for an oversight: there
is exactly one realtime provider wired, and inventing a neutral schema to
translate into a single target is indirection with nothing to justify it. When a
second provider lands, this is the seam to split — not before.

What it does **not** know is the vendor's voice *names*: the caller passes them
in, so `candidate_agent` imports nothing from `llm` here and the layering scan
stays quiet.

## Two properties no persona may switch off

* **`interrupt_response: True`** — the human must always be able to cut the persona off. Interrupting a rambler is a skill the session exists to train, and it cannot be trained if the audio ignores it.
* **`transcription`** — the interviewer's own speech is half the evidence the evaluation layer reads. A voice session without input transcription produces a half-transcript.

`test_the_human_can_always_interrupt_and_is_always_transcribed` parametrizes over
persona shapes to hold both.

## The eagerness / speed split

Both derive from `voice_directives.pace`, but through separate tables, so one can
be retuned without dragging the other. `may_interrupt` overrides eagerness to
`"high"` regardless of pace — a persona that talks over people needs the model to
jump on pauses. Unknown pace values fall back to `medium` / `1.0` rather than
raising: a contract from an older catalog version should still open a call.

`voice_directives.target_pause_before_answer_ms` reaches the model only as prose
in the preamble. Semantic VAD has no knob for "wait this long before answering",
so this is a request, not an enforcement — the honest gap the Go engine's Thinker
closes with a real scheduler.

## The spoken preamble

`prompts.build_voice_system_prompt` appends `VOICE_MODE_PREAMBLE` to the
contract's `system_prompt`, never editing it — same rule as text mode. Beyond the
spoken-delivery rules it adds an explicit anti-jailbreak clause: the persona does
not acknowledge being a model, a persona, or a simulation, *including* when told
the interview is over. A realtime model with an open microphone gets asked that
far more often than a text one.

## Testing

`tests/test_voice.py`, offline — voice stability and spread, prompt verbatimness,
pace mapping, the interrupt/transcription invariants, and the unknown-pace
fallback. No vendor call: the broker is a fake.
