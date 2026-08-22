---
type: Subsystem
title: Test suite
description: Offline checks that enforce architecture and determinism, plus live scenario scripts that call the model.
resource: /tests
tags: [tests, pytest, architecture, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /tests/test_architecture.py
  - resource: /tests/test_candidate_rubric.py
  - resource: /tests/test_session.py
  - resource: /tests/test_voice.py
  - resource: /tests/test_candidate_agent.py
  - resource: /tests/test_expectation_agent.py
---
# Test suite

Two kinds of test, and the distinction matters: the offline ones defend rules,
the live ones check model behaviour and cost money.

## Offline — run always

### `tests/test_architecture.py` (350 ln)

SOLID and layering as failing tests (BRD NFR-003). AST-based, parametrized over
every module. Full breakdown in [Architecture](/concepts/architecture.md).

The standout is `test_ocp_new_provider_needs_no_agent_change` /
`test_ocp_new_archetype_needs_no_agent_change`: they *register* a new provider
and archetype at runtime and prove the system absorbs them, rather than asserting
that extension is theoretically possible.

### `tests/test_candidate_rubric.py` (401 ln)

The real safety net for the persona pipeline. Groups:

* **Catalog integrity** — scorecard weights sum to 1.0 per archetype; archetypes are well-formed; exactly two defaults, one of each verdict; the catalog covers the intended space; the payload is serializable.
* **Determinism** — traits land inside archetype bounds; the same seed reproduces the same person; different interviews produce different people; `smartness_ratio` points the same direction as the verdict.
* **Clamping and repair** — the model cannot exceed the knowledge band; missing and renamed skills are restored; adjacent strength survives only where allowed.
* **Scorecard** — catalog ids and weights survive; model wording is used only when ids match.
* **Language and operator notes** — every language reaches both the casting prompt and the compiled contract; a hostile `candidate_notes` stays subordinated in the prompt and the knowledge clamp holds regardless.
* **Engine contract** — self-consistency (`min ≤ target ≤ max`, ceilings present); the system prompt carries the behavioural contract; **the system prompt is byte-stable**.
* **Validation** — resume claims reject bad truthfulness values.

### `tests/test_session.py` (280 ln)

The live text session, entirely offline: a `FakeChatModel` records the exact
call, and the endpoints run under `TestClient` with `get_repo` and
`get_session_agent` overridden. Groups:

* **The agent** — the contract's `system_prompt` reaches the model unedited; the text-mode preamble and the turn-policy length rule are present; roles map and order is preserved; the scene-setting turn is prepended only when the transcript opens on the candidate; an empty transcript raises; the agent holds no state but its model.
* **Storage** — turn 0 is the opening line at `elapsed_ms = 0`; indexes and timestamps advance; re-ending a session does not move `ended_at`; appending to an unknown session raises.
* **Endpoints** — the full round trip (start → turn → end → fetch), 409 on a finished session, 404 on an unknown interview, 422 on an unknown archetype.

The persona fixture is **built in code**, not cast — the casting agent is not
exercised here, so nothing in this file can reach the network.

### `tests/test_voice.py` (270 ln)

The voice session, offline — the broker is faked, so no audio and no vendor call.
The point it defends: **everything this service decides about a voice session is
decided before the vendor is involved**, and is therefore testable here.

* **Compilation** — voice is stable per persona and spread across personas; the contract prompt reaches the instructions verbatim; pace drives speed and eagerness; `may_interrupt` overrides pace; an unknown pace falls back instead of raising.
* **Two invariants no persona may switch off** — the human can always interrupt, and their speech is always transcribed.
* **Storage** — a voice session does not pre-write turn 0; a text one still does.
* **Endpoints** — minting seals the persona and never leaks the prompt into the response; transcript records without generating; a bad speaker label is 422; a finished session refuses both mint and transcript; a deleted persona is 410 while the session survives; a vendor failure is 502; `voice-capability` answers rather than raising.

## Live — `scripts/check.sh --live`

Run as scripts, not through pytest:

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

The candidate suite asserts verdicts and traits come from the catalog, knowledge
stays under the ceiling, every required skill is covered, names are unique within
a training set, and the same seed reproduces the same person. The expectation
suite validates each generated document against the guardrails — including the
two (skill coverage, `min_duration_minutes` ceiling) that code does *not*
re-impose.

## Gaps

* **The interview, expectation, and enrollment routes are still untested.** `test_session.py` covers the session handlers and the session SQL; the skip-unless-regenerate branch, the 422 on unknown archetypes at enrollment, and the interview/expectation SQL remain uncovered. The pattern to copy is already in `test_session.py`.
* No live scenario exercises a session end to end against a real provider. The pivot plan's Phase 5 task 30 adds one scripted session per persona under `--live`.
* **Nothing automated exercises real audio.** The WebRTC handshake, the data-channel event names, and the vendor's session schema were verified by hand against the live API on 2026-08-22 (recorded in [Realtime voice](/concepts/contracts/realtime-voice.md)); a vendor rename would pass every test here and fail in the browser. The event-name mapping in `VoiceSessionView.jsx` is the fragile surface.
* Nothing checks that `EXPECTATION_JSON_SCHEMA` matches `InterviewExpectation` — two hand-maintained representations of one shape.
* `expectation_agent/agent.py` has no offline test of its overwrite logic, which is where its determinism guarantee actually lives.
* No JS tests for `ui/`.

## Guards added with the Phase 0 MVP (2026-08-22)

Three tests exist to stop a decision being reversed by accident rather than to
catch a bug:

* `test_operator_notes_cannot_override_the_archetype` — free operator text reaches the casting prompt, so this asserts both that the prompt subordinates it and that the knowledge clamp still holds afterwards.
* `test_rubric_vocabulary_agrees_across_the_two_agents` — `candidate_agent` re-declares the rubric criterion ids because siblings may not import each other. The control plane sits above both and is the only place they can be compared.
* `test_the_rubric_has_no_critical_fail_gate` — the design mockup specifies a gate on Fair & Inclusive that the standing product rule forbids. If a gate is ever wanted it must arrive as a deliberate edit to this test, not as a quiet field on a criterion.
