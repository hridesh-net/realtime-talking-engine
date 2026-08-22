---
type: Map
title: Repo Map
description: Path → concept routing table; read this to find the right page without grepping the tree.
resource: /
tags: [navigation, index]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
---
# Repo Map

| Path | Concept |
|---|---|
| `llm/base.py` | [StructuredModel contract](/concepts/contracts/structured-model.md) |
| `llm/factory.py` | [llm/factory.py](/concepts/modules/llm-factory.md) — provider/model resolution |
| `llm/gemini.py`, `llm/openai_model.py` | [LLM port subsystem](/concepts/subsystems/llm-port.md) |
| `expectation_agent/agent.py` | [expectation_agent/agent.py](/concepts/modules/expectation-agent-agent.md) |
| `expectation_agent/rubric.py` | [expectation_agent/rubric.py](/concepts/modules/expectation-agent-rubric.md) — the deterministic tables |
| `expectation_agent/schema.py` | [InterviewExpectation contract](/concepts/contracts/interview-expectation.md) |
| `expectation_agent/prompts.py` | [Expectation agent subsystem](/concepts/subsystems/expectation-agent.md) |
| `candidate_agent/agent.py` | [candidate_agent/agent.py](/concepts/modules/candidate-agent-agent.md) |
| `candidate_agent/archetypes.py` | [candidate_agent/archetypes.py](/concepts/modules/candidate-agent-archetypes.md) — the catalog |
| `candidate_agent/engine_contract.py` | [candidate_agent/engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) |
| `candidate_agent/schema.py` | [VirtualCandidate contract](/concepts/contracts/virtual-candidate.md), [EngineContract](/concepts/contracts/engine-contract.md) |
| `candidate_agent/prompts.py` | [Candidate agent subsystem](/concepts/subsystems/candidate-agent.md) |
| `control_plane/api.py` | [control_plane/api.py](/concepts/modules/control-plane-api.md), [REST API](/concepts/contracts/rest-api.md) |
| `control_plane/ports.py` | [Storage ports](/concepts/contracts/storage-ports.md) |
| `control_plane/repository.py` | [control_plane/repository.py](/concepts/modules/control-plane-repository.md) |
| `control_plane/database.py` | [Database schema](/concepts/contracts/database-schema.md) |
| `control_plane/schemas.py` | [Interview record](/concepts/contracts/interview-record.md) |
| `control_plane/persona.py` | [Control plane subsystem § legacy persona](/concepts/subsystems/control-plane.md) |
| `control_plane/main.py` | [Dev setup](/concepts/runbooks/dev-setup.md) |
| `ui/` | [Test UI](/concepts/subsystems/ui.md) |
| `tests/` | [Test suite](/concepts/subsystems/test-suite.md), [Architecture](/concepts/architecture.md) |
| `scripts/check.sh` | [Checks](/concepts/runbooks/checks.md) |
| `scripts/export_schemas.py` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `owner_handover/` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `docs/BRD_AI_Interview_Platform_v2.md` | [BRD](/references/brd.md) |
| `docs/GO_ENGINE_CONTRACT.md` | [EngineContract](/concepts/contracts/engine-contract.md) |
| `docs/ENGINE_IMPLEMENTATION_PLAN.md` | [Live-session engine](/concepts/subsystems/engine.md) |
| `docs/ENGINE_ONE_BRAIN_TWO_PARTS.html` | [Live-session engine](/concepts/subsystems/engine.md) — diagrams of the Speaker/Thinker sync; open in a browser |
| `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — Go module, separate build and CI gate |
| `.golangci.yml` | [Live-session engine](/concepts/subsystems/engine.md), [Checks](/concepts/runbooks/checks.md) |
| `pyproject.toml`, `.env.example` | [Conventions](/concepts/conventions.md), [Dev setup](/concepts/runbooks/dev-setup.md) |
| `control_plane.db` | [Database schema](/concepts/contracts/database-schema.md) — gitignored |

## "I want to change X" → read Y

| Change | Read first |
|---|---|
| Add a candidate archetype | [archetypes.py](/concepts/modules/candidate-agent-archetypes.md) — and note the OCP test proves no agent edit is needed |
| Add an LLM provider | [llm/factory.py](/concepts/modules/llm-factory.md), [StructuredModel](/concepts/contracts/structured-model.md) |
| Change what the persona prompt says | [engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) — **bump `ENGINE_CONTRACT_VERSION`** |
| Change phase durations, criteria, or flags | [rubric.py](/concepts/modules/expectation-agent-rubric.md) |
| Change what the model is allowed to author | [Determinism split](/concepts/determinism.md) first, then the agent's `_build_*` helpers |
| Add or change an endpoint | [REST API](/concepts/contracts/rest-api.md), [api.py](/concepts/modules/control-plane-api.md) — pick the narrowest port |
| Swap SQLite for Postgres | [Storage ports](/concepts/contracts/storage-ports.md), [Database schema](/concepts/contracts/database-schema.md) |
| Anything inside `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — then `go test ./internal/arch`, which enforces the layering |
| Change any Pydantic model in the public surface | [Owner handover](/concepts/subsystems/owner-handover.md) — regenerate, or CI fails |
