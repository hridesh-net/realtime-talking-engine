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
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /candidate_agent/agent.py
  - resource: /candidate_agent/archetypes.py
  - resource: /candidate_agent/engine_contract.py
  - resource: /candidate_agent/prompts.py
  - resource: /candidate_agent/schema.py
---
# Candidate agent

`candidate_agent/` — the largest and most interesting package. Casts one persona
per `(interview, archetype)` for a **human interviewer** to practise against.
Imports only `llm`.

| Module | Role |
|---|---|
| `archetypes.py` (987 ln) | [The fixed catalog](/concepts/modules/candidate-agent-archetypes.md) — 11 archetypes, registered with validation |
| `agent.py` (373 ln) | [`VirtualCandidateAgent.generate(...)`](/concepts/modules/candidate-agent-agent.md) — seed, call, re-impose, fingerprint |
| `engine_contract.py` (190 ln) | [Compiles the runtime slice](/concepts/modules/candidate-agent-engine-contract.md) and the system prompt |
| `schema.py` (254 ln) | [`VirtualCandidate`, `EngineContract`, the draft schema](/concepts/contracts/virtual-candidate.md) |
| `prompts.py` (200 ln) | Casting-director persona, 11 hard rules, user prompt builder, `expectation_note()` |

## The idea

Each archetype exists to test **one specific interviewer skill**. A persona that
does not challenge the interviewer in a distinct way does not belong in the
catalog.

| Archetype | Verdict | Tests whether the interviewer… |
|---|---|---|
| `strong_hire` *(default)* | select | confirms strength with evidence, still finds the gap |
| `clear_reject` *(default)* | reject | reaches a defensible no-hire with quotable evidence |
| `lazy` | reject | separates low effort from low ability |
| `smart_but_lazy` | borderline | probes past a shallow first answer |
| `disengaged` | reject | names disinterest instead of scoring it as weak skill |
| `eager_underqualified` | borderline | discounts enthusiasm when scoring depth |
| `confident_bluffer` | reject | verifies claims instead of rewarding fluency |
| `resume_inflater` | reject | asks ownership questions, converts "we" to "I" |
| `nervous_but_capable` | select | separates presentation from ability |
| `rambler` | borderline | controls time and still covers the rubric |
| `specialist_mismatch` | borderline | assesses transferable depth, not keywords |

Eleven archetypes: **2 select, 5 reject, 4 borderline**. The catalog is
deliberately weighted toward rejects and borderlines — those are the calls
interviewers get wrong.

## The casting-director persona

*"You write the person a real interviewer would actually meet on a Tuesday
afternoon: a concrete history, a concrete ceiling, concrete things they get
wrong. You never write a caricature."*

Eleven hard rules. The ones that shape output most: the archetype and verdict are
fixed and must not be softened; every required skill must appear spelled exactly
as given; levels must stay inside the given band; `wrong_beliefs` must be a real
mistaken belief an engineer holds, not "misunderstands caching";
`breaking_point` must name a depth an interviewer could walk into; resume-claim
truthfulness must match the honesty trait (high honesty → all `true`, low
honesty → at least two `exaggerated`/`false`); names must be realistic and
culturally varied.

## The output

A [`VirtualCandidate`](/concepts/contracts/virtual-candidate.md) containing both
halves: the persona document (for humans and storage) and the compiled
[`EngineContract`](/concepts/contracts/engine-contract.md) (for the Go runtime),
plus the scorecard that grades the interviewer afterwards.

## Testing

Offline: `tests/test_candidate_rubric.py` (279 ln) is the real safety net —
determinism, clamping, scorecard integrity, prompt byte-stability.
Live: `tests/test_candidate_agent.py`, six archetypes plus a determinism check.
