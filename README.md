# interview-watcher

Interview control plane. Four things, all in Python:

1. Create interviews from a job spec.
2. Generate a deterministic **interviewer expectation** for each one — what must
   be covered, for how long, and how a good interviewer should run the session.
3. Enroll **virtual candidates** — LLM-cast personas, stored in the database,
   that a human interviewer practises against. Each persona carries a
   ground-truth answer key used to grade the interviewer afterwards.
4. **Run the interview** — a live session against one of those personas,
   **typed or spoken**, stored as a timestamped transcript and, for voice
   sessions, a stereo recording. Open the UI, pick a persona, hit **Chat** or
   **🎙 Voice**, and conduct it.
5. **Analyse the recording** — an audio-native pass that listens to the session
   against the expectation it was held against, and stores structured
   observations. Not a report: observations.
6. **Generate the report** — the manager's development report, composed in code
   from the transcript and the analysis. Free and instant; the analysis is the
   paid step and it runs once.

**The hiring manager is the one assessed, not the candidate.** The candidate is
a scripted persona; the manager is the learner.

This project is **separate from `smart-Interview`** (the real-time voice
interviewer engine). Nothing here imports from it. The runtime engine stays in
Go/Rust; this service owns the "what" of an interview.

## Layout

```
llm/                 Provider port + Gemini/OpenAI adapters (the only vendor SDKs)
expectation_agent/   Expectation agent — persona, guardrails, fixed rubric
candidate_agent/     Virtual candidate agent — archetype catalog, engine contract, live session
evaluation_agent/    The manager rubric and the role-fact checklist
analysis_agent/      Audio analysis — INSTRUCTIONS.md, windowing harness, observations
report_engine/       Standalone: session bundle in, report out. Imports nothing first-party
control_plane/       FastAPI service, storage ports, SQLite adapter
owner_handover/      JSON Schemas + samples for the API contract (deliverables)
ui/                  React + Vite test UI
tests/               Offline checks (fast) + live scenario scripts
scripts/             check.sh, export_schemas.py
engine/              Go live-session engine (voice) — skeleton, parked
docs/                BRDs, pivot plan, engine contract, scoring spec, pricing
okf/                 The knowledge bundle — read this before the source
```

Dependencies point one way: `llm` ← agents ← `control_plane`. Nothing outside
`llm/` imports a vendor SDK; nothing outside `control_plane/` touches storage.
`tests/test_architecture.py` fails the build if that stops being true.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # then fill GEMINI_API_KEY (or OPENAI_API_KEY)
```

## Run

```bash
.venv/bin/python -m control_plane.main          # http://127.0.0.1:8081
cd ui && npm install && npm run dev             # http://localhost:3000
```

The UI proxies `/api` to `127.0.0.1:8081`, so start the API first.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/interviews` | Create an interview from a job spec |
| GET | `/api/v1/interviews` | List interviews (optional `?status=`) |
| GET | `/api/v1/interviews/{id}` | Fetch one interview |
| POST | `/api/v1/interviews/{id}/expectation` | Generate + persist the expectation (AI call) |
| GET | `/api/v1/interviews/{id}/expectation` | Fetch the stored expectation |
| GET | `/api/v1/candidate-archetypes` | The fixed persona catalog |
| POST | `/api/v1/interviews/{id}/candidates` | Cast + persist personas (AI call) |
| GET | `/api/v1/interviews/{id}/candidates` | List enrolled personas |
| GET | `/api/v1/candidates/{cid}` | Fetch one persona |
| GET | `/api/v1/candidates/{cid}/engine-contract` | Runtime slice for the interview engine |
| GET | `/api/v1/candidates/{cid}/scorecard` | Ground-truth key for grading the interviewer |
| DELETE | `/api/v1/candidates/{cid}` | Remove a persona |
| POST | `/api/v1/sessions` | Start a live interview against one persona (casts it first if needed) |
| POST | `/api/v1/sessions/{id}/turns` | Send the manager's line, get the persona's reply (AI call) |
| POST | `/api/v1/sessions/{id}/end` | Close the session |
| GET | `/api/v1/sessions/{id}` | Session with its full timestamped transcript |
| GET | `/api/v1/voice-capability` | Whether this deployment can run voice sessions |
| POST | `/api/v1/sessions/{id}/realtime` | Mint the browser's ephemeral credential for a voice call |
| POST | `/api/v1/sessions/{id}/transcript` | Record a spoken turn (no reply generated) |

Interview creation captures the job spec only — `job_title`, `jd`,
`skills_required`, `job_location_type`, `experience_level`, `company_type`.
Candidate and interviewer are assigned later, not at creation.

`POST /interviews/{id}/candidates` with **no body** enrolls the two defaults:
one candidate who should be selected and one who should be rejected. Pass
`{"archetypes": [...]}` to choose from the catalog, and `"regenerate": true` to
re-cast personas that are already enrolled.

Contracts live in `owner_handover/`, regenerated from the Pydantic models by
`scripts/export_schemas.py` so they cannot drift:

- `interview_create_schema.json` / `interview_create_sample.json`
- `interview_response_schema.json`
- `expectation_input_schema.json`
- `expectation_output_schema.json` / `expectation_output_sample.json`
- `candidate_enroll_schema.json`
- `candidate_output_schema.json` / `candidate_output_sample.json`
- `engine_contract_schema.json` / `engine_contract_sample.json`
- `candidate_archetypes.json` — the full catalog, readable without running anything

## Virtual candidates

Seven archetypes, fixed in `candidate_agent/archetypes.py` (catalog `v2.0`).
The catalog is built around the **manager** being assessed: each persona exists
to put one manager competency under pressure.

| Archetype | Stresses most | Tests whether the manager… |
|---|---|---|
| `cooperative_trap` *(default)* | Unconscious Bias | declines a volunteered protected detail and routes the accommodation ask to policy |
| `evasive` *(default)* | Structured Interviewing | asks again after a platitude, and lets a silence do the work |
| `nervous_fresher` | Communication, Candidate Experience | warms the room before assessing, and scores content rather than delivery |
| `inflated_resume` | Structured Interviewing | converts "we" into "I" and probes a claim to its breaking point |
| `comp_first` | Hiring with Clarity | sells the role and states the band honestly without caving |
| `defensive` | Communication & Tone | holds composure through provocation and re-plans around a hard stop |
| `rambler` | Structured Interviewing | redirects without rudeness and still covers what was planned |

Each also declares `session_beats` (what it tends to do — fed into casting, so
it reaches the compiled prompt) and `stresses` (rubric criterion → 1-4). The
five criteria are Hiring with Clarity, Structured Interviewing, Unconscious
Bias, Candidate Experience, Communication & Tone. **Nothing is scored yet** —
the evaluation layer has not been built, and there is no critical-fail gate on
any criterion by design.

Every persona carries the same fixed axes:

- **Way of talking** — pace, verbosity, filler and hesitation frequency,
  formality, interruption behaviour, verbal tics, sample phrases.
- **Smartness / dumbness ratio with seriousness** — plus effort, interest,
  honesty, preparedness, nervousness, each 0–10.
- **Selectable or rejectable** — `select`, `reject`, or `borderline`, with the
  rationale written against the actual required skills.

Plus the parts the runtime needs: a per-skill knowledge ceiling with a named
breaking point, specific wrong beliefs for the personas that bluff, resume
claims graded by truthfulness, an unlock condition, and a compiled system prompt
the interview engine injects verbatim. See `docs/GO_ENGINE_CONTRACT.md`.

### What the model does and does not decide

Archetype, verdict, every trait score, scorecard weights and knowledge ceilings
are computed in code from `SHA256(interview_id + archetype)`. The model only
writes what has to be grounded in the specific job — who the person is, what
they can talk about, where they break down, how they sound. Levels outside the
archetype's band are clamped; scorecard ids the model invents are discarded.

`seed_fingerprint` is stable for a given `(interview, archetype)`, so two
interviewers can be measured against the same candidate. `fingerprint` also
covers the model-authored content and moves on every re-cast, so you can detect
a persona that changed underneath a training set.

## Storage

SQLite (`control_plane.db`, path via `CONTROL_PLANE_DB`) — tables `interviews`,
`ai_personas`, `interview_expectations`, `virtual_candidates`, `sessions`,
`session_turns`. Personas are
stored as the full JSON document plus indexed columns (archetype, verdict,
fingerprints), unique on `(interview_id, archetype)` so a re-cast replaces
rather than duplicates. The schema ports to PostgreSQL with minimal change;
Postgres is the intended bridge to the Go/Rust runtime.

## Running an interview

```bash
.venv/bin/python -m control_plane.main    # start this first
cd ui && npm run dev                      # then http://localhost:3000
```

Select an interview, scroll to the persona catalog, and pick a card. An
archetype that is not yet enrolled is cast on the spot.

**Chat** — you type as the hiring manager; the persona answers in character.
Enter sends, Shift+Enter breaks the line.

**🎙 Voice** — a real spoken interview. The browser talks to the vendor
directly and the persona opens the call with its own scripted first line; no
push-to-talk, and you can interrupt it mid-sentence. The first click raises
Chrome's microphone prompt, which you have to allow yourself. The header shows
which talker and transcriber you are getting, and offers a microphone picker and
a noise-suppression toggle.

Two providers, chosen by `VOICE_PROVIDER`:

* **Gemini Live** (default) — a WebSocket carrying raw PCM. Needs
  `GEMINI_API_KEY`.
* **OpenAI Realtime** — the WebRTC path. Set `VOICE_PROVIDER=openai`; needs
  `OPENAI_API_KEY` with Realtime access, and `TRANSCRIBE_MODEL` picks its
  speech-to-text (Gemini transcribes in-session).

Leave `VOICE_PROVIDER` blank to auto-detect. `GET /api/v1/voice-capability` says
whether voice is available at all, and the UI disables the button with the
reason if not.

**End interview** closes the session either way and leaves the stored transcript
on screen.

Every turn is written to `session_turns` with a **server-side** timestamp and
elapsed offset — the transcript is the evidence the evaluation layer will read,
so its clock and ordering are not the client's to supply. Text and voice produce
the same transcript shape.

Both modes are driven by the same compiled `EngineContract` the Go voice engine
will consume; each only appends its own modality preamble. In voice mode the
audio never touches this service — the control plane compiles the persona,
seals it into a short-lived credential (the browser never receives the prompt),
and the media runs browser-to-vendor.

**Voice is Speaker-only today.** One realtime model both decides what the persona
knows and says it, with the knowledge ceiling carried as prompt text and nothing
enforcing it. The deterministic pre-gate, false-belief injection and claims
ledger live in the Go engine's Thinker, which is still at Phase 0. A voice
persona is easier to argue past its ceiling than a text one; reproduce in Chat to
tell a persona problem from a modality one.

There is no report yet. Ending a session stores the transcript and stops.

## Reports

A report has two halves, and says which is which on every row.

**Counted** signals are computed from the stored transcript by code. Re-running
produces byte-identical numbers, and a test asserts it.

**Heard** signals come from the audio analysis. They exist because the counted
half cannot read what it was not written for: on a real session the counted
fairness detector returned **10/10, "no protected topics detected"**, on an
interview containing questions about household composition and salary history —
asked in Hindi, which an English lexicon does not match. Hearing the audio
brought that criterion to 6.24.

Every report carries a **basis panel**: how many signals were counted versus
heard, which model and instruction version produced the analysis, the languages
heard, and how many timestamps were discarded for falling outside the recording.

```bash
# analyse (background, ~40s for a six-minute recording), then report
curl -X POST localhost:8081/api/v1/sessions/$SID/analyze
curl        localhost:8081/api/v1/sessions/$SID/analysis      # poll until complete
curl -X POST localhost:8081/api/v1/sessions/$SID/report
```

The report engine also runs standalone, with no database and no network:

```bash
python scripts/make_bundle.py --session $SID -o bundle.json
python -m report_engine bundle.json -o report.html
```

Design and provenance for every threshold:
[`docs/REPORT_ENGINE_SCORING_SPEC.md`](docs/REPORT_ENGINE_SCORING_SPEC.md).
The analysis agent's rules are a shipped, versioned document:
[`analysis_agent/INSTRUCTIONS.md`](analysis_agent/INSTRUCTIONS.md) — changing it
changes what every report is built from.

## What a session costs

About **$1.07** marginal for a 20-minute voice session. The live voice call is
roughly four times the analysis (~$0.85 against $0.19). Report *scoring* still
calls no model and is free; the report's *prose* is one judge call at well under
a cent, which means regenerating a report is no longer free — `judge=false`
produces the same numbers with code-composed sentences and no call. Measured
token counts, quoted vendor rates and the levers that actually move the number
are in [`docs/PRICING_PER_SESSION.md`](docs/PRICING_PER_SESSION.md).

## Determinism

The expectation agent is deliberately not free-form. Phase durations, the six
evaluation criteria and weights, interview type, baseline red/green flags,
resume-probing policy, and interviewer guidance are computed in
`expectation_agent/rubric.py` and **overwrite** the model output. The model only
fills in the role-specific text. Temperature is 0.1 and output is constrained by
`EXPECTATION_JSON_SCHEMA`.

## Checks

```bash
scripts/check.sh            # everything offline — lint, format, types, architecture
scripts/check.sh --live     # also the model scenario tests (costs money)
```

| Check | Enforces |
|---|---|
| `ruff check` | The explicit rule set in `pyproject.toml` — pyflakes, naming, py311 idioms, bugbear, docstrings, annotations |
| `ruff format --check` | One formatting standard, no debate |
| `mypy` | `disallow_untyped_defs`, no implicit Optional, pydantic plugin |
| `tests/test_architecture.py` | SOLID and layering (below) |
| `tests/test_candidate_rubric.py` | Determinism, clamping, scorecard integrity |
| `tests/test_session.py` | The text session — contract-verbatim prompt, transcript ordering, session endpoints |
| `tests/test_voice.py` | The voice session — deterministic voice/speed, the never-leak-the-prompt guarantee, voice endpoints |
| `scripts/export_schemas.py --check` | `owner_handover/` matches the code |
| gofmt / go vet / go build / `go test -race` / go architecture | The Go engine in `engine/`, run from inside that module |

### SOLID checks (BRD NFR-003)

`tests/test_architecture.py` turns each principle into a failing test rather
than a code-review convention:

- **SRP** — agents never import `sqlite3` or `control_plane`; generation does
  not persist. Prompt modules perform no I/O. Schema modules hold no logic.
- **OCP** — registering a new archetype or provider flows through the system
  with no edit to any agent. The test registers one at runtime and proves it.
- **LSP** — every `StructuredModel`, `ChatModel` and `RealtimeBroker` shares its
  base signature, implements the whole contract, and is constructible through one
  uniform call; every archetype honours the same shape.
- **ISP** — `InterviewStore` / `ExpectationStore` / `CandidateStore` /
  `SessionStore` stay small and non-overlapping; handlers depend on the one they
  need. `StructuredModel`, `ChatModel` and `RealtimeBroker` are three ports, not
  one.
- **DIP** — vendor SDKs appear only inside `llm/`; agents take an injected
  model and never read API keys; handlers are typed against ports, not the
  SQLite adapter.

Plus a layering check that no package imports one above it, and no module uses
relative imports.

### Live scenario tests

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

These call the model. The candidate suite asserts verdicts and traits come from
the catalog, knowledge stays under the ceiling, every required skill is covered,
names are unique within a training set, and the same seed reproduces the same
person.

## Config

Resolution order per role: `<ROLE>_PROVIDER` / `<ROLE>_MODEL`, then
`LLM_PROVIDER` / `LLM_MODEL`, then the provider default. Four roles:
`EXPECTATION` and `CANDIDATE` (one structured call each, per interview or
persona), `SESSION` (one chat call **per turn** — the one that dominates cost
and pace), and `JUDGE` (reserved for the evaluation layer).

`VOICE` is resolved separately and does **not** fall back to `LLM_PROVIDER`:
realtime speech-to-speech is OpenAI-only today, so a Gemini-configured
deployment still gets voice from `OPENAI_API_KEY`, or gets no Voice button at
all. `VOICE_MODEL` must name a realtime speech model, never a text one.

| Var | Default | Meaning |
|---|---|---|
| `EXPECTATION_PROVIDER` / `CANDIDATE_PROVIDER` / `SESSION_PROVIDER` / `JUDGE_PROVIDER` | — | `gemini` or `openai` |
| `EXPECTATION_MODEL` / `CANDIDATE_MODEL` / `SESSION_MODEL` / `JUDGE_MODEL` | — | Model ID — config, never hardcoded |
| `VOICE_PROVIDER` / `VOICE_MODEL` | — / `gpt-realtime-2` | Voice mode. Realtime providers only — **no** `LLM_*` fallback |
| `LLM_PROVIDER` / `LLM_MODEL` | — | Fallback for the text roles |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | — | At least one required |
| `CONTROL_PLANE_DB` | `control_plane.db` | SQLite path |
| `CONTROL_PLANE_PORT` | `8081` | Service port |

## License

Proprietary and confidential. Copyright (c) 2026 Hridesh Sharma. All rights
reserved. See [LICENSE](LICENSE) — access to this repository does not grant
permission to use the software.
