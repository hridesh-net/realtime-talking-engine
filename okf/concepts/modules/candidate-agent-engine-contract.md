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

def jd_precis(jd, limit=JD_PRECIS_LIMIT) -> str       # code-owned, no model call
def _role_section(*, job_title, jd, company_type, experience_level,
                  job_location_type, location) -> str
def _speech_directives(speech, aptitude) -> dict
def _turn_policy(policy, speech) -> dict
def _compile_system_prompt(*, name, headline, background, years_experience,
                           speech, aptitude, knowledge_map, policy,
                           language=DEFAULT_LANGUAGE,
                           job_title="", jd="", company_type="",
                           experience_level="", job_location_type="",
                           location="") -> str
def build_engine_contract(*, candidate_id, interview_id, name, headline,
                          background, years_experience, speech, aptitude,
                          knowledge_map, policy, opening_line,
                          language=DEFAULT_LANGUAGE, voices=(),
                          job_title="", jd="", company_type="",
                          experience_level="", job_location_type="",
                          location="") -> EngineContract
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

Fixed section order: identity + headline → BACKGROUND → THE ROLE YOU ARE
INTERVIEWING FOR → HOW YOU TALK → WHO YOU ARE UNDER THE SURFACE → WHAT YOU
ACTUALLY KNOW → HOW YOU ANSWER → ALWAYS → NEVER → the realism layer → HARD
RULES → closing.

Details that matter:

* THE ROLE section (contract **v1.4**) renders only when a `job_title` was
  passed, the same conditional trick `_realism_section` uses — so a contract
  compiled without a job spec is byte-identical to v1.3. `jd_precis` cuts the
  JD at a sentence boundary inside 400 chars, in code: a model summarising it
  would make the same interview compile different bytes each cast.

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

## The voice roster — `GEMINI_TTS_VOICES`

`build_engine_contract` picks `tts_voice_id` via `pick_voice(candidate_id,
voices)`, and as of M1.2 the control plane actually passes a roster:
`GEMINI_TTS_VOICES`, defined in this module next to `pick_voice`, mirrors the Go
engine's `defaultTTSVoices` (`engine/internal/config/config.go`) **exactly** —
same 30 voices, same order. `control_plane/api.py` imports it and passes
`voices=GEMINI_TTS_VOICES` at both call sites that cast a persona (enrollment
and lazy session-start casting); before this, `voices` defaulted to `()` and
every live-cast persona's `tts_voice_id` came back `""`.

The list is append-only, for the reason `pick_voice`'s docstring on the roster
states: the choice is `hash(candidate_id) % len(voices)`, so it is a function of
the list's order and length. `tts_voice_id` is computed once at cast time and
frozen into the stored contract — never recomputed at session time
(`okf/concepts/determinism.md`) — so reordering the roster would silently
repoint the voice of every already-cast persona.

### `voices_for_presentation` — the voice matches the persona (v1.5)

`pick_voice` hashes over whatever roster it is handed, which meant a persona
whose `human_traits.gender_presentation` read `woman` could be cast in a man's
voice. `voices_for_presentation(voices, gender_presentation)` narrows the roster
before `pick_voice` sees it:

| Presentation | Offered roster |
|---|---|
| `woman` | `llm.gemini_live.GEMINI_FEMALE_VOICES` ∩ the roster, in roster order |
| `man` | `GEMINI_MALE_VOICES` ∩ the roster, in roster order |
| `non_binary`, `unspecified`, `neutral`, absent, `""` | the roster, unchanged |

It takes the *presentation*, not its source, so one rule serves both inputs —
`build_engine_contract` decides which to hand it.

### Which presentation, and who declared it (v1.6)

v1.5 read `human_traits.gender_presentation` and did nothing when there was no
trait layer — which is the **default** cast path, so most personas were
unaffected and the bug reached production as a persona named *Tanvi* speaking
with a man's voice. `build_engine_contract` now resolves in order:

1. `human_traits.gender_presentation` when `human_traits is not None`. Code
   owned, composed from fixed presets, never seen by the model — it wins.
2. Otherwise `normalize_presented_gender(presented_gender)`, the casting
   model's declaration of how the name it just authored reads.

`normalize_presented_gender(value)` accepts only `PRESENTED_GENDER_VALUES`
(`woman | man | neutral`) and returns `""` for everything else — a missing key,
`None`, `"female"`, a sentence. **It never raises**: a model that returned a bad
enum has still written a usable persona, and losing the cast over a voice hint
is the worse failure. `""` and `neutral` both take the full-roster branch.

`agent.generate` reads the field off the parsed draft and passes it down, so
neither `control_plane/api.py` cast site needed a signature change and the agent
stays persistence- and vendor-free.

Three things the implementation is careful about:

* **The sets live in `llm/gemini_live.py`, imported not restated.** The
  classification is a vendor fact (Google's Gemini-TTS voice table) and belongs
  with the roster it classifies; `candidate_agent` → `llm` is the allowed
  direction. They partition the roster exactly, and `tests/test_voice.py`
  asserts it, so a voice appended to the roster without a classification fails.
* **Order is preserved.** `pick_voice` is `hash % len(voices)` indexing into the
  sequence, so the subset's order is contract as much as the roster's is.
  Sorting or set-iterating here would repoint every persona.
* **`pick_voice` is untouched.** Its signature and behaviour are unchanged, so
  the fallback in `candidate_agent/voice.py` for old contracts with no
  `tts_voice_id` — which has no traits in scope — still resolves against the
  full roster.

A roster carrying voices in neither set (a test roster, the OpenAI names) would
narrow to nothing under a gendered presentation, so the filter falls back to the
full roster rather than raising: an unclassified voice is better than no voice.

**Already-cast personas are unaffected.** `tts_voice_id` is frozen into the
stored contract at cast time and never recomputed, so only personas cast from
here on are gender-matched.

`build_engine_contract` also asserts, right after picking the voice, that it is
non-empty and a member of the offered roster before building the contract —
defence in depth on top of `pick_voice`'s own by-construction guarantee, since
`tts_voice_id` is exactly the kind of frozen field a silent regression here
would corrupt for every future cast until caught.

## The sample fixture is generated, not hand-written

`owner_handover/engine_contract_sample.json` (and its Go-side twin,
`engine/internal/contract/testdata/engine_contract_sample.json`) are produced by
`scripts/export_engine_contract_sample.py`, which drives `build_engine_contract`
and its helpers over a real persona's fields — no live model call, fully
deterministic (same input, byte-identical output, proven by running it twice
and diffing). Before M1.2 both files were still on `contract_version: "v1.0"`
with all five v1.3 fields absent, and nothing caught it:
`scripts/export_schemas.py --check` validated schemas only. It now also asserts
the sample's `contract_version` matches `ENGINE_CONTRACT_VERSION` and that
`precompiled_beliefs`, `stall_phrases`, `pregate_lexicon`, `unlock_spec` and
`tts_voice_id` are all non-empty — see
[owner-handover.md](/concepts/subsystems/owner-handover.md).

## The rule when editing

**Bump `ENGINE_CONTRACT_VERSION` (in `candidate_agent/schema.py`) with any change
to the emitted prompt text.** The engine pins the version, the byte-stability
test compares against a stored expectation, and both fingerprints include the
compiled prompt.
