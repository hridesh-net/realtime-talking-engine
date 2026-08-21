# Modules

One reference card per significant source file: API surface with line anchors,
invariants, and gotchas. These exist so an agent can answer "what does this file
do and what breaks if I change it" without opening it.

Data shapes live in [Contracts](/concepts/contracts/index.md) instead —
`llm/base.py`, `control_plane/ports.py`, `control_plane/database.py`,
`control_plane/schemas.py`, `expectation_agent/schema.py`, and
`candidate_agent/schema.py` are documented there.

## llm
* [llm/factory.py](/concepts/modules/llm-factory.md) - provider and model resolution.

## expectation_agent
* [expectation_agent/rubric.py](/concepts/modules/expectation-agent-rubric.md) - the deterministic tables.
* [expectation_agent/agent.py](/concepts/modules/expectation-agent-agent.md) - pre-compute, call, overwrite.

## candidate_agent
* [candidate_agent/archetypes.py](/concepts/modules/candidate-agent-archetypes.md) - the fixed catalog.
* [candidate_agent/agent.py](/concepts/modules/candidate-agent-agent.md) - casting and re-imposition.
* [candidate_agent/engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) - the compiled runtime slice.

## control_plane
* [control_plane/api.py](/concepts/modules/control-plane-api.md) - routes and dependency injection.
* [control_plane/repository.py](/concepts/modules/control-plane-repository.md) - the SQLite adapter.
