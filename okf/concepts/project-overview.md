---
type: Project
title: interview-watcher
description: The interview control plane — job specs in, interviewer expectations and virtual candidate personas out.
resource: /
tags: [project, control-plane, fastapi, interviewer-training]
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
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /README.md
  - resource: /docs/BRD_AI_Interview_Platform_v2.md
  - resource: /pyproject.toml
---
# interview-watcher

The interview **control plane**. Python, FastAPI, SQLite. It owns the *what* of
an interview; the runtime engine that actually holds the conversation is a
separate Go/Rust build and lives elsewhere.

Four jobs:

1. **Create interviews from a job spec** — title, JD, required skills, location type, experience level, company type. Candidate and interviewer are assigned later, not at creation.
2. **Generate a deterministic interviewer expectation** — what must be covered, for how long, and how a good interviewer runs the session.
3. **Enroll virtual candidates** — LLM-cast personas stored in the database that a *human* interviewer practises against. Each persona carries a ground-truth answer key used to grade the interviewer afterwards.
4. **Run the interview** — a live session against one of those personas, **typed or spoken**, stored as a timestamped transcript. The live call is browser-to-vendor WebRTC; that audio never enters this service. A voice session's audio is separately **recorded by the browser** and uploaded here in chunks, out of band from the call — see [Session recording](/concepts/contracts/session-recording.md) — and [Run an interview](/concepts/runbooks/run-an-interview.md).

The last two are the product's real point: this is a **training rig for
interviewers**, not an interviewing bot. The persona plays the candidate; the
human plays the interviewer; the transcript is the evidence the report will be
built from.

⚠️ **Direction of travel.** BRD v3 flips the assessed subject from the candidate
to the **hiring manager**, replaces the JD-driven rubric with a fixed one, and
drops the pass/fail verdict entirely. `docs/PIVOT_PLAN_MANAGER_ASSESSMENT.md`
is the plan; Phase 1 (the live text session) has landed on the *existing*
domain model, and Phases 2–5 pivot the domain underneath it. Read the BRD before
changing anything about what is scored or who is scored.

## What makes it unusual

**Almost nothing important is left to the model.** Archetype, verdict, every
trait score, scorecard weights, knowledge ceilings, phase durations, evaluation
criteria and weights are all computed in code, seeded from
`SHA256(interview_id + archetype)`. The model writes only what has to be grounded
in the specific job. See [Determinism split](/concepts/determinism.md) — it is
the organizing principle of the whole repo.

**Architecture rules are executable.** `tests/test_architecture.py` turns SRP,
OCP, LSP, ISP, DIP and layering into failing tests rather than review
conventions. Adding a vendor SDK import outside `llm/` breaks the build.

## Relationship to smart-Interview

`smart-Interview` is the real-time **voice interviewer engine** — a separate
repo, split out from this one at commit `378a7b4`. **Nothing here imports from
it.** The boundary is deliberate: that repo owns the *how* of a live
conversation, this one owns the *what* of an interview. See
[the sibling-repo reference](/references/smart-interview-relationship.md).

## Build state (2026-08-27)

* **Working**: interview creation, expectation generation and storage, **the v2.0 seven-archetype persona library** (each stressing one manager competency, with session beats and a stress profile), enrollment with re-cast and seeding, engine-contract and scorecard endpoints, **the live text session** (start, turn, end, stored transcript, browser chat view), **the live voice session** (OpenAI Realtime over WebRTC from the browser, deterministic per-persona voice, transcript ingest), **browser-captured session recording** for voice sessions (dual-channel, chunked upload, playback and download in the UI — see [Session recording](/concepts/contracts/session-recording.md)), session listing per interview, the React console aligned to the SkillBrew.AI design mockup, the offline check suite, schema export.
* **Partly built**: the Phase 0 MVP defined by `interview_training_wizard (1).html`. **M1 shipped** — the full interview configuration (location, department, manager level, language, proctoring, operator notes, the fixed role-fact checklist and report-section toggles), plus `evaluation_agent/` holding the rubric and the role-fact checklist. M2 (hiring-manager cohort), M3 (evaluation layer and report) and M4 (report UI) are open. Plan: `~/.claude/plans/humble-tinkering-ocean.md`.
* **Partly built**: the persona library v2 — pivot plan Phase 3. The **catalog half shipped**; the behavioural half (`DisruptionSpec`, `candidate_questions`) did not. Session beats reach the live persona through the casting prompt, so they are a tendency, not a scripted event. (`ENGINE_CONTRACT_VERSION` is now **v1.3**, carrying the dual-model runtime fields — precompiled beliefs, stall phrases, pre-gate lexicon, unlock spec and frozen TTS voice.)
* **Partly built**: the **Go live-session engine**. No longer parked. A live interview runs end to end — media in over a ticketed WebSocket, local speech detection, the Gemini Live Speaker, a pre-synthesized opening line in the contract's frozen voice — but nothing is *recorded on the engine side* yet, so nothing from an engine-run session is graded. (The control plane's browser-captured recording, for its own voice sessions, is a separate producer — see [Session recording](/concepts/contracts/session-recording.md) — and does not change this.) See [Live-session engine](/concepts/subsystems/engine.md) for what it does and does not do.
* **Working (2026-08-27)**: the **evaluation layer** — pivot plan Phase 4, and no longer on the designed-not-built list. Deterministic signals, the analytical report, and as of 2026-08-27 the **judge pass**: one model call that writes the report's prose while `report_engine/validate.py` vetoes any quote that is not in the transcript verbatim and any sentence that states a number. The report a manager reads is two pages of plain language; the signal tables are behind a `detail` flag. Spec phase 7, the audio-derived English module, is still open. See [Report engine](/concepts/subsystems/report-engine.md).
* **Designed, not built**: the manager-assessment domain model (role cards replacing job specs) — Phase 2; the manager cohort (roster, CSV upload, invites) — nowhere in the plan yet, though the design mockup shows it; interviewer assignment (`interview_assignments` table exists and is unused). On the engine side: the recorder and grading bundle (the `producer='engine'` half of [Session recording](/concepts/contracts/session-recording.md)), the WebRTC transport, and an independent ASR adapter (every session currently runs `degraded:asr`).
* **Deployed**: `prod` is live at `https://interview.opsintelai.com` on one EC2 instance (see `infra/README.md`). The control plane, the UI and the report engine work there; **`engined` has never started successfully on it** — in `-dev-sample-contract` mode it reads the sample contract from a build-machine path that ships in no artifact, so voice sessions do not run on the deployed stack. The analysis agent needs `ffmpeg`/`ffprobe` on PATH, which the instance now installs.
* **Stand-in**: SQLite. The schema ports to PostgreSQL with minimal change, and Postgres is the intended bridge to the runtime engine.
* **Legacy**: `control_plane/persona.py` — the original BRD §4.3 seeded persona, attached at creation for `training_interviewer` mode. Superseded by [`candidate_agent`](/concepts/subsystems/candidate-agent.md) but still wired in.

## Layout

```
llm/                 Provider port + Gemini/OpenAI adapters — the only vendor SDKs
expectation_agent/   Expectation agent — persona, guardrails, fixed rubric
candidate_agent/     Virtual candidate agent — archetype catalog, engine contract, text + voice sessions
evaluation_agent/    Manager assessment — the fixed rubric and the role-fact checklist
control_plane/       FastAPI service, storage ports, SQLite adapter
owner_handover/      JSON Schemas + samples, regenerated from the Pydantic models
ui/                  React + Vite test UI
tests/               Offline checks (fast) + live scenario scripts
scripts/             check.sh, export_schemas.py
engine/              Go live-session engine — runs a live session; no engine-side recording yet
docs/                BRDs, pivot plan, Go engine contract and plan
```
