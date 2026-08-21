# Subsystems

One page per package, in dependency order (bottom of the stack first).

* [LLM port](/concepts/subsystems/llm-port.md) - `llm/`. The only place a vendor SDK appears.
* [Expectation agent](/concepts/subsystems/expectation-agent.md) - `expectation_agent/`. Job spec → interviewer plan.
* [Candidate agent](/concepts/subsystems/candidate-agent.md) - `candidate_agent/`. Archetype + job spec → persona.
* [Control plane](/concepts/subsystems/control-plane.md) - `control_plane/`. FastAPI service and SQLite adapter.
* [Test UI](/concepts/subsystems/ui.md) - `ui/`. React + Vite operator console.
* [Owner handover](/concepts/subsystems/owner-handover.md) - `owner_handover/`, `scripts/export_schemas.py`.
* [Test suite](/concepts/subsystems/test-suite.md) - `tests/`. Offline checks and live scenarios.
