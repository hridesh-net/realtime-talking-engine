---
type: Principle
title: The determinism split
description: What code owns and what the model may author — the organizing rule of this repository.
resource: /
tags: [determinism, reproducibility, guardrails, core-idea]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /report_engine/judge.py
  - resource: /report_engine/validate.py
  - resource: /report_engine/narrate.py
  - resource: /candidate_agent/agent.py
  - resource: /expectation_agent/agent.py
  - resource: /candidate_agent/archetypes.py
  - resource: /expectation_agent/rubric.py
  - resource: /candidate_agent/session.py
  - resource: /candidate_agent/voice.py
---
# The determinism split

Read this before changing either agent. Both are built the same way, and the
split is the reason the output is trustworthy.

> The model fills in the blanks. It cannot move the walls.

## Why

Two independent requirements force it:

1. **Comparability.** Training reports only mean something if two interviewers can be measured against *the same candidate*. If the persona drifts between sessions, the comparison is noise.
2. **Fairness / auditability.** An expectation whose criteria and weights the model can rewrite per run is not a rubric — it is a suggestion. Fixed criteria applied identically to every interview for a role is the defensible position.

## Candidate agent

| Owned by code | Owned by the model |
|---|---|
| Which archetype | The person's name, headline, background, years |
| The verdict (`select`/`reject`/`borderline`) | `verdict_rationale`, written against the real skills |
| Every trait score, drawn from the archetype's bounds by a seeded RNG | Talking points, breaking points, wrong beliefs |
| The knowledge band (skill-level ceiling) | Where inside the band each skill sits (then clamped) |
| Scorecard signal ids and weights | The wording of each signal, grounded in this job |
| Speech spec (pace, verbosity, filler/hesitation, formality, interrupts) | Verbal tics and sample phrases |
| Answer policy defaults (depth, on-unknown, on-pressure, on-silence) | `reveals_depth_when`, `always_does`, `never_does` |
| The compiled engine contract and system prompt | `opening_line` |
| The voice, and the validation of the declaration it is picked from | `presented_gender` — *how the name it authored reads*, not which voice to use |
| Resume-claim truthfulness enum validation | The claims themselves |
| Every realism-taxonomy value (`HumanTraitProfile`, when present) — affect, verbal style, language/comprehension, motivation, negotiation stance, compliance traps, environment, profile — **and the behavioural directive each one compiles to** | Nothing — the model never sees or authors `human_traits`; it is composed by `trait_dimensions.compose_human_traits` from fixed presets before the call and injected into the compiled prompt after |

A taxonomy value is only code-owned if the *behaviour* is. Emitting
`affect: flirtatious_inappropriate` into the prompt looks deterministic — the
same persona compiles the same bytes — but it hands the model an underscore-
joined token and lets it decide what that means, which is authoring persona
behaviour by another route. Every value therefore renders through a directive
table in `candidate_agent/engine_contract.py`, and a test asserts no directive
restates its own key.

**A persona is compiled once and replayed.** The full `VirtualCandidate`,
compiled `system_prompt` included, is stored as `persona_json` and a session
resolves it from the database rather than re-deriving it. That makes casting-time
coherence a correctness property, not a nicety: `opening_line`, `sample_phrases`,
`verbal_tics` and `always_does` are model-authored and *stored*, so anything the
casting model cannot see is permanently missing from the artifact that runs. The
realism layer and the profile facts therefore reach the casting prompt as well as
the compiled one (`engine_contract.casting_realism_note`) — before that, a
persona told it joined six minutes late had an opening line written as though it
arrived on time, and one whose profile said `gender presentation: woman` was cast
under a man's name.

**Beliefs are precompiled, never invented at runtime.** The live engine runs a
reasoning model alongside the speech model, and the tempting shortcut is to let
it improvise a wrong answer when the interviewer probes past the ceiling. That
would void `seed_fingerprint`: two sessions on the same contract would hold
different false beliefs. So `contract.precompiled_beliefs` fixes them at cast
time with the material to sustain them — `elaborations` for when the persona is
pushed, `vague_deflections` for a skill it cannot really discuss — and the
runtime only retrieves and rephrases. Vagueness is a generation target with
literal material behind it, not an absence of output.

Enforcement is not by prompt alone — the agent **re-imposes** the code side after
the call:

* `_build_knowledge_map` clamps every level into `archetype.knowledge_band` and restores any required skill the model dropped or renamed.
* `_build_scorecard` iterates `archetype.must_discover`, so invented ids are silently discarded and weights always come from the catalog.
* `_stance` and `ResumeClaim.truthfulness` reject out-of-enum values.
* Trait scores never touch the model at all — `derive_traits` seeds `random.Random` from `SHA256(seed)`.

## Candidate session agent

The same split, restated for the live conversation. Casting decides *who* the
persona is; the session only decides *what they say next*.

| Owned by code | Owned by the model |
|---|---|
| The system instruction — the contract's `system_prompt`, appended to but never edited | The words of the reply |
| The text-mode preamble and the sentence-length rule, interpolated from `turn_policy` | |
| Turn order, and the `manager`→`user` / `candidate`→`assistant` mapping | |
| Turn 0 — the persona's `opening_line`, written at session creation | |
| Every timestamp and turn index, stamped by the repository | |

`build_session_system_prompt` **appends**; it never rewrites what
`engine_contract.py` compiled. That is the property that lets the Go voice engine
and the Python text session run the same persona — both inject the same
`system_prompt` verbatim, and the only difference is the modality preamble.

The session call runs at temperature **0.8**. Nothing reproducible depends on
it: the transcript is stored, so re-reading a session is exact even though
re-running one would not be.

## Voice sessions

The same discipline again, and one new reproducibility claim.

| Owned by code | Owned by the model |
|---|---|
| The instructions — contract prompt verbatim, plus the spoken-mode preamble | Everything said aloud |
| **The opening line** — appended as a "say this first, close to verbatim" instruction | |
| **The voice**, hashed from `candidate_id` so a persona always sounds the same, over the roster subset matching how the persona presents | `presented_gender` — how the name it just authored reads, on personas with no code-owned `human_traits` |
| Speaking rate and turn-detection eagerness (OpenAI) / VAD silence window (Gemini), both from `voice_directives.pace` | |
| The transcription vocabulary hint, composed in code from the contract's skills | |
| That the human can always interrupt, and is always transcribed | |

`pick_voice` makes voice a persona property rather than a setting: two managers
practising against "Ravi Sharma" hear the same person, which is the same
comparability argument as `seed_fingerprint`. The cost is that the provider's
voice **ordering** becomes contract — reordering it reassigns every persona.
On the Gemini path the voice is not even re-derived: `tts_voice_id`, computed
once at cast time and stored on the contract, is what the session speaks in, so
it matches the pre-synthesized stall clips the Go engine plays. The roster
itself has exactly one home — `llm.gemini_live.GEMINI_LIVE_VOICES`, re-exported
as `engine_contract.GEMINI_TTS_VOICES` — because two copies of an
order-sensitive tuple is precisely the drift `tts_voice_id` cannot survive.

**The voice matches how the persona presents (contract v1.5, 2026-09-01).**
`pick_voice` hashes over whatever roster it is handed, and it used to be handed
all thirty voices — so a persona whose `human_traits.gender_presentation` said
`woman` had roughly an even chance of speaking in a man's voice. That is the
same casting-time incoherence as the persona cast under a man's name that the
realism note fixed: the interviewer hears a contradiction the persona document
never contained. `engine_contract.voices_for_presentation` now narrows the
offered roster first — `woman` → `llm.gemini_live.GEMINI_FEMALE_VOICES`, `man`
→ `GEMINI_MALE_VOICES`, `non_binary`/`unspecified`/absent → the roster
unchanged, because there is no vendor-neutral subset and inventing one would be
this repo deciding what non-binary sounds like.

Three properties hold the split together. The classification is a **vendor
fact** (Google's Gemini-TTS voice table), lives in exactly one place, and
partitions the roster — a test asserts union and disjointness, so a voice
appended to the roster without being classified fails. The filter **preserves
roster order**, because `pick_voice` is a modulus and the subset's order is
contract too. And `pick_voice` itself is **signature-stable**: the fallback in
`candidate_agent/voice.py` for pre-`tts_voice_id` contracts has no traits in
scope and still resolves against the full roster.

**Who declares the presentation when there are no traits (contract v1.6,
2026-09-01).** v1.5 only engaged when `human_traits` was present — and the
*default* cast path has none. `enroll_candidates` casts the fixed catalog
archetypes as `(key, None, None)`, and the lazy session-start cast passes no
traits either, so the overwhelming majority of personas still hashed over all
thirty voices. It reached production as a persona named **Tanvi** speaking with
a man's voice.

Code cannot close this gap alone: a name is not a gender lookup table, and
writing one would be this repo guessing at the identity the model authored. So
the split moves the boundary by exactly one field. The casting model declares
`presented_gender` — `woman | man | neutral`, *describing its own output*, in
`CANDIDATE_DRAFT_JSON_SCHEMA` and required — and code owns everything after
that: `normalize_presented_gender` validates it (anything outside the three
values becomes `""`, never an exception — losing a whole cast over a voice hint
is the worse failure), `voices_for_presentation` maps it, and `pick_voice`
still picks. The model does not choose a voice; it answers one question about
the name it wrote.

**Precedence is code over model.** `human_traits.gender_presentation` is
composed from fixed presets and never seen by the model, so it wins outright
where it exists; `presented_gender` only decides for personas that have no
trait layer. Both `neutral` and `non_binary`/`unspecified` take the same
full-roster branch.

The declared value is **stored** on `VirtualCandidate` and included in
`fingerprint`, so a persona can explain the voice it speaks in and an edited
one no longer matches. `PERSONA_VERSION` v1.2 → **v1.3**: the stored document
gained a field and the casting prompt changed, which is the same pair of
reasons v1.1 and v1.2 were bumped.

**Already-cast personas are untouched.** `tts_voice_id` is computed once and
stored; it is never recomputed at session time, so an existing persona keeps
the voice its managers already know it by. Only new casts are gender-matched —
which is why this is a bump of `ENGINE_CONTRACT_VERSION` (v1.4 → **v1.5**) even
though not one byte of the compiled prompt changed. The rule below is *bump the
constant that covers what moved*, and what moved is the compiled contract:
identical inputs now compile a different `tts_voice_id`. Neither fingerprint
covers that field, so the contract version is the only thing that records it.
The Go engine pins by major version, so v1.x needs no engine change.

**The opening line is now delivered.** It was authored at cast time and stored,
and until 2026-09-01 the voice path simply never mentioned it — the model
improvised a greeting, so every spoken interview opened the same generic way
regardless of persona. `build_voice_system_prompt` now appends a `THE FIRST
THING YOU SAY` block carrying it, for both providers, and each browser path
sends one nudge so the vendor generates turn 0. The nudge itself is never
stored; what reaches the transcript is what the persona says.

Per-provider turn detection is the same decision expressed twice, because the
vendors expose different knobs: OpenAI takes a semantic `eagerness`
(low/medium/high), Gemini takes a silence timer (800/650/500 ms for
slow/measured/fast). Both are read from `voice_directives.pace`, and neither is
a client setting.

**Where the split is weaker than elsewhere, said plainly.** In voice mode the
knowledge ceiling exists only as prompt text. There is no post-hoc clamp (as in
casting) and no deterministic pre-gate (as the Go engine's Thinker will have), so
a persona can be argued above its ceiling more easily than in text. That is a
known Speaker-only limitation, not an oversight — see
[Realtime voice](/concepts/contracts/realtime-voice.md).

## Expectation agent

Computed before the call and **overwritten after** it in `agent.generate`:

* `interview_type` — from `(experience_level, company_type)`.
* `evaluation_criteria` — the six fixed criteria and weights, verbatim.
* `red_flags` / `green_flags` — baselines first, model additions appended (deduped).
* `resume_probing.required` — from `(experience_level, has_resume)`.
* `interviewer_guidance` — from `(experience_level, company_type)`.
* `structure` — if the model's phase durations do not sum to the requested total, the whole structure is replaced with the template.

Temperature is **0.1**; the candidate agent runs at **0.35** because personas
need texture and everything reproducible is computed outside the model anyway.

## The two fingerprints

Both are SHA256 over a sorted-key JSON payload, and they answer different
questions:

| | `seed_fingerprint` | `fingerprint` |
|---|---|---|
| Covers | seed, archetype, catalog/persona versions, traits, verdict | all of the above **plus** name, background, knowledge levels, stances, system prompt |
| Stable across a re-cast? | **Yes** | No |
| Answers | "is this the same person?" — the reproducibility claim | "has this stored persona changed underneath my training set?" — the integrity claim |

`candidate_id` is `vc-<sha256(seed)[:12]>`, so the same `(interview, archetype)`
always yields the same id — which is what makes the storage upsert idempotent.

## When you change something here

Bump the version constant that covers it — `CATALOG_VERSION`,
`PERSONA_VERSION`, `ENGINE_CONTRACT_VERSION`, or `expectation_version` — because
both fingerprints include the version fields, and the Go engine pins the
contract version. Changing the compiled prompt text without bumping
`ENGINE_CONTRACT_VERSION` silently invalidates every stored persona's byte
stability, which `tests/test_candidate_rubric.py::test_system_prompt_is_byte_stable`
exists to catch.

The prompt text is the common case, not the whole rule. `ENGINE_CONTRACT_VERSION`
covers **the compiled contract**, so *any* change that makes identical inputs
compile a different contract needs the bump — including a field no fingerprint
covers, which is precisely the case that has nothing else to record it. v1.5
(the gender-matched voice) is the worked example: same prompt bytes, different
`tts_voice_id`.

## Operator input is code-owned too (2026-08-22)

Two configuration fields let a human put words into a persona's prompt, which
makes them the newest place the split could leak.

**`language`** — the *choice* is the operator's, from a closed list; the
*wording* is `LANGUAGE_DIRECTIVES` in `candidate_agent/engine_contract.py`. The
model never picks a language and never authors the instruction that describes
one.

**`candidate_notes`** — free text, and the only unstructured operator input that
reaches casting. It is rendered beneath an explicit subordination clause, and
every structural guarantee is still enforced in code afterwards: the knowledge
clamp, the trait bounds, the scorecard weights, `UNIVERSAL_FORBIDDEN`. A note
can add that the candidate worked at a competitor down the road. It cannot make
them cleverer than their band, change their archetype, or unlock a forbidden
behaviour — `test_operator_notes_cannot_override_the_archetype` asserts both the
prompt framing and the clamp.

**`clarity_facts`** — the *keys* are fixed in `evaluation_agent.schema`; only the
*statements* are drafted, and a drafted key that is not on the list is discarded.
The checklist a manager is measured against is never something a model chose.

## The report judge (2026-08-27)

The newest place the split could leak, and the first one where a model authors
text a manager reads *about themselves*. `report_engine/judge.py` makes one call;
`report_engine/validate.py` decides what survives it.

| Owned by code | Owned by the model |
|---|---|
| Every number: signal values, sub-scores, criterion scores, the readiness index, the band | Nothing numeric — prose containing a digit outside a quotation is **rejected**, not trimmed |
| **Which** signals get written about — strengths are the highest sub-scores with valid evidence, gaps the lowest (§7) | The **sentences** about them: headline and detail |
| Which criteria exist, their weights, and the bullet count | The narrative and the bullets under each criterion |
| The evidence anchor — turn index, timestamp, speaker — rebuilt from the transcript | Which moment to quote, subject to the span matching verbatim |
| Whether a `must_discover` verdict counts, and what it does to the score | The verdict itself: `surfaced` plus a span |
| The next practice persona, unchanged and fully deterministic | |

**A vetoed claim never blanks a section.** `report_engine/narrate.py` composes
every one of those sentences from the measurements first, and the judge overlays
what passes. That is why the offline report is a complete report rather than a
table with the headings missing, and why `--no-judge` is still the regression
harness: with no model, `to_json` and `to_html` are byte-identical across runs.

**Numbers are recomputed, never patched.** A surviving `must_discover` verdict
becomes a `discovery_surfaced` signal and the whole report is rebuilt through
`build_report(bundle, extra_signals=[...])`. Nothing downstream — the criterion
score, the readiness index, which findings were selected — is edited in place,
because a patched score is one code did not derive.

**Three vetoes, and one of them is deliberately not a fourth.** A span must
appear verbatim; a `surfaced: true` must be the *candidate* speaking after a
manager question; prose must state no number. The spec also asks for "a manager
question act **in the same topic**" — topics are clustered from the manager's own
questions, so the nearest preceding act is in the evidence's topic by
construction, and asserting it would be a test that cannot fail. It is written
down as not-a-check rather than shipped as an inert one.

**A rejected verdict degrades to `unmeasurable`, never to `False`.** The judge
failing to evidence something is not evidence that the manager missed it, and
scoring it as a miss would penalise them for the model's silence.

`source` on a signal now has three values, and the report prints which: `measured`
(counted by code), `assessed` (heard in the recording), `judged` (read out of the
transcript by the judge). Temperature **0.1**.

## The job spec reaches the persona's prompt (2026-09-01)

Until contract **v1.4**, no job-spec field reached `_compile_system_prompt` at
all. The persona knew who it was and what it knew; it never knew what job it had
walked in for. The determinism table above still held line by line — and the
system still produced interchangeable candidates for a fiber technician and a
retail sales role, because the *only* thing distinguishing the two prompts was a
background paragraph the model happened to write differently.

The fix keeps the split. `job_title`, `experience_level`, `company_type`,
`job_location_type` and `location` are stored interview fields, interpolated by
code into the THE ROLE YOU ARE INTERVIEWING FOR section
(`engine_contract._role_section`). The JD is operator free text of unbounded
length, so it goes through **`jd_precis(jd, limit=400)` — deterministic, code
owned, no model call**: whitespace normalisation, a cut at the last sentence end
inside the limit, a hard cut if there is none. Asking a model to summarise the JD
here would have been the leak: the same interview would compile different prompt
bytes on every cast, and `ENGINE_CONTRACT_VERSION` exists precisely to pin those
bytes.

The casting prompt gained the other half of the spec — `location`, `department`,
`manager_level` and the interview's `clarity_facts` — for the reason stated
above: the casting model writes `opening_line`, `sample_phrases` and `background`
and they are *stored*, so anything it cannot see is permanently missing from the
artifact that runs. Empty scalars render `(not specified)` and an empty checklist
renders `(none)`, both in code; a `ClarityFact` with an empty statement is not on
this interview's checklist and is not rendered at all.

Consequence for [the two fingerprints](#the-two-fingerprints): `fingerprint`
covers `system_prompt`, so it moves with the job text — as it should, since the
stored persona did change. `seed_fingerprint` does not include the job spec and
is unchanged, so "same seed, same person" still holds for the same interview.

Section-conditional rendering is the back-compat rule, same as the realism
layer: an empty `job_title` renders nothing, so hand-built contracts and the
handover sample compile byte-identically to v1.3.
