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

`ENGINE_CONTRACT_VERSION = "v1.6"`, versioned **separately** from the persona
document so the engine can pin a contract version while personas keep evolving.
v1.1 added the language line, v1.2–v1.3 the dual-model runtime fields, v1.4 the
job spec (all below) — each of those changed the emitted prompt text. **v1.5 and
v1.6 do not**: the prompt is byte-identical and no field was added, but
identical inputs compile a different `tts_voice_id`, because the voice is picked
from the roster subset matching how the persona presents. The rule is *bump the
constant that covers what moved*, and what moved is the compiled contract.
v1.5 matched on `human_traits.gender_presentation`; v1.6 extends it to the
personas that carry no traits, which is most of them.

The Go engine needs exactly two reads: this contract, and the
[scorecard](/concepts/contracts/virtual-candidate.md) afterwards. It never parses
the full persona, never sees the archetype key, and never re-derives prompt text.

## v1.1 — the language line (2026-08-22)

The minor bump adds two things: a language directive as the first line of the
compiled prompt's `HOW YOU TALK` section, and a `language` key on
`voice_directives`. The Go engine needs no change — it parses by **major**
version and retains the minor, which `engine/internal/contract/contract_test.go`
already covers with an explicit `v1.1` case.

The directives themselves live in `LANGUAGE_DIRECTIVES` in
`candidate_agent/engine_contract.py`. Code owns the vocabulary; the model never
picks the language.

One consequence for any consumer: **a v1.1 persona may not speak English.**
Anything downstream that reads the transcript must not assume it does.

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

`turn_policy.barge_in_allowed` and `voice_directives.may_interrupt` are easy to
conflate and mean opposite directions of interruption: `barge_in_allowed` is
whether the **human interviewer** may cut the persona off; `may_interrupt` is
whether the **persona** may cut the human off (`speech.interrupts_interviewer`,
an archetype trait). Documented side by side in `docs/GO_ENGINE_CONTRACT.md`,
which was missing `barge_in_allowed` entirely until M1.2.

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
identity/headline → BACKGROUND → **THE ROLE YOU ARE INTERVIEWING FOR** (only
when a `job_title` was passed, rendered by `_role_section`; empty string, and
therefore no section, when absent — see v1.4 below) → HOW YOU TALK →
WHO YOU ARE UNDER THE SURFACE →
WHAT YOU ACTUALLY KNOW → HOW YOU ANSWER → ALWAYS → NEVER → **the realism layer**
(only when the persona carries a
[`HumanTraitProfile`](/concepts/contracts/virtual-candidate.md), rendered by
`_realism_section`; empty string, and therefore no section, when absent) →
HARD RULES → a closing instruction that *a convincing bad candidate is the
point*.

**HARD RULES come last, and the realism layer before them.** The realism layer
carries the only operator-supplied free text in the prompt (`function`,
`region`), so it must never be the model's most recent instruction; and its
environment lines used to contradict the hard rules outright — an
`ENVIRONMENT: hard stop at minute 20` sitting under *"never end the interview
yourself"*. The hard-stop directive now states both halves explicitly.

The realism layer renders as: HOW YOU COME ACROSS (affect, verbal style,
motivation, negotiation stance) → HOW YOU SPEAK AND LISTEN (vocabulary ceiling,
accent, code-switching, comprehension) → WHAT DOES NOT ADD UP ABOUT YOU
(integrity red flags) → THINGS YOU DO WITHOUT BEING ASKED (compliance traps,
never labelled as traps to the persona) → YOUR SITUATION RIGHT NOW (camera,
lateness, connection, hard stop) → WHO YOU ARE ON PAPER (the profile labels,
quoted).

Every line is an **instruction the model can act on**, produced by a directive
table keyed on the taxonomy value — never the token itself, and never a bare
number. `accent_strength=0.5` becomes *"You have a strong regional accent. Once
or twice the interviewer has to ask you to repeat a word."* A model cannot act
on `0.5`. `tests/test_architecture.py` asserts every value the schema accepts
has a directive, and that no directive merely restates its own key.

**Same persona in, byte-identical prompt out** — true both with and without a
`human_traits` layer and with or without a job spec; `_realism_section(None)`
and `_role_section(job_title="")` both return `""`, so a persona cast without
either compiles the same bytes it always did. Do not edit, summarise, or
append to it at runtime — session framing and audio config go in a separate
turn.

## Changing this file

Bump `ENGINE_CONTRACT_VERSION` with any change to the emitted prompt text: the
engine pins the version, and
`tests/test_candidate_rubric.py::test_system_prompt_is_byte_stable` will fail
otherwise. The prompt is the common case, not the whole rule — bump it for **any**
change that makes identical inputs compile a different contract, prompt bytes or
not. v1.5 is the worked example: same prompt, different `tts_voice_id`.

## Related

`docs/GO_ENGINE_CONTRACT.md` is the full spec, including the grading procedure ·
[engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) ·
`owner_handover/engine_contract_schema.json`


## v1.3 — the dual-model runtime fields

The Go engine runs **two models per session**: a speech model that talks, and a
reasoning model (the *Thinker*) that thinks alongside it. See
[the engine subsystem](/concepts/subsystems/engine.md). Four contract fields
exist so the reasoning half has something deterministic to reason *over*, and
one so the two halves sound like the same person.

| Field | Owner | Purpose |
|---|---|---|
| `precompiled_beliefs[]` | model authors the prose, code assigns `claim_id` in `knowledge_map` order | Seeds the claims ledger at turn 0. Stable ids across casts of the same seed. |
| `stall_phrases[]` | code, from the persona's own `verbal_tics` / `on_silence` | Filler played within 50 ms of a defer, in the persona's register. |
| `pregate_lexicon{}` | model authors `probe_aliases`, code owns `defer_at_or_below` | Spot an incoming hard question from partial speech. |
| `unlock_spec` | code, compiled from `reveals_depth_when` prose | `never` short-circuits per-turn assessment. |
| `tts_voice_id` | code, `sha256(candidate_id) % len(voices)` over the gender-matched subset (v1.5) | Stall clips must not be a different voice than the answer. |

All optional. A v1.0–v1.2 contract parses with them empty and the engine falls
back to the single-model path — the engine pins by **major** version.

`compile_unlock_spec` reads model-authored prose, so it is deliberately
conservative: a negation closes the door **unless** the sentence also names a
trigger word, in which case the negation was qualifying it. Both misreadings
cost something — a wrong `never` makes the unlock unreachable, a wrong
`conditional` burns a reasoning call every turn — so the rule is explicit and
tested in both directions rather than left to a prefix match.


## v1.4 — the role the persona is interviewing for (2026-09-01)

Until v1.4 **no job-spec field reached the compiled prompt at all**. The persona
was told who it was, how it spoke and what it knew, but never what job it had
walked in for. Two interviews for completely different roles compiled prompts
that differed only in the persona's own background — so the candidates were
interchangeable, and every session opened the same way.

The minor bump inserts one section between BACKGROUND and HOW YOU TALK:

```
THE ROLE YOU ARE INTERVIEWING FOR
{job_title} ({experience_level}, {company_type}, {job_location_type}, based in {location}).
{jd_precis(jd)}
Everything you say about your experience and motivation is anchored to THIS role.
```

`_compile_system_prompt` and `build_engine_contract` take the six fields as
keyword arguments defaulting to `""`. **An empty `job_title` renders nothing**,
exactly like `_realism_section(None)` — a contract compiled without a job spec
(the handover sample, the Go fixtures, hand-built test contracts) is byte-identical
to v1.3 apart from the version string. Empty parenthetical parts are skipped, and
`, based in {location}` is omitted when there is no location.

`jd_precis(jd, limit=400)` is **code-owned and deterministic**: whitespace
normalisation, then a cut at the last sentence end inside the limit, then a hard
cut if there is no sentence boundary. No model call — a JD is unbounded operator
free text, and a model summarising it here would make the same interview compile
different prompt bytes on every cast, which is the one thing this contract's
version pins.

The Go engine needs no change: it parses by **major** version, and v1.4 adds no
field. The only engine-visible difference is longer `system_prompt` bytes.

Reproducibility: `fingerprint` covers `system_prompt`, so it moves with the job
text. `seed_fingerprint` does not, and is unchanged — a re-cast of the same
interview and archetype still reproduces the same person.


## v1.5 — the voice matches how the persona presents (2026-09-01)

`tts_voice_id` is picked by `pick_voice(candidate_id, voices)`, which hashes over
whatever roster it is handed — and it was handed all thirty voices. A persona
whose `human_traits.gender_presentation` read `woman` therefore had roughly an
even chance of speaking in a man's voice: the same casting-time incoherence as
the persona cast under a man's name, heard rather than read.

`build_engine_contract` now filters the offered roster through
`engine_contract.voices_for_presentation` before picking:

| `gender_presentation` | Offered roster |
|---|---|
| `woman` | `llm.gemini_live.GEMINI_FEMALE_VOICES` ∩ the roster, in roster order |
| `man` | `GEMINI_MALE_VOICES` ∩ the roster, in roster order |
| `non_binary`, `unspecified`, no `human_traits` | the roster, unchanged |

The classification is a **vendor fact** (Google's Gemini-TTS voice table), owned
by `llm/gemini_live.py` beside the roster it classifies, and the two sets
partition it exactly — a voice appended to the roster without a classification
fails `tests/test_voice.py`. The filter preserves roster **order**, because
`pick_voice` is a modulus and the subset's order is contract too. `pick_voice`
itself is unchanged, so the fallback in `candidate_agent/voice.py` for
pre-`tts_voice_id` contracts still resolves against the full roster.

**No new field, no prompt-text change**, so the Go engine needs no change — it
parses by major version. The bump exists because the compiled contract moved for
identical inputs and nothing else records that: neither `fingerprint` nor
`seed_fingerprint` covers `tts_voice_id`.

**Already-cast personas keep their voice.** `tts_voice_id` is written once at
cast time and never recomputed at session time, so only personas cast from v1.5
on are gender-matched. The handover sample and the Go fixtures compile with
`human_traits=None` and are byte-identical to v1.4 apart from the version string.


## v1.6 — the trait-less personas get a matching voice too (2026-09-01)

v1.5 narrowed the roster only when the persona carried a `HumanTraitProfile`,
and the **default cast path has none**: `enroll_candidates` casts the fixed
catalog archetypes as `(key, None, None)` and the lazy session-start cast passes
no traits either. So the fix covered the custom-persona minority and left the
majority hashing over all thirty voices. It surfaced in production as a persona
named *Tanvi* speaking with a man's voice.

The casting draft gains one model-authored field,
`presented_gender` — `woman | man | neutral`, enum-constrained and **required**
in `CANDIDATE_DRAFT_JSON_SCHEMA`. It describes the identity the model just
wrote rather than choosing anything: *how does the name you authored read?*
Code owns the rest. `build_engine_contract` resolves the presentation as
`human_traits.gender_presentation` when there is a trait layer (code-owned,
never seen by the model, wins outright), otherwise
`normalize_presented_gender(presented_gender)` — which returns `""` for anything
outside the three values and **never raises**, because losing a cast over a bad
voice hint is worse than picking from thirty voices.

**No contract field and no prompt-text change**, so the Go engine needs no
change; it pins by major version. Same reason for the bump as v1.5: the compiled
`tts_voice_id` moved for identical inputs. The declared value is also stored on
[`VirtualCandidate`](/concepts/contracts/virtual-candidate.md) and folded into
`fingerprint`, so a stored persona explains the voice it speaks in —
`PERSONA_VERSION` v1.2 → **v1.3**.
