---
type: Map
title: Repo Map
description: Path → concept routing table; read this to find the right page without grepping the tree.
resource: /
tags: [navigation, index]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5
    at: "2026-08-23T18:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
---
# Repo Map

| Path | Concept |
|---|---|
| `llm/base.py` | [StructuredModel](/concepts/contracts/structured-model.md) and [ChatModel](/concepts/contracts/chat-model.md) — the two model ports |
| `llm/factory.py` | [llm/factory.py](/concepts/modules/llm-factory.md) — provider/model resolution |
| `llm/gemini.py`, `llm/openai_model.py` | [LLM port subsystem](/concepts/subsystems/llm-port.md) |
| `llm/openai_realtime.py` | [Realtime voice](/concepts/contracts/realtime-voice.md) — the only realtime provider |
| `expectation_agent/agent.py` | [expectation_agent/agent.py](/concepts/modules/expectation-agent-agent.md) |
| `expectation_agent/rubric.py` | [expectation_agent/rubric.py](/concepts/modules/expectation-agent-rubric.md) — the deterministic tables |
| `expectation_agent/schema.py` | [InterviewExpectation contract](/concepts/contracts/interview-expectation.md) |
| `expectation_agent/prompts.py` | [Expectation agent subsystem](/concepts/subsystems/expectation-agent.md) |
| `candidate_agent/agent.py` | [candidate_agent/agent.py](/concepts/modules/candidate-agent-agent.md) |
| `candidate_agent/archetypes.py` | [candidate_agent/archetypes.py](/concepts/modules/candidate-agent-archetypes.md) — the catalog |
| `candidate_agent/trait_dimensions.py` | [Candidate agent subsystem § composing personas](/concepts/subsystems/candidate-agent.md) — compose an archetype/human-trait profile from presets instead of hand-writing one |
| `candidate_agent/engine_contract.py` | [candidate_agent/engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) |
| `candidate_agent/schema.py` | [VirtualCandidate contract](/concepts/contracts/virtual-candidate.md), [EngineContract](/concepts/contracts/engine-contract.md) |
| `candidate_agent/session.py` | [candidate_agent/session.py](/concepts/modules/candidate-agent-session.md) — one persona turn in a live interview |
| `candidate_agent/voice.py` | [candidate_agent/voice.py](/concepts/modules/candidate-agent-voice.md) — the persona's spoken session config |
| `candidate_agent/prompts.py` | [Candidate agent subsystem](/concepts/subsystems/candidate-agent.md) — casting prompts and `build_session_system_prompt()` |
| `control_plane/api.py` | [control_plane/api.py](/concepts/modules/control-plane-api.md), [REST API](/concepts/contracts/rest-api.md) |
| `control_plane/ports.py` | [Storage ports](/concepts/contracts/storage-ports.md) |
| `control_plane/repository.py` | [control_plane/repository.py](/concepts/modules/control-plane-repository.md) |
| `control_plane/database.py` | [Database schema](/concepts/contracts/database-schema.md), [Session recording](/concepts/contracts/session-recording.md) — `session_recordings`, `RECORDINGS_DIR` |
| `evaluation_agent/rubric.py` | [evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) — the fixed manager rubric |
| `evaluation_agent/role_facts.py`, `prompts.py`, `schema.py` | [evaluation_agent/role_facts.py](/concepts/modules/evaluation-agent-role-facts.md) — the fixed role-fact checklist and its drafting agent |
| `report_engine/score.py`, `transfer.py` | [Report engine](/concepts/subsystems/report-engine.md) — aggregation and the raw-to-score transfer functions |
| `report_engine/acts.py`, `segment.py` | [Report engine](/concepts/subsystems/report-engine.md) — the question act and the four segments |
| `report_engine/signals/` | [Report engine](/concepts/subsystems/report-engine.md) — one module per rubric criterion |
| `report_engine/packs/` | [Report engine](/concepts/subsystems/report-engine.md) — dated jurisdiction and competency packs |
| `report_engine/schema.py` | [Report engine](/concepts/subsystems/report-engine.md) — `SessionBundle` in, `AssessmentReport` out |
| `scripts/make_bundle.py` | [Report engine](/concepts/subsystems/report-engine.md) — builds a bundle from the DB, a turn list, or the demo fixture |
| `control_plane/schemas.py` | [Interview record](/concepts/contracts/interview-record.md), [Session transcript](/concepts/contracts/session-transcript.md), [Session recording](/concepts/contracts/session-recording.md) — `RecordingMeta` |
| `control_plane/persona.py` | [Control plane subsystem § legacy persona](/concepts/subsystems/control-plane.md) |
| `control_plane/main.py` | [Dev setup](/concepts/runbooks/dev-setup.md) |
| `ui/src/SessionView.jsx`, `ui/src/VoiceSessionView.jsx` | [Test UI § conducting an interview](/concepts/subsystems/ui.md), [Run an interview](/concepts/runbooks/run-an-interview.md), [Session recording](/concepts/contracts/session-recording.md) — the browser-side capture and upload |
| `ui/src/PersonaPicker.jsx` | [Test UI § the persona picker](/concepts/subsystems/ui.md), [archetypes.py](/concepts/modules/candidate-agent-archetypes.md) |
| `ui/src/{Shell,InterviewList,Wizard,InterviewDetail}.jsx` | [Test UI](/concepts/subsystems/ui.md) |
| `ui/src/index.css`, `interview_training_wizard (1).html` | [Test UI](/concepts/subsystems/ui.md) — the mockup is the design source of truth |
| `ui/` | [Test UI](/concepts/subsystems/ui.md) |
| `tests/` | [Test suite](/concepts/subsystems/test-suite.md), [Architecture](/concepts/architecture.md) |
| `scripts/check.sh` | [Checks](/concepts/runbooks/checks.md) |
| `scripts/export_schemas.py` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `owner_handover/` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `docs/BRD_AI_Interview_Platform_v2.md` | [BRD](/references/brd.md) — **superseded** by BRD v3 |
| `docs/BRD_Interviewer_Upskilling_v3.{html,pdf}` | Current requirements. The manager is assessed, not the candidate; the job card does not drive the rubric; no criterion has a hard limit |
| `docs/PIVOT_PLAN_MANAGER_ASSESSMENT.md` | The BRD v3 pivot — 5 phases, 34 ToDos; retires `expectation_agent/`, session is text-first. **Phase 1 (tasks 1–6) is done**; Phases 2–5 open |
| `docs/GO_ENGINE_CONTRACT.md` | [EngineContract](/concepts/contracts/engine-contract.md) |
| `docs/ENGINE_IMPLEMENTATION_PLAN.md` | [Live-session engine](/concepts/subsystems/engine.md) |
| `docs/ENGINE_ONE_BRAIN_TWO_PARTS.html` | [Live-session engine](/concepts/subsystems/engine.md) — diagrams of the Speaker/Thinker sync; open in a browser |
| `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — Go module, separate build and CI gate |
| `engine/internal/session/` | [Live-session engine](/concepts/subsystems/engine.md) — the turn loop and the actor; start at its state table |
| `engine/internal/audio/` | [Live-session engine](/concepts/subsystems/engine.md) — sample domain: resampler, onset detection, jitter buffer, send ring |
| `engine/internal/transport/` | [Live-session engine](/concepts/subsystems/engine.md) — `wsfallback` carries live traffic today; `webrtc` is a placeholder |
| `engine/internal/vendors/gemini/` | [Live-session engine](/concepts/subsystems/engine.md) — the Speaker, over the Gemini **Live** API. Read its live-verified facts before changing it |
| `engine/internal/vendors/` (others) | [Live-session engine](/concepts/subsystems/engine.md) — reasoning adapters and TTS; only `cmd/engined` may import any of them |
| `engine/internal/stall/` | [Live-session engine](/concepts/subsystems/engine.md) — pre-synthesized opening line and stall clips |
| `engine/internal/ports/record.go`, `finalize.go` | [Session recording § the forward seam](/concepts/contracts/session-recording.md) — the `Recorder`/`Finalizer` ports the browser-side recording is designed to hand off to; `engine/internal/record/` and `engine/internal/store/s3/` are still `doc.go` stubs, nothing implements them yet |
| `.golangci.yml` | [Live-session engine](/concepts/subsystems/engine.md), [Checks](/concepts/runbooks/checks.md) |
| `pyproject.toml`, `.env.example` | [Conventions](/concepts/conventions.md), [Dev setup](/concepts/runbooks/dev-setup.md) |
| `control_plane.db` | [Database schema](/concepts/contracts/database-schema.md) — gitignored |

## "I want to change X" → read Y

| Change | Read first |
|---|---|
| Add a candidate archetype | [archetypes.py](/concepts/modules/candidate-agent-archetypes.md) — and note the OCP test proves no agent edit is needed |
| Compose a persona from presets instead of hand-writing an archetype | [trait_dimensions.py](/concepts/subsystems/candidate-agent.md) — `compose_archetype` for the skill/verdict axis, `compose_human_traits` for the realism/compliance taxonomy, `compose_custom_persona` for both at once |
| Add an LLM provider | [llm/factory.py](/concepts/modules/llm-factory.md), [StructuredModel](/concepts/contracts/structured-model.md) |
| Change what the persona prompt says | [engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) — **bump `ENGINE_CONTRACT_VERSION`** |
| Change phase durations, criteria, or flags | [rubric.py](/concepts/modules/expectation-agent-rubric.md) |
| Change what the model is allowed to author | [Determinism split](/concepts/determinism.md) first, then the agent's `_build_*` helpers |
| Anything touching what is scored, or who is scored | `docs/BRD_Interviewer_Upskilling_v3.html` first — the rubric is fixed configuration and no criterion may gate the result |
| Add or change an endpoint | [REST API](/concepts/contracts/rest-api.md), [api.py](/concepts/modules/control-plane-api.md) — pick the narrowest port |
| Anything about how a persona behaves *in conversation* | [session.py](/concepts/modules/candidate-agent-session.md) and [Determinism § session agent](/concepts/determinism.md) — the contract prompt is appended to, never edited |
| Anything about how a persona **sounds**, or the voice call | [voice.py](/concepts/modules/candidate-agent-voice.md), [Realtime voice](/concepts/contracts/realtime-voice.md) — and note that voice ordering is contract, not cosmetics |
| The transcript shape, turn timing, or session status | [Session transcript](/concepts/contracts/session-transcript.md) — the evaluation layer and the Go engine both depend on it |
| Swap SQLite for Postgres | [Storage ports](/concepts/contracts/storage-ports.md), [Database schema](/concepts/contracts/database-schema.md) |
| Anything inside `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — then `go test ./internal/arch`, which enforces the layering |
| A vendor's observed behaviour (Live API, TTS) | [Live-session engine](/concepts/subsystems/engine.md) — the live-verified facts section. Several of them removed planned work; do not re-derive them from docs |
| Change any Pydantic model in the public surface | [Owner handover](/concepts/subsystems/owner-handover.md) — regenerate, or CI fails |
| Anything about the recorded audio artifact, its chunk protocol, or consent/retention | [Session recording](/concepts/contracts/session-recording.md) first — several of its decisions (where bytes land, no auth on the GET, indefinite retention) are meant to be vetoed, not silently changed |
