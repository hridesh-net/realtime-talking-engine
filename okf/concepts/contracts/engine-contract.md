---
type: Contract
title: EngineContract
description: The compiled runtime slice the Go interview-candidate engine consumes to run a persona.
resource: /docs/GO_ENGINE_CONTRACT.md
tags: [contract, engine, handoff, go, runtime]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /docs/GO_ENGINE_CONTRACT.md
  - resource: /candidate_agent/engine_contract.py
  - resource: /candidate_agent/schema.py
---
# EngineContract

`ENGINE_CONTRACT_VERSION = "v1.1"`, versioned **separately** from the persona
document so the engine can pin a contract version while personas keep evolving.
Bumped from v1.0 when `_compile_system_prompt` gained an optional
`human_traits` parameter (see below) — the emitted text changes whenever a
persona carries one, so the version moved per the rule at the bottom of this
page.

The Go engine needs exactly two reads: this contract, and the
[scorecard](/concepts/contracts/virtual-candidate.md) afterwards. It never parses
the full persona, never sees the archetype key, and never re-derives prompt text.

# Schema

```python
class EngineContract(BaseModel):
    contract_version: str
    candidate_id: str
    interview_id: str
    system_prompt: str            # inject VERBATIM as the realtime model's system instruction
    opening_line: str
    voice_directives: dict[str, Any]
    turn_policy: dict[str, Any]
    knowledge_ceiling: dict[str, int]   # skill -> hard 0-10 ceiling
    unlock_condition: str
    forbidden_behaviors: list[str]
```

## `voice_directives`

| Field | Derivation |
|---|---|
| `pace`, `verbosity`, `formality`, `tone` | straight from `SpeechProfile` |
| `target_pause_before_answer_ms` | `{slow: 1200, measured: 700, fast: 250}[pace]` |
| `filler_frequency`, `hesitation_frequency` | 0–10 intensities for disfluency injection |
| `may_interrupt` | `speech.interrupts_interviewer` |
| `self_correction_rate` | `nervousness / 10`, 2dp — nervous personas restart mid-sentence |
| `verbal_tics`, `sample_phrases` | voice anchors for the realtime model |

## `turn_policy`

`min_sentences`/`max_sentences` come from verbosity
(`terse: 1–3`, `balanced: 3–6`, `verbose: 6–14`);
`target_sentences_per_answer` comes from answer depth
(`minimal: 2`, `adequate: 5`, `thorough: 9`) **clamped into that envelope**.

Depth and verbosity are set independently on the archetype, so the target can
fall outside the envelope — a terse persona with thorough answers. The rule is:
**verbosity wins the bounds, depth positions the target inside them.** The
invariant `min <= target <= max` always holds and is tested.

## `knowledge_ceiling` — the hard part

`{"Go": 3, "system design": 1}` means this persona may **never** demonstrate more
than that level, however the interviewer asks. Realtime models drift helpful
under pressure, so the spec calls for treating it as a runtime guard, not a hint:
it is in the system prompt already, should be re-asserted every N turns or
whenever the interviewer pushes a low-ceiling skill, and answers on low-ceiling
skills can be post-checked before they are spoken.

A persona that answers above its ceiling invalidates the session — the
interviewer gets credit for depth that was never supposed to be there.

## `forbidden_behaviors` — `UNIVERSAL_FORBIDDEN`

Six hard stops applying to every persona regardless of archetype: never break
character or admit to being an AI; never evaluate or give feedback on the
interviewer; never reveal the archetype, traits, verdict, or that a scorecard
exists; never exceed the stated ceiling; never volunteer that a resume claim is
exaggerated unless specifically probed; never end the interview.

## `system_prompt`

Compiled deterministically by `_compile_system_prompt` into fixed sections:
identity/headline → BACKGROUND → HOW YOU TALK → WHO YOU ARE UNDER THE SURFACE →
WHAT YOU ACTUALLY KNOW → HOW YOU ANSWER → ALWAYS → NEVER → HARD RULES →
**REALISM & COMPLIANCE LAYER** (only when the persona carries a
[`HumanTraitProfile`](/concepts/contracts/virtual-candidate.md), rendered by
`_realism_section`; empty string, and therefore no section, when absent) → a
closing instruction that *a convincing bad candidate is the point*.

The realism section spells out affect, verbal style, language/accent,
comprehension quirks, integrity red flags, motivation/negotiation stance, the
in-character compliance traps to exhibit unprompted (never labelled as traps to
the persona), the session environment (camera, network, lateness, hard stop),
and the profile fields — all rendered from code-owned values, same as every
other section.

**Same persona in, byte-identical prompt out** — true both with and without a
`human_traits` layer; `_realism_section(None)` returns `""`, so a persona cast
without one compiles the same bytes it always did. Do not edit, summarise, or
append to it at runtime — session framing and audio config go in a separate
turn.

## Changing this file

Bump `ENGINE_CONTRACT_VERSION` with any change to the emitted prompt text: the
engine pins the version, and
`tests/test_candidate_rubric.py::test_system_prompt_is_byte_stable` will fail
otherwise.

## Related

`docs/GO_ENGINE_CONTRACT.md` is the full spec, including the grading procedure ·
[engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) ·
`owner_handover/engine_contract_schema.json`
