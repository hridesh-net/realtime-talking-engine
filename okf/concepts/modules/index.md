# Modules

One reference card per significant source file: API surface with line anchors,
invariants, and gotchas. These exist so an agent can answer "what does this file
do and what breaks if I change it" without opening it.

Data shapes live in [Contracts](/concepts/contracts/index.md) instead —
`llm/base.py`, `control_plane/ports.py`, `control_plane/database.py`,
`control_plane/schemas.py`, `evaluation_agent/schema.py`, and
`candidate_agent/schema.py` are documented there.

## llm
* [llm/factory.py](/concepts/modules/llm-factory.md) - provider and model resolution.

## evaluation_agent
* [evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) - the fixed manager rubric, its override, and the interview-type table.
* [evaluation_agent/role_facts.py](/concepts/modules/evaluation-agent-role-facts.md) - drafts the role-fact checklist wording.
* [evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md) - the fixed expectation items and the agent that drafts and classifies them.

## expectation_agent — **superseded 2026-09-13**, package deleted
Both cards are kept as history; the decisions in them are what the replacement
was argued against. See [Expectation agent](/concepts/subsystems/expectation-agent.md).
* [expectation_agent/rubric.py](/concepts/modules/expectation-agent-rubric.md) - the deterministic tables.
* [expectation_agent/agent.py](/concepts/modules/expectation-agent-agent.md) - pre-compute, call, overwrite.

## candidate_agent
* [candidate_agent/archetypes.py](/concepts/modules/candidate-agent-archetypes.md) - the fixed catalog.
* [candidate_agent/agent.py](/concepts/modules/candidate-agent-agent.md) - casting and re-imposition.
* [candidate_agent/engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) - the compiled runtime slice.
* [candidate_agent/session.py](/concepts/modules/candidate-agent-session.md) - one persona turn in a live text interview.
* [candidate_agent/voice.py](/concepts/modules/candidate-agent-voice.md) - the persona's realtime voice session config.

## control_plane
* [control_plane/api.py](/concepts/modules/control-plane-api.md) - routes and dependency injection.
* [control_plane/repository.py](/concepts/modules/control-plane-repository.md) - the SQLite adapter.

## Files without a card — by decision, not omission
`control_plane/object_store.py`, `control_plane/migrate.py` and
`control_plane/reporting.py` are documented on the contract and subsystem pages
they serve ([Storage ports](/concepts/contracts/storage-ports.md),
[Database schema](/concepts/contracts/database-schema.md),
[Report engine](/concepts/subsystems/report-engine.md)); `analysis_agent/*` and
`report_engine/*` are documented as whole packages ([Audio analysis
agent](/concepts/subsystems/analysis-agent.md), [Report
engine](/concepts/subsystems/report-engine.md)) because their invariants live
across files, not in one. The [Repo Map](/concepts/repo-map.md) routes every
path either way.
