---
type: Subsystem
title: Candidate agent
description: Casts virtual candidates — fixed archetypes made concrete against one job spec.
resource: /candidate_agent
tags: [candidate, persona, archetype, agent, training]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /candidate_agent/agent.py
  - resource: /candidate_agent/archetypes.py
  - resource: /candidate_agent/engine_contract.py
  - resource: /candidate_agent/prompts.py
  - resource: /candidate_agent/session.py
  - resource: /candidate_agent/voice.py
  - resource: /candidate_agent/schema.py
---
# Candidate agent

`candidate_agent/` — the largest and most interesting package. Casts one persona
per `(interview, archetype)` for a **human interviewer** to practise against,
and then plays that persona through a live typed interview. Imports only `llm`.

| Module | Role |
|---|---|
| `archetypes.py` (987 ln) | [The fixed catalog](/concepts/modules/candidate-agent-archetypes.md) — 11 archetypes, registered with validation |
| `agent.py` (373 ln) | [`VirtualCandidateAgent.generate(...)`](/concepts/modules/candidate-agent-agent.md) — seed, call, re-impose, fingerprint |
| `engine_contract.py` (190 ln) | [Compiles the runtime slice](/concepts/modules/candidate-agent-engine-contract.md) and the system prompt |
| `schema.py` (254 ln) | [`VirtualCandidate`, `EngineContract`, the draft schema](/concepts/contracts/virtual-candidate.md) |
| `session.py` (95 ln) | [`CandidateSessionAgent.reply(...)`](/concepts/modules/candidate-agent-session.md) — one persona turn, stateless |
| `voice.py` (105 ln) | [`build_realtime_session(...)`](/concepts/modules/candidate-agent-voice.md) — the persona's spoken session config |
| `prompts.py` (240 ln) | Casting-director persona, 11 hard rules, user prompt builder, `expectation_note()`, `build_session_system_prompt()` |
| `trait_dimensions.py` | Compose an archetype or a `HumanTraitProfile` from fixed presets instead of hand-writing one — see below |

## The idea

Each archetype exists to put **one manager competency** under pressure. A
persona that does not stress the manager in a distinct way does not belong in
the catalog. Catalog `v2.0` — v1 sorted personas by hiring outcome, which
stopped meaning anything when the assessed subject became the manager.

| Archetype | Stresses hardest | Tests whether the manager… |
|---|---|---|
| `cooperative_trap` *(default)* | Unconscious Bias | declines a volunteered protected detail and routes the accommodation ask to policy |
| `evasive` *(default)* | Structured Interviewing | asks again after a platitude, and lets a silence do the work |
| `nervous_fresher` | Communication, Candidate Experience | warms the room before assessing, and scores content not delivery |
| `inflated_resume` | Structured Interviewing | converts "we" into "I" and probes a claim to its breaking point |
| `comp_first` | Hiring with Clarity | sells the role and states the band honestly without caving |
| `defensive` | Communication & Tone | holds composure through provocation and re-plans around a hard stop |
| `rambler` | Structured Interviewing | redirects without rudeness and still covers what was planned |
| `frontline_network_candidate` | Unconscious Bias | explains shifts/conditions beyond the JD, probes with open follow-ups, stays bias-free about a volunteered career gap |
| `frontline_sales_candidate` | Unconscious Bias | explains targets/incentives concretely, verifies claims with numbers, stays bias-free about age/re-entry |

Nine archetypes — though the verdict is now only persona metadata. What the
catalog is balanced on instead is rubric coverage: a test asserts every one of
the five criteria is stressed at level ≥3 by at least one persona, so no
competency is untrainable. The two `frontline_*` entries are Airtel/telecom
profiles, predating the v2.0 rubric reframe — their `interviewer_challenge`
text already targeted clarity/structure/bias/communication directly, so they
needed only `session_beats`/`stresses` added to satisfy `_register`, not a
rewrite.

The two defaults are no longer "one hire, one no-hire". They are the bias trap
(the one manager failure that cannot be walked back) and the evasive candidate
(the one that separates structured interviewing from conversation).

**Nothing here scores anything.** `stresses` is advisory until the evaluation
layer lands, and by explicit product decision no criterion — bias included —
is a critical-fail gate.

## The casting-director persona

*"You write the person a real interviewer would actually meet on a Tuesday
afternoon: a concrete history, a concrete ceiling, concrete things they get
wrong. You never write a caricature."*

Eleven hard rules, plus the archetype's `session_beats` rendered as a fixed
block the cast persona must be written to perform. The ones that shape output
most: the archetype and verdict are fixed and must not be softened; every required skill must appear spelled exactly
as given; levels must stay inside the given band; `wrong_beliefs` must be a real
mistaken belief an engineer holds, not "misunderstands caching";
`breaking_point` must name a depth an interviewer could walk into; resume-claim
truthfulness must match the honesty trait (high honesty → all `true`, low
honesty → at least two `exaggerated`/`false`); names must be realistic and
culturally varied.

## Casting, then conversation

The package has two jobs and they run at different times. `agent.py` casts a
persona **once** per `(interview, archetype)` — a `StructuredModel` call whose
output is validated, clamped, and fingerprinted. `session.py` then replays that
persona's compiled contract on **every turn** of a live interview via a
[`ChatModel`](/concepts/contracts/chat-model.md), adding nothing but a text-mode
preamble.

`voice.py` is the third: it compiles the same contract into a realtime voice
session — instructions, voice, speaking rate, turn detection — which a browser
then runs against the vendor directly ([Realtime voice](/concepts/contracts/realtime-voice.md)).

None of the three share a model instance or a temperature (0.35 casting, 0.8 text
session, vendor-owned for voice), and neither `session.py` nor `voice.py` imports
`agent.py`. All three meet at the compiled
[`EngineContract`](/concepts/contracts/engine-contract.md) — which is also exactly
what the Go voice engine will consume. That one seam is why text, browser voice,
and the future engine all run the same persona.

## The output

A [`VirtualCandidate`](/concepts/contracts/virtual-candidate.md) containing both
halves: the persona document (for humans and storage) and the compiled
[`EngineContract`](/concepts/contracts/engine-contract.md) (for the Go runtime),
plus the scorecard that grades the interviewer afterwards.

## Composing personas from presets — `trait_dimensions.py`

Two composers, both additive to the fixed catalog above — neither replaces it,
and neither lets the model choose a value:

* **`compose_archetype(...)`** builds an `Archetype` from five generic presets
  (`COMPETENCE`, `CONSCIENTIOUSNESS`, `COMMUNICATION`, `EMOTIONAL_STANCE`,
  `HONESTY`, optionally `BIAS_TRAP`) instead of writing the dataclass by hand,
  deriving `session_beats` and `stresses` from those same inputs so it satisfies
  exactly what `archetypes.validate_archetype` requires — v2.0's
  non-empty-beats and valid-criteria rules included. Each preset declares the
  rubric pressure it contributes; the composed `stresses` are the clamped sum,
  so they vary with the composition rather than being a constant.

  **Composed archetypes are validated, never registered.** A persona composed
  for one interview is not a catalog entry: adding it to the process-wide
  `ARCHETYPES` dict would leak it into every other interview's picker, grow that
  dict without bound, and strand the persona on the next restart, since the dict
  is memory and the candidate row is not. `compose_custom_persona(...)` returns
  the archetype and the caller passes it to `agent.generate(archetype=...)`.
* **`compose_human_traits(...)`** builds a `HumanTraitProfile` — the realism
  taxonomy layer (affect, verbal style, language & literacy, comprehension,
  integrity red flags, motivation, negotiation stance, compliance traps,
  environment, profile). Orthogonal to the archetype and to `stresses`/
  `session_beats`: this decides how realistically a persona comes across,
  including compliance-training traps like volunteering protected information.
  Every value in it renders into the prompt through a **directive table** in
  `engine_contract` (`AFFECT_DIRECTIVES`, `VERBAL_STYLE_DIRECTIVES`, …), never
  as the raw vocabulary token: `affect="jargon_flooder"` is an index into
  behaviour, not English, and emitting it verbatim would hand the persona's
  design to the model. See
  [VirtualCandidate § human_traits](/concepts/contracts/virtual-candidate.md)
  and [EngineContract § the realism layer](/concepts/contracts/engine-contract.md).

`dimension_catalog()` serializes every preset table and closed vocabulary for
a UI to render pickers from — it backs `GET /api/v1/trait-dimensions`
([REST API](/concepts/contracts/rest-api.md)). The control plane exposes both
composers as `custom_personas` on the enrollment endpoint, through the single
`compose_custom_persona(...)` entry point: a spec composes into a
content-addressed archetype key (`dyn-<hash of the spec>`, idempotent on
resubmission), an unregistered `Archetype` and a `HumanTraitProfile`, then casts
through the normal `agent.generate(...)` path. Because the archetype is never
registered, `POST /sessions` resolves an enrolled persona from the **database
first** and only falls back to the catalog. The UI's "Compose" tab
(`ui/src/PersonaComposer.jsx`, inside `InterviewDetail.jsx`) is the human-facing
side of this.

## Testing

Offline: `tests/test_candidate_rubric.py` (279 ln) is the real safety net —
determinism, clamping, scorecard integrity, prompt byte-stability.
`tests/test_session.py` covers the session agent against a fake `ChatModel`;
`tests/test_voice.py` covers voice compilation against a fake broker.
`tests/test_trait_dimensions.py` covers both composers (valid composition,
unknown-preset and out-of-vocabulary rejection, the v2.0 `session_beats`/
`stresses` requirement, the `protected_info_type`-required-when-volunteered
guard). `tests/test_control_plane_candidates_api.py` covers the
`custom_personas` enrollment path end-to-end (`TestClient` + fake model +
throwaway SQLite).
`tests/test_custom_persona_integration.py` goes one level deeper than either:
it drives the full `agent.generate()` pipeline for a composed persona against
an *adversarial* fake model that deliberately violates every re-imposition
rule (inflates a skill past its ceiling, drops a required one, invents an
extra one, uses out-of-enum stance/truthfulness, invents scorecard ids) —
proving a composed archetype holds the same guarantees a hand-written one
does, not a relaxed subset. Also covers all four bias traps, all three
compliance-trap types landing distinctly in the compiled prompt, taxonomy
values reaching the prompt verbatim, and a 25-seed trait-bounds sweep.
`tests/test_full_interview_pipeline_integration.py` drives the whole
manager-facing HTTP surface end to end — cast a persona (composed or
hand-written) -> read its `InterviewerScorecard` "report" -> run a multi-turn
practice session via `CandidateSessionAgent` -> end it -> re-read the
transcript and confirm the report is unchanged — across a matrix of five
compositions (every bias trap plus none, each paired with a distinct
competence/honesty/communication combination). Also covers the edge cases a
manager hits in practice: a persona never engaged still has a readable
report, ending a session with zero manager turns, an unknown candidate's
scorecard is 404, two personas run independent sessions in one interview
without leaking into each other's transcript or report, re-casting the same
spec reuses both the candidate and its report, a hand-written catalog
archetype follows the identical lifecycle, and the live transcript is
readable mid-session before `end` is ever called. Note: there is no
post-session judge/grader yet — the "report" a manager can pull today is the
pre-computed `InterviewerScorecard` answer key, generated at casting time, not
a score of what actually happened in the transcript; `JUDGE_MODEL` and the
Go `Judge` port (`engine/internal/ports/judge.go`) are reserved for that,
unbuilt in Python.
Live: `tests/test_candidate_agent.py`, six archetypes plus a determinism check.
