# Subsystems

One page per package, in dependency order (bottom of the stack first).

* [LLM port](/concepts/subsystems/llm-port.md) - `llm/`. The only place a vendor SDK appears.
* [Candidate agent](/concepts/subsystems/candidate-agent.md) - `candidate_agent/`. Archetype + job spec → persona.
* [Evaluation agent](/concepts/subsystems/evaluation-agent.md) - `evaluation_agent/`. The fixed manager rubric, the role-fact checklist and the per-interview expectation items — the configuration the report engine scores against. The scoring itself lives in `report_engine/`.
* [Audio analysis agent](/concepts/subsystems/analysis-agent.md) - `analysis_agent/`. Listens to the recording against the expectation items; observations, not a report.
* [Expectation agent](/concepts/subsystems/expectation-agent.md) - **superseded 2026-09-13**, package deleted. Kept as history; the evaluation agent is what replaced it.
* [Report engine](/concepts/subsystems/report-engine.md) - `report_engine/`. Standalone: session bundle → the manager's report. Spec phases 1–6 built (signals, scoring, the judge under a code veto, the *heard* half from the analysis); phase 7, the audio-derived English module, is not.
* [Control plane](/concepts/subsystems/control-plane.md) - `control_plane/`. FastAPI service and SQLite adapter.
* [Test UI](/concepts/subsystems/ui.md) - `ui/`. React + Vite operator console.
* [Owner handover](/concepts/subsystems/owner-handover.md) - `owner_handover/`, `scripts/export_schemas.py`.
* [Test suite](/concepts/subsystems/test-suite.md) - `tests/`. Offline checks and live scenarios.
* [Live-session engine](/concepts/subsystems/engine.md) - `engine/`. Go runtime that performs the spoken session and reports it back to the control plane. Runs end to end; no engine-side recording yet.
