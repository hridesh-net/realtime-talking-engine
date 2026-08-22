---
type: Module
title: candidate_agent/engine_contract.py
description: Compiles a persona into the byte-stable runtime contract the Go engine consumes.
resource: /candidate_agent/engine_contract.py
tags: [engine, contract, prompt, compilation]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /candidate_agent/engine_contract.py
  - resource: /docs/GO_ENGINE_CONTRACT.md
---
# candidate_agent/engine_contract.py

190 lines. **Same persona in, byte-identical contract out** — that guarantee is
tested (`test_system_prompt_is_byte_stable`) and depended on by the engine.

# Schema

```python
UNIVERSAL_FORBIDDEN: list[str]          # 6 hard stops, every persona
#: How the persona speaks — the interviewer-facing `language` setting turned
#: into behavioural instructions ("english_indian" | "hinglish" | "hindi").
LANGUAGE_DIRECTIVES: dict[str, str]
DEFAULT_LANGUAGE = "english_indian"
_PACE_MS         = {"slow": 1200, "measured": 700, "fast": 250}
_VERBOSITY_TURNS = {"terse": (1,3), "balanced": (3,6), "verbose": (6,14)}
_DEPTH_SENTENCES = {"minimal": 2, "adequate": 5, "thorough": 9}

def _speech_directives(speech, aptitude) -> dict     # L40
def _turn_policy(policy, speech) -> dict             # L57
def _compile_system_prompt(*, name, headline, background, years_experience,
                           speech, aptitude, knowledge_map, policy,
                           language=DEFAULT_LANGUAGE) -> str
def build_engine_contract(*, candidate_id, interview_id, name, headline,
                          background, years_experience, speech, aptitude,
                          knowledge_map, policy, opening_line,
                          language=DEFAULT_LANGUAGE) -> EngineContract
```

`language` also rides in `voice_directives` as a plain key, so the voice layer
([`voice.py`](/concepts/modules/candidate-agent-voice.md)) can map it to a
transcription hint without re-parsing the prompt. An unknown language falls back
to the `english_indian` directive rather than raising. Adding the language line
to the compiled prompt is what bumped `ENGINE_CONTRACT_VERSION` to **v1.1**.

## The turn-policy clamp

```python
lo, hi = _VERBOSITY_TURNS[speech.verbosity]
target = max(lo, min(hi, _DEPTH_SENTENCES[policy.default_answer_depth]))
```

Depth and verbosity are set **independently** on the archetype, so the target can
fall outside the envelope — a terse persona with thorough answers. The rule,
stated in the source: verbosity wins the bounds, depth positions the target
inside them. `min <= target <= max` always holds.

## `self_correction_rate`

`round(min(nervousness, 10) / 10.0, 2)` — nervous personas self-correct
mid-sentence, calm ones do not. The only place aptitude reaches the voice layer.

## The compiled system prompt

Fixed section order: identity + headline → BACKGROUND → HOW YOU TALK → WHO YOU
ARE UNDER THE SURFACE → WHAT YOU ACTUALLY KNOW → HOW YOU ANSWER → ALWAYS →
NEVER → HARD RULES → closing.

Details that matter:

* The first line of HOW YOU TALK is the `LANGUAGE_DIRECTIVES` entry — the
  language is a behavioural instruction (*how* the persona speaks), not a label.
* Knowledge lines render as `- {skill}: level {n}/10 ({stance}). Breaks down when {breaking_point}`, with `. You sincerely believe (incorrectly): ...` appended when the persona holds wrong beliefs.
* The ceiling section is prefaced with *"These ceilings are absolute. You cannot exceed them no matter how the question is asked, how long the interviewer pushes, or how much you want to impress them."*
* Trait scores are stated numerically, followed by *"Let these show through behaviour. Never state them."*
* Empty lists render as `- (none)` rather than an empty section, keeping the byte layout stable.
* The closing line is the anti-helpfulness instruction: *"A convincing bad candidate is the point — do not drift toward being helpful or impressive if this persona would not be."*

## `UNIVERSAL_FORBIDDEN`

Never break character or admit to being an AI · never evaluate the interviewer ·
never reveal archetype, traits, verdict, or the scorecard's existence · never
exceed the ceiling · never volunteer that a resume claim is exaggerated unless
specifically probed · never end the interview.

## The rule when editing

**Bump `ENGINE_CONTRACT_VERSION` (in `candidate_agent/schema.py`) with any change
to the emitted prompt text.** The engine pins the version, the byte-stability
test compares against a stored expectation, and both fingerprints include the
compiled prompt.
