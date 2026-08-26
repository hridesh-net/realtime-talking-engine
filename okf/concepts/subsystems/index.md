# Subsystems

One page per package, in dependency order (bottom of the stack first).

* [LLM port](/concepts/subsystems/llm-port.md) - `llm/`. The only place a vendor SDK appears.
* [Expectation agent](/concepts/subsystems/expectation-agent.md) - `expectation_agent/`. Job spec → interviewer plan.
* [Candidate agent](/concepts/subsystems/candidate-agent.md) - `candidate_agent/`. Archetype + job spec → persona.
* [Evaluation agent](/concepts/subsystems/evaluation-agent.md) - `evaluation_agent/`. Manager assessment. Partial: the rubric and the role-fact checklist; signals, judge and report not built.
* [Audio analysis agent](/concepts/subsystems/analysis-agent.md) - `analysis_agent/`. Listens to the recording against the expectation; observations, not a report.
* [Report engine](/concepts/subsystems/report-engine.md) - `report_engine/`. Standalone: session bundle → deterministic report. Phases 1-5 built; no judge, no audio yet.
* [Control plane](/concepts/subsystems/control-plane.md) - `control_plane/`. FastAPI service and SQLite adapter.
* [Test UI](/concepts/subsystems/ui.md) - `ui/`. React + Vite operator console.
* [Owner handover](/concepts/subsystems/owner-handover.md) - `owner_handover/`, `scripts/export_schemas.py`.
* [Test suite](/concepts/subsystems/test-suite.md) - `tests/`. Offline checks and live scenarios.
* [Live-session engine](/concepts/subsystems/engine.md) - `engine/`. Go runtime that performs the session. Under construction.
