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
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
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
| `archetypes.py` (809 ln) | [The fixed catalog](/concepts/modules/candidate-agent-archetypes.md) — seven archetypes, registered with validation |
| `agent.py` (381 ln) | [`VirtualCandidateAgent.generate(...)`](/concepts/modules/candidate-agent-agent.md) — seed, call, re-impose, fingerprint |
| `engine_contract.py` (215 ln) | [Compiles the runtime slice](/concepts/modules/candidate-agent-engine-contract.md) and the system prompt |
| `schema.py` (254 ln) | [`VirtualCandidate`, `EngineContract`, the draft schema](/concepts/contracts/virtual-candidate.md) |
| `session.py` (95 ln) | [`CandidateSessionAgent.reply(...)`](/concepts/modules/candidate-agent-session.md) — one persona turn, stateless |
| `voice.py` (125 ln) | [`build_realtime_session(...)`](/concepts/modules/candidate-agent-voice.md) — the persona's spoken session config |
| `prompts.py` (345 ln) | Casting-director persona, 11 hard rules, user prompt builder, `expectation_note()`, `build_session_system_prompt()` |

## The idea

Each archetype exists to put **one manager competency** under pressure. A
persona that does not stress the manager in a distinct way does not belong in
the catalog. Catalog `v2.0` — v1 sorted personas by hiring outcome, which
stopped meaning anything when the assessed subject became the manager.

| Archetype | Stresses hardest | Tests whether the manager… |
|---|---|---|
| `cooperative_trap` *(default)* | Fair & Inclusive | declines a volunteered protected detail and routes the accommodation ask to policy |
| `evasive` *(default)* | Structured Interviewing | asks again after a platitude, and lets a silence do the work |
| `nervous_fresher` | Communication & Presence | warms the room before assessing, and scores content not delivery |
| `inflated_resume` | Structured Interviewing | converts "we" into "I" and probes a claim to its breaking point |
| `comp_first` | Hiring with Clarity | sells the role and states the band honestly without caving |
| `defensive` | Communication & Presence | holds composure through provocation and re-plans around a hard stop |
| `rambler` | Structured Interviewing | redirects without rudeness and still covers what was planned |

Seven archetypes: **2 select, 2 reject, 3 borderline** — though the verdict is
now only persona metadata. What the catalog is balanced on instead is rubric
coverage: a test asserts every one of the four criteria is stressed at level ≥3
by at least one persona, so no competency is untrainable. The criteria are the
training-wizard spec's four, owned by
[`evaluation_agent.rubric`](/concepts/modules/evaluation-agent-rubric.md) and
re-declared here — the two are pinned together by
`test_rubric_vocabulary_agrees_across_the_two_agents`.

The two defaults are no longer "one hire, one no-hire". They are the bias trap
(the one manager failure that cannot be walked back) and the evasive candidate
(the one that separates structured interviewing from conversation).

**Nothing here scores anything.** `stresses` is advisory — the rubric instrument
exists but nothing scores a session yet — and by explicit product decision no
criterion, fairness included, is a critical-fail gate.

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

## Testing

Offline: `tests/test_candidate_rubric.py` (401 ln) is the real safety net —
determinism, clamping, scorecard integrity, prompt byte-stability, and the
language/operator-notes guarantees.
`tests/test_session.py` covers the session agent against a fake `ChatModel`;
`tests/test_voice.py` covers voice compilation against a fake broker.
Live: `tests/test_candidate_agent.py`, six archetypes plus a determinism check.
