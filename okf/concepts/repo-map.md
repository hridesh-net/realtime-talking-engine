---
type: Map
title: Repo Map
description: Path → concept routing table; read this to find the right page without grepping the tree.
resource: /
tags: [navigation, index]
generated:
  by: claude-opus-5
  at: "2026-09-14T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-14T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-13T12:00:00Z"
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T18:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T12:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
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
| `llm/openai_realtime.py`, `llm/gemini_live.py` | [Realtime voice](/concepts/contracts/realtime-voice.md) — the two realtime providers; `gemini_live.py` also owns the voice roster **and its gender classification** |
| `llm/failover.py` | [LLM port](/concepts/subsystems/llm-port.md#two-gemini-keys-one-silent-failover-2026-09-01) — retries a key-shaped failure on the provider's second key |
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
| `control_plane/object_store.py` | [Storage ports § the object store](/concepts/contracts/storage-ports.md) — the byte port (`ObjectStore`/`ByteSource`), its filesystem and S3 adapters, and the range rules both obey. **Nothing calls it yet** |
| `control_plane/database.py` | [Database schema](/concepts/contracts/database-schema.md), [Session recording](/concepts/contracts/session-recording.md) — `session_recordings`, `RECORDINGS_DIR` |
| `control_plane/migrate.py`, `control_plane/migrations/` | [Database schema § Postgres](/concepts/contracts/database-schema.md) — the forward-only migration runner, `schema_migrations`, and the Postgres DDL. **No down-migrations** |
| `evaluation_agent/rubric.py` | [evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) — the fixed manager rubric, and `determine_interview_type` |
| `evaluation_agent/role_facts.py`, `prompts.py`, `schema.py` | [evaluation_agent/role_facts.py](/concepts/modules/evaluation-agent-role-facts.md) — the fixed role-fact checklist and its drafting agent |
| `evaluation_agent/expectations.py` | [evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md) — the fixed expectation items, the drafting/classifying agent, and the id slug the rubric is pinned to |
| `control_plane/reporting.py` | [Report engine](/concepts/subsystems/report-engine.md) — the seam that assembles a bundle from stored rows; resolves catalog **and** composed personas |
| `ui/src/ReportView.jsx` | [Test UI](/concepts/subsystems/ui.md) — embeds the engine's own report HTML; print is the PDF path |
| `analysis_agent/INSTRUCTIONS.md` | [Analysis agent instructions](/references/analysis-instructions.md) — the shipped rules; changing it changes every report |
| `analysis_agent/agent.py`, `harness.py` | [Audio analysis agent](/concepts/subsystems/analysis-agent.md) — the windowed run and the merge that owns every number |
| `analysis_agent/audio.py` | [Audio analysis agent](/concepts/subsystems/analysis-agent.md) — windowing; also why timestamps stay in range |
| `analysis_agent/schema.py` | [Audio analysis agent](/concepts/subsystems/analysis-agent.md) — `SessionAnalysis`, and the 60/40 weights |
| `report_engine/signals/assessed.py` | [Report engine](/concepts/subsystems/report-engine.md) — the heard half, from the analysis |
| `llm/base.py` `AudioModel` | [LLM port](/concepts/subsystems/llm-port.md) — the audio port; `AUDIO_PROVIDERS` is deliberately partial |
| `report_engine/score.py`, `transfer.py` | [Report engine](/concepts/subsystems/report-engine.md) — aggregation and the raw-to-score transfer functions |
| `report_engine/acts.py`, `segment.py` | [Report engine](/concepts/subsystems/report-engine.md) — the question act and the four segments |
| `report_engine/signals/` | [Report engine](/concepts/subsystems/report-engine.md) — one module per rubric criterion |
| `report_engine/packs/` | [Report engine](/concepts/subsystems/report-engine.md) — dated jurisdiction and competency packs |
| `report_engine/schema.py` | [Report engine](/concepts/subsystems/report-engine.md) — `SessionBundle` in, `AssessmentReport` out |
| `report_engine/judge.py` | [Report engine](/concepts/subsystems/report-engine.md) — the one model call, and what it may author. See [Determinism split](/concepts/determinism.md) |
| `report_engine/validate.py` | [Report engine](/concepts/subsystems/report-engine.md) — the judge veto: verbatim spans, who spoke, no numbers in prose |
| `report_engine/narrate.py` | [Report engine](/concepts/subsystems/report-engine.md) — the sentences code composes when no judge has run |
| `report_engine/render.py` | [Report engine](/concepts/subsystems/report-engine.md) — the two-page report, and `detail=True` for the working |
| `scripts/make_bundle.py` | [Report engine](/concepts/subsystems/report-engine.md) — builds a bundle from the DB, a turn list, or the demo fixture |
| `control_plane/schemas.py` | [Interview record](/concepts/contracts/interview-record.md), [Links and participants](/concepts/contracts/links-and-participants.md), [Session transcript](/concepts/contracts/session-transcript.md), [Session recording](/concepts/contracts/session-recording.md) — `RecordingMeta` |
| `control_plane/persona.py` | [Control plane subsystem § legacy persona](/concepts/subsystems/control-plane.md) |
| `control_plane/main.py` | [Dev setup](/concepts/runbooks/dev-setup.md) |
| `ui/src/geminiLive.js`, `ui/src/audio/pcmWorklet.js` | [Realtime voice](/concepts/contracts/realtime-voice.md), [Test UI](/concepts/subsystems/ui.md) — the Gemini WebSocket path: PCM capture, gapless playback, resumption |
| `ui/src/SessionView.jsx`, `ui/src/VoiceSessionView.jsx` | [Test UI § conducting an interview](/concepts/subsystems/ui.md), [Run an interview](/concepts/runbooks/run-an-interview.md), [Session recording](/concepts/contracts/session-recording.md) — the browser-side capture and upload |
| `ui/src/PersonaPicker.jsx` | [Test UI § the persona picker](/concepts/subsystems/ui.md), [archetypes.py](/concepts/modules/candidate-agent-archetypes.md) |
| `ui/src/{Shell,InterviewList,Wizard,InterviewDetail}.jsx` | [Test UI](/concepts/subsystems/ui.md) |
| `ui/src/index.css`, `interview_training_wizard (1).html` | [Test UI](/concepts/subsystems/ui.md) — the mockup is the design source of truth |
| `ui/` | [Test UI](/concepts/subsystems/ui.md) |
| `tests/infra.py`, `tests/conftest.py` | [Test suite](/concepts/subsystems/test-suite.md) — throwaway Postgres/MinIO on **Apple `container`** (never Docker), and the lazy session fixtures |
| `tests/test_object_store.py` | [Test suite](/concepts/subsystems/test-suite.md), [Storage ports](/concepts/contracts/storage-ports.md) — one contract set parametrized over both adapters; the S3 half runs against a **real MinIO**, and errors rather than skips without one |
| `tests/test_migrations.py` | [Database schema § Postgres](/concepts/contracts/database-schema.md) — the runner, and the foreign-key decisions SQLite could not enforce |
| `tests/test_expectations.py` | [evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md) — the clamps, the **pinned fixed ids**, and what `POST /interviews` will accept |
| `tests/test_links_participants.py` | [Links and participants](/concepts/contracts/links-and-participants.md) — the 410s, the constant-time compare, the email-keyed upsert, cross-interview history |
| `tests/` | [Test suite](/concepts/subsystems/test-suite.md), [Architecture](/concepts/architecture.md) |
| `scripts/check.sh` | [Checks](/concepts/runbooks/checks.md) |
| `scripts/rename_columns_sqlite.py`, `scripts/upgrade_sqlite_expectations.py` | [Database schema](/concepts/contracts/database-schema.md) — the two one-offs that bring an existing SQLite `.db` up to date (2026-09-10 renames; 2026-09-13 expectations, participants and links). SQLite has no migration runner; Postgres does |
| `scripts/export_schemas.py` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `owner_handover/` | [Owner handover](/concepts/subsystems/owner-handover.md) |
| `docs/BRD_AI_Interview_Platform_v2.md` | [BRD](/references/brd.md) — **superseded** by BRD v3 |
| `docs/BRD_Interviewer_Upskilling_v3.{html,pdf}` | Current requirements. The manager is assessed, not the candidate; the job card does not drive the rubric; no criterion has a hard limit |
| `docs/PIVOT_PLAN_MANAGER_ASSESSMENT.md` | The BRD v3 pivot — 5 phases, 34 ToDos; retires `expectation_agent/`, session is text-first. **Phase 1 (tasks 1–6) is done**, and **task 7 (retire `expectation_agent/`) was done 2026-09-13**; the rest of Phases 2–5 are open |
| `docs/GO_ENGINE_CONTRACT.md` | [EngineContract](/concepts/contracts/engine-contract.md) |
| `docs/ENGINE_IMPLEMENTATION_PLAN.md` | [Live-session engine](/concepts/subsystems/engine.md) |
| `docs/ENGINE_ONE_BRAIN_TWO_PARTS.html` | [Live-session engine](/concepts/subsystems/engine.md) — diagrams of the Speaker/Thinker sync; open in a browser |
| `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — Go module, separate build and CI gate |
| `engine/internal/session/` | [Live-session engine](/concepts/subsystems/engine.md) — the turn loop and the actor; start at its state table |
| `engine/internal/audio/` | [Live-session engine](/concepts/subsystems/engine.md) — sample domain: resampler, onset detection, jitter buffer, send ring |
| `engine/internal/transport/` | [Live-session engine](/concepts/subsystems/engine.md) — `wsfallback` carries live traffic today; `webrtc` is a placeholder |
| `engine/internal/controlplane/` | [Session ingest](/concepts/contracts/session-ingest.md) — the HTTP `ContractSource`: contract fetch, ingest report with retry and spool |
| `control_plane/migrations/` | [Database schema § Postgres](/concepts/contracts/database-schema.md) — Postgres DDL, one numbered file per change; `0002` is the ingest table, `0003` drops the never-produced `cost_cap` end reason, `0004` adds expectations/participants/links and drops `interview_expectations` and `interview_assignments` |
| `engine/internal/vendors/gemini/` | [Live-session engine](/concepts/subsystems/engine.md) — the Speaker, over the Gemini **Live** API. Read its live-verified facts before changing it |
| `engine/internal/vendors/` (others) | [Live-session engine](/concepts/subsystems/engine.md) — reasoning adapters and TTS; only `cmd/engined` may import any of them |
| `engine/internal/stall/` | [Live-session engine](/concepts/subsystems/engine.md) — pre-synthesized opening line and stall clips |
| `engine/internal/ports/record.go`, `finalize.go` | [Session recording § the forward seam](/concepts/contracts/session-recording.md) — the `Recorder`/`Finalizer` ports the browser-side recording is designed to hand off to; `engine/internal/record/` and `engine/internal/store/s3/` are still `doc.go` stubs, nothing implements them yet |
| `.golangci.yml` | [Live-session engine](/concepts/subsystems/engine.md), [Checks](/concepts/runbooks/checks.md) |
| `pyproject.toml`, `.env.example` | [Conventions](/concepts/conventions.md), [Dev setup](/concepts/runbooks/dev-setup.md) |
| `control_plane.db` | [Database schema](/concepts/contracts/database-schema.md) — gitignored |
| `scripts/transcribe_recording.py`, `scripts/export_engine_contract_sample.py` | [Session recording](/concepts/contracts/session-recording.md) (transcribes each stereo channel separately into a speaker-labelled turn list — exact labels, no diarisation); [EngineContract](/concepts/contracts/engine-contract.md) (the sample the Go contract tests pin) |
| `report_engine/cli.py`, `__main__.py`, `text.py` | [Report engine](/concepts/subsystems/report-engine.md) — `python -m report_engine` over a bundle file (cannot run the judge); shared text helpers |
| `engine/internal/vendors/openaitx/` | [Live-session engine](/concepts/subsystems/engine.md) — the independent Transcriber (OpenAI Realtime transcription, GA shape; live test under `//go:build live`) |
| `engine/internal/{gate,ledger,obs,judge}/` | [Live-session engine](/concepts/subsystems/engine.md) — pre-gate, claims ledger, event log; `judge` is `doc.go` only |
| `engine/internal/config/` | [Live-session engine § Configuration](/concepts/subsystems/engine.md#configuration) — the only place the engine reads the environment |
| `infra/` | `infra/README.md` — one EC2 instance, three processes behind Caddy; Terraform in `infra/terraform/`, artifacts via `infra/build-artifacts.sh`. Deployment facts are in [Project Overview](/concepts/project-overview.md) build state; `*.tfvars` and state are gitignored |
| `docs/INTERVIEW_EXPECTATIONS_PLAN.md` | The approved plan behind the 2026-09-13 change: the four competencies fixed, the granular items dynamic, `report_sections` re-keyed, links and participants. WP1 (domain, storage, API) is done; WP2 (report engine), WP3 (console) and WP4 (verification) are open |
| `docs/INTERVIEWER_PRACTICE_PORTAL_PLAN.md`, `..._SYSTEM_FLOW.md`, `..._UI_FLOW.md` | The SkillBrew portal integration (separate repo): the approved plan, the request path and every endpoint the portal calls, and the user-facing walkthrough. Drove the compatibility layer in [REST API](/concepts/contracts/rest-api.md) |
| `docs/INTERVIEW_EXPECTATIONS_PLAN.md` | [The interview as a fixture](/concepts/interview-fixture.md) — the approved v3 plan (expectations, report shape, links, participants); WP1 built, WP2–WP4 open |
| `docs/INTERVIEWER_PRACTICE_WIZARD_PLAN.md` | The portal's three-step **New interview** wizard (Basics → Expectations → Preview), shaped like BrewVoice's New role. Five work packages; only **WP0 is this repo's** and it is built (2026-09-14): `PATCH /interviews/{id}`, the `InterviewEditor` port, the lifted `validate_expectations` / `validate_report_sections`. WP1–WP4 are `skillbrew-organization` |
| `docs/VIDEO_SESSION_TAB_PLAN.md` | Spoken sessions in their own portal tab, with video — the control-plane half is in [Session recording](/concepts/contracts/session-recording.md) |
| `docs/LIVE_TALKING_ENGINE_HARNESS.{drawio,png,svg}` | [Live-session engine § the harness context](/concepts/subsystems/engine.md) — the latency diagram the actor was built against |
| `docs/REPORT_ENGINE_SCORING_SPEC.md`, `docs/PRICING_PER_SESSION.md` | [Report engine scoring specification](/references/report-engine-spec.md), [What a session costs](/references/pricing.md) |
| `graphify-out/` | Generated knowledge-graph artifacts from the `/graphify` skill — **gitignored and untracked since 2026-09-13**, like `owner_handover/`. Not a source; nothing in this bundle depends on it |

## "I want to change X" → read Y

| Change | Read first |
|---|---|
| Add a candidate archetype | [archetypes.py](/concepts/modules/candidate-agent-archetypes.md) — and note the OCP test proves no agent edit is needed |
| Compose a persona from presets instead of hand-writing an archetype | [trait_dimensions.py](/concepts/subsystems/candidate-agent.md) — `compose_archetype` for the skill/verdict axis, `compose_human_traits` for the realism/compliance taxonomy, `compose_custom_persona` for both at once |
| Add an LLM provider | [llm/factory.py](/concepts/modules/llm-factory.md), [StructuredModel](/concepts/contracts/structured-model.md) |
| Change what the persona prompt says | [engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md) — **bump `ENGINE_CONTRACT_VERSION`** |
| Change the competencies, weights or bands | [evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) — **and** the pinned id list in `tests/test_expectations.py`: a reworded `covers` string re-keys every stored interview's checklist |
| Change what an interview may carry as expectations | [Interview record § expectations](/concepts/contracts/interview-record.md), [expectations.py](/concepts/modules/evaluation-agent-expectations.md) |
| Anything about links, expiry, or who took a session | [Links and participants](/concepts/contracts/links-and-participants.md) — several of its decisions (410 not 404, the public route's four fields, indefinite retention of name and email) are meant to be vetoed, not silently changed |
| Change what the model is allowed to author | [Determinism split](/concepts/determinism.md) first, then the agent's `_build_*` helpers |
| Anything touching what is scored, or who is scored | `docs/BRD_Interviewer_Upskilling_v3.html` first — the rubric is fixed configuration and no criterion may gate the result |
| Add or change an endpoint | [REST API](/concepts/contracts/rest-api.md), [api.py](/concepts/modules/control-plane-api.md) — pick the narrowest port |
| Anything about how a persona behaves *in conversation* | [session.py](/concepts/modules/candidate-agent-session.md) and [Determinism § session agent](/concepts/determinism.md) — the contract prompt is appended to, never edited |
| Anything about how a persona **sounds**, or the voice call | [voice.py](/concepts/modules/candidate-agent-voice.md), [Realtime voice](/concepts/contracts/realtime-voice.md) — and note that voice ordering is contract, not cosmetics |
| The transcript shape, turn timing, or session status | [Session transcript](/concepts/contracts/session-transcript.md) — the evaluation layer and the Go engine both depend on it |
| Swap SQLite for Postgres | [Database schema § Postgres](/concepts/contracts/database-schema.md) first — the schema, the pool and the migration runner already exist; what is left is `repository.py`. Then [Storage ports](/concepts/contracts/storage-ports.md) |
| Add a column, or any schema change | [Database schema § Postgres](/concepts/contracts/database-schema.md) — a **new** `NNNN_name.sql`; never edit an applied migration, which `--check` reports as drift (exit 2). `_SCHEMA` still needs the same change while SQLite is what runs |
| Rename a column | [Database schema](/concepts/contracts/database-schema.md) — `_SCHEMA` is `CREATE TABLE IF NOT EXISTS`, so a rename is invisible to an existing database. `scripts/rename_columns_sqlite.py` is the pattern to follow |
| Anything named `clarity` | [role_facts.py](/concepts/modules/evaluation-agent-role-facts.md) — the **facts** are `role_facts`; the **competency** "Hiring with Clarity" keeps the name `clarity` everywhere. Do not conflate them |
| Anything inside `engine/` | [Live-session engine](/concepts/subsystems/engine.md) — then `go test ./internal/arch`, which enforces the layering |
| A vendor's observed behaviour (Live API, TTS) | [Live-session engine](/concepts/subsystems/engine.md) — the live-verified facts section. Several of them removed planned work; do not re-derive them from docs |
| Change any Pydantic model in the public surface | [Owner handover](/concepts/subsystems/owner-handover.md) — regenerate, or CI fails |
| Store or serve a large file — a recording, an engine bundle | [Storage ports § the object store](/concepts/contracts/storage-ports.md) — `put` takes a **path**, `open` returns a stream; neither takes `bytes`. The range rules and the shared `sessions/{id}/` key layout are decided there, not per caller |
| Anything about the recorded audio artifact, its chunk protocol, or consent/retention | [Session recording](/concepts/contracts/session-recording.md) first — several of its decisions (where bytes land, no auth on the GET, indefinite retention) are meant to be vetoed, not silently changed |
