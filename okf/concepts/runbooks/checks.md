---
type: Runbook
title: Checks
description: One command for every standard — what each check enforces and when to run the live ones.
resource: /scripts/check.sh
tags: [runbook, ci, lint, tests]
generated:
  by: claude-opus-5
  at: "2026-09-14T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-14T00:00:00Z"
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T18:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T12:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5
    at: "2026-08-23T18:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /scripts/check.sh
  - resource: /tests/infra.py
  - resource: /tests/test_object_store.py
  - resource: /pyproject.toml
---
# Checks

```bash
scripts/check.sh          # everything that does not call a model
scripts/check.sh --live   # also the scenario tests (needs an API key, costs money)
```

CI runs this; run it before pushing. Each check prints PASS/FAIL and the script
**continues after a failure**, so one break does not hide the rest. Exit code is
non-zero if any failed, with a summary list.

| Check | Enforces |
|---|---|
| `ruff check .` | The explicit rule set in `pyproject.toml` — pyflakes, imports, naming, py311 idioms, bugbear, docstrings, annotations, no relative imports |
| `ruff format --check .` | One formatting standard. `okf/` and `docs/` are excluded in `pyproject.toml`: ruff reformats fenced Python blocks in markdown, and those are aligned for reading |
| `mypy` | `disallow_untyped_defs`, no implicit Optional, pydantic plugin, over all six first-party packages |
| `pytest tests/test_architecture.py` | [SOLID and layering](/concepts/architecture.md) |
| `pytest tests/test_candidate_rubric.py` | Determinism, clamping, scorecard integrity, prompt byte-stability |
| `pytest tests/test_session.py` | The live text session — contract-verbatim prompt, transcript ordering, session SQL, and the session endpoints under `TestClient`. Offline: a fake `ChatModel`, an in-memory database |
| `pytest tests/test_voice.py` | The voice session on **both** providers — deterministic voice/speed/eagerness/VAD, prompt and opening-line verbatimness, dispatch by provider, the never-leak-the-prompt guarantee (including `client_config`), and the voice endpoints. Offline: a fake `RealtimeBroker` per provider |
| `pytest tests/test_recording.py` | [Session recording](/concepts/contracts/session-recording.md) — chunk ordering, finalize idempotency, the modality gate, and the recording endpoints, including a `video/webm` recording served `inline` with its own mime, a `Range` request answered 206, and analyse being handed the spool path rather than a scratch copy. Offline: `recordings_dir=tmp_path`, no real audio |
| `pytest tests/test_engine_ingest.py` | [Session ingest](/concepts/contracts/session-ingest.md) — the bearer gate on both engine routes (401 wrong, 503 unset), first delivery creating a voice session from the engine's turn table, a repeat replacing rather than appending, landing on the session the portal opened, and the 409/404/422 refusals. Offline: `:memory:`, no model |
| `pytest tests/test_portal_compat.py` | The three additions the SkillBrew portal needs — the [error envelope](/concepts/contracts/rest-api.md) beside an unchanged `detail`, the [multipart chunk door](/concepts/contracts/session-recording.md) against the raw one, and that `CORS_ALLOWED_ORIGINS` decides whether any CORS header exists. Offline: `TestClient`, `:memory:`, no model |
| `pytest tests/test_migrations.py` | The [Postgres schema and migration runner](/concepts/contracts/database-schema.md) — apply (four versions), `--check`'s three exit codes, drift, a failed migration recording nothing, the advisory lock, the foreign-key decisions (`sessions.candidate_id` absent, `sessions.participant_id` real), and that the two dropped tables are not created anywhere. **Needs a database**; see the block below |
| `pytest tests/test_object_store.py` | The [object store port](/concepts/contracts/storage-ports.md) — one behavioural set over **both** adapters: round trip, the five range cases, a missing key, the content-type round trip, the prefix in the real key, and a 9 MiB object whose ETag proves the multipart path. **Needs MinIO**; see the block below |
| `pytest tests/test_key_failover.py` | The [second-key failover](/concepts/subsystems/llm-port.md#two-gemini-keys-one-silent-failover-2026-09-01) — which errors are key-shaped and which are not, that a rate-limited primary falls over and a malformed request does not, that stickiness survives a rebuild, and that a single key builds no wrapper. Offline: counting fakes, no key |
| `pytest tests/test_trait_dimensions.py` | Composing a persona from presets is held to a hand-written archetype's guarantees — [Test suite](/concepts/subsystems/test-suite.md) |
| `pytest tests/test_custom_persona_integration.py` | A composed persona enacts as composed, against an adversarial fake model that violates every constraint |
| `pytest tests/test_control_plane_candidates_api.py` | The enrollment routes under `TestClient`: trait dimensions, custom personas, idempotent re-submission, 422 on a bad preset, and that both cast paths hand the agent the same job spec and the same enabled expectation items |
| `pytest tests/test_expectations.py` | [The expectation checklist](/concepts/modules/evaluation-agent-expectations.md) — the agent's four clamps, the classify fallback, **the pinned fixed ids** (a reworded `covers` string fails here), what `POST /interviews` **and `PATCH /interviews/{id}`** accept and reject (including the explicit-`null` case that would otherwise be a 500, and the partial-list pin that says why a client sends the whole checklist), the re-keyed `report_sections`, and that the two retired routes are 404. Offline: a scripted fake model, `:memory:` |
| `pytest tests/test_links_participants.py` | [Links and participants](/concepts/contracts/links-and-participants.md) — mint/read/revoke, 404 vs 410, the public body carrying neither the JD nor a persona, the constant-time compare, the shared-secret gate (and its 503 when unset), the token path through `POST /sessions`, email normalisation into one row, `user_id` attaching and never clearing, and cross-interview history with and without a stored report. Offline: `:memory:`, a fake casting model |
| `pytest tests/test_model_error_surfacing.py` | A provider failure on the casting and expectation endpoints is a clean 502, never a raw 500 |
| `pytest tests/test_report_engine.py` | The [report engine](/concepts/subsystems/report-engine.md) without a judge — signals, scoring, segments, and byte-identical output for the same bundle |
| `pytest tests/test_full_interview_pipeline_integration.py` | The whole manager-facing flow over HTTP, offline, across a spread of personas: create → cast → scorecard → session → end → re-read |
| gofmt / go vet / go build / `go test -race` / go architecture / golangci-lint | The [live-session engine](/concepts/subsystems/engine.md) in `engine/`. Every gate runs **from inside the module** — a repo-root `go vet ./...` finds no packages. Race detector always on |
| `pytest tests/test_report_judge.py` | The [judge veto](/concepts/determinism.md) — verbatim spans, who spoke, no numbers in prose, and that a rejected claim leaves the composed sentence standing. Offline: `judge.overlay` driven with hand-written model output |
| `pytest tests/test_analysis_agent.py` | The [analysis harness](/concepts/subsystems/analysis-agent.md) — window timestamps, anchor rejection, the 60/40 weighting, and `duration_ms` against a real video-plus-audio WebM. Offline, but that last test **skips when `ffmpeg`/`ffprobe` are not on PATH** — the one gate in this table that can quietly cover less than it looks like it does |
| `export_schemas.py --check` | `owner_handover/` matches the Pydantic models |
| Live scenarios | Only with `--live` — Python model scenarios plus the engine's `//go:build live` vendor tests. The Go live tests read credentials through `internal/config`, not `os.Getenv`, because the layering gate allows only that package to read the environment — which also means they exercise the same configuration path production does. The Gemini tests need `GEMINI_API_KEY` + `SPEAKER_MODEL_ID`; the OpenAI transcription test needs `OPENAI_API_KEY` + `ASR_MODEL_ID` (e.g. `gpt-4o-mini-transcribe`) and skips otherwise |

## The Postgres + MinIO block

The database-backed suites need a real server, and the object-store suite needs
a real S3-compatible one. `check.sh` brings both up **once** for the whole gate
run, through `python -m tests.infra up all`, and tears them down with a `trap`
on EXIT — provisioning costs seconds and this gate runs one pytest session per
suite line, so a container per session would dominate the run. (It asked for
`postgres` alone until 2026-09-10; `tests/test_object_store.py` is what widened
it. Narrow it again only if every suite that needs one of them goes away.)

`tests/infra.py` uses `TEST_DATABASE_URL` and `TEST_S3_*` if they are set and
otherwise starts throwaway `postgres:16-alpine` and `minio` containers with
**Apple `container`**. Docker is not installed in this project and is not used;
`docker.io/...` in the image names is a registry hostname, not a runtime. The
runtime is not started automatically — `container system start` has a one-time
kernel download behind it.

**Containers are reached on their own IP, not a published host port.** Apple
`container` 1.2.0 accepts `-p 127.0.0.1:<host>:<guest>` and even binds a
listener that completes a TCP handshake, but the forwarded connection is
dropped the moment a real protocol exchange starts. Measured on 2026-09-10:
`nc` reported the host port open while `psycopg` on that same port failed with
"server closed the connection unexpectedly", and the container's own log said
`database system is ready to accept connections` — the server was fine, the
forwarder was not. `infra.py` therefore publishes no ports at all and reads
`.status.networks[0].ipv4Address` from `container inspect`, which also removes
the free-port race that publishing needed. A host-port binding that handshakes
and then fails is worse than one that refuses outright: it makes a readiness
probe that only opens a socket report success.

**Unavailable infrastructure is `missing`, not `skip`**: the block prints
**NOT RUN** and fails the gate unless `ALLOW_MISSING_TOOLS=1`. Both ways to make
it run:

```bash
container system start                                   # once per machine
container system kernel set --recommended                 # once; see the note below
# or point the gate at servers you already run — the same override path, no
# code difference. A Homebrew postgres and a Homebrew minio are enough:
export TEST_DATABASE_URL='postgresql:///postgres?host=/tmp&user=<you>'
export TEST_S3_ENDPOINT=http://127.0.0.1:9000 TEST_S3_ACCESS_KEY=... TEST_S3_SECRET_KEY=...
scripts/check.sh
```

The object-store suite does **not** fall back to a stub when MinIO is missing:
its fixture raises, every S3 case ERRORs, and the run is red. A storage adapter
checked against a fake only proves the fake matches the fake.

### A gate that did not run must never read as one that did

`check.sh` distinguishes two things that used to be the same call. **SKIP** is a
gate deliberately not requested — `--live`, which costs money. **NOT RUN** is a
gate whose tooling is absent, and it *fails the script*.

The distinction was bought the hard way: `golangci-lint` was never installed, so
the lint gate had never executed once in the module's life while the script
still printed "All checks passed". `unused`, `gosec` and `revive` were silently
inactive throughout. Set `ALLOW_MISSING_TOOLS=1` to accept the gap deliberately;
do not make it the default.

Install what the Go gates need with `brew install golangci-lint`.

## Live scenarios

```bash
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
.venv/bin/python tests/test_gemini_live_mint.py    # Live-API mint smoke test
```

Run these after changing a prompt, a guardrail, or a schema the model
fills. (`tests/test_expectation_agent.py` was the third line here until
2026-09-13; it went with the package.) The offline suite cannot catch a model that started dropping skills or
drifting outside its band — that is exactly what these assert.

The third is not a scenario: it mints one ephemeral Gemini Live token and checks
the vendor still accepts a whole `LiveConnectConfig` inside
`live_connect_constraints` on the configured model id. Run it after changing
`VOICE_MODEL`, the sealed session config, or the pinned `google-genai`. It skips
cleanly without `GEMINI_API_KEY`. Nothing is spoken; the offline suite already
covers everything decided before the vendor is involved.

## When a check fails

* **`export_schemas.py --check`** — you changed a public Pydantic model. Run it without `--check` and commit the regenerated files.
* **`test_system_prompt_is_byte_stable`** — you changed the compiled persona prompt. Intended? Bump `ENGINE_CONTRACT_VERSION` and update the expectation. Unintended? Revert.
* **A layering or DIP test** — the message names the file and the offending import. Do not add an exception; move the code.
* **`test_ocp_*`** — an agent grew a dependency on a specific archetype or provider. Push the special case back into the catalog or factory.
* **`go architecture`** — the engine's layering rule broke: a package outside `cmd/engined` imported a vendor, transport or store adapter, `os.Getenv` escaped `internal/config`, a model id was hardcoded, or `internal/session` called `time.Now` instead of the injected `Clock`. Move the code; do not add an exception.
