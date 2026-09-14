---
type: Runbook
title: Dev setup
description: Virtualenv, dependencies, and every environment variable the service reads.
resource: /README.md
tags: [runbook, setup, env]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-09-10T12:00:00Z"
verified:
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T12:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /README.md
  - resource: /.env.example
  - resource: /pyproject.toml
---
# Dev setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill GEMINI_API_KEY (or OPENAI_API_KEY)
```

Python **>= 3.11**. Runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2`,
`python-dotenv`, `psycopg[binary]`, `psycopg-pool`, `boto3`, `google-genai`,
`openai`. Dev extras: `pytest`, `pytest-asyncio`, `httpx`, `ruff` (plus `mypy`,
used by `check.sh`).

`scripts/check.sh` invokes `.venv/bin/python` directly and fails early if the
virtualenv is missing — keep it at `.venv/`.

## Run

```bash
.venv/bin/python -m control_plane.main        # http://127.0.0.1:8081
cd ui && npm install && npm run dev           # http://localhost:3000
```

The UI proxies `/api` → `127.0.0.1:8081`, so **start the API first**. Note the
service binds `0.0.0.0` while the UI proxy targets `127.0.0.1`.

# Environment

## ffmpeg — required for audio analysis only

`analysis_agent` shells out to `ffprobe` and `ffmpeg`; nothing else in the repo
does. Everything except the **Analyse** action works without them.

```bash
brew install ffmpeg            # macOS
sudo dnf install ffmpeg        # or the distro equivalent
ffmpeg -hide_banner -formats | grep matroska,webm   # the recorder's container
```

## Credentials — at least one required

| Var | Used when |
|---|---|
| `GEMINI_API_KEY` | provider is `gemini` (the default pick) |
| `GEMINI_API_KEY2` | *optional.* A second Gemini key, tried automatically when the first fails for a reason that names the key |
| `OPENAI_API_KEY` | **required for voice mode**, whatever the text provider is |
| `OPENAI_API_KEY` | provider is `openai` |

With no `*_PROVIDER` set, the factory takes the first provider whose key is
present, checking Gemini first.

`GEMINI_API_KEY2` is a **fallback, not a configuration**: it does not make
Gemini available on its own, and setting it changes nothing until the primary
key fails with a 401/403/429, an invalid or expired key, or a quota/rate-limit
error. Then the same call is retried on it, once, and it is preferred for the
rest of the process. Any other failure is not retried. Nothing is visible to the
client; the switch is a server-side warning log. See
[the LLM port](/concepts/subsystems/llm-port.md#two-gemini-keys-one-silent-failover-2026-09-01).

## Provider and model selection

Resolution per role: `<ROLE>_PROVIDER`/`<ROLE>_MODEL` → `LLM_PROVIDER`/`LLM_MODEL`
→ provider default.

| Role prefix | Workload | Call shape |
|---|---|---|
| `EXPECTATIONS` | drafting the per-interview expectation items and filing a manager's own item under a competency (`evaluation_agent/expectations.py`) | two short structured calls per wizard run; a light model is the right choice. Renamed from `EXPECTATION` 2026-09-13 with the agent it belongs to |
| `CANDIDATE` | casting a persona | one structured call per persona |
| `SESSION` | playing the persona in a live interview | one **chat** call per turn |
| `JUDGE` | writing the report's prose from a finished session (`report_engine/judge.py`) | one structured call per report; **blank** means code-composed sentences, no model |
| `ANALYSIS` | listening to the session recording (`analysis_agent/`) | one audio call per window; must resolve to a provider in `AUDIO_PROVIDERS` — **gemini only** today, and the Analyse button is hidden when none is available |
| `ROLE_FACTS` | drafting the role-fact checklist | one structured call per wizard auto-fill |
| `VOICE` | the live **spoken** session | mints a browser credential; realtime-capable providers only |

| Var | Default |
|---|---|
| `EXPECTATIONS_PROVIDER` / `CANDIDATE_PROVIDER` / `SESSION_PROVIDER` / `JUDGE_PROVIDER` / `ROLE_FACTS_PROVIDER` / `ANALYSIS_PROVIDER` | — (auto-detect) |
| `EXPECTATIONS_MODEL` / `CANDIDATE_MODEL` / `SESSION_MODEL` / `JUDGE_MODEL` / `ROLE_FACTS_MODEL` / `ANALYSIS_MODEL` | — |
| `TRANSCRIBE_MODEL` | `gpt-4o-transcribe` — the interviewer's own speech-to-text on the **OpenAI voice path only**; Gemini Live transcribes both sides itself and ignores it |
| `LLM_PROVIDER` / `LLM_MODEL` | — |
| provider default model | `gemini-3.7-flash` / `gpt-4o-mini` |

`SESSION` is the one worth tuning: it is the only role called on every turn, so
it dominates both cost and the pace of a practice interview.

⚠️ **`VOICE` does not fall back to `LLM_PROVIDER`.** This role resolves against
the realtime-capable providers alone (`REALTIME_PROVIDERS`: gemini, openai) and,
left blank, picks the first of those whose key is set — **gemini before
openai** since 2026-09-01. `VOICE_PROVIDER=openai` keeps the WebRTC path.
`VOICE_MODEL` must be a realtime speech model for the chosen provider
(`gemini-3.1-flash-live-preview`; `gpt-realtime-2`, `gpt-realtime-2.1-mini`),
never a text model id; pointing it at one fails at mint time.
`GET /api/v1/voice-capability` reports what the deployment can actually do.
See [Realtime voice](/concepts/contracts/realtime-voice.md).

Model IDs are config, never hardcoded at a call site.

⚠️ `LLM_MODEL` applies **regardless of provider** — setting it while forcing a
different per-role provider sends the wrong model id. Prefer the per-role vars.

## Service

| Var | Default | Meaning |
|---|---|---|
| `CONTROL_PLANE_DB` | `control_plane.db` | SQLite path — **still what the service runs on** |
| `DATABASE_URL` | `postgresql:///interview_watcher` | Postgres DSN. Read by `database.open_pool()` and by the migration runner. Nothing in the request path uses it yet |
| `SPOOL_DIR` | `spool` | Local disk buffer for in-flight session artifacts before upload. Shared with the Go engine, which spools its bundle into the same directory |
| `CONTROL_PLANE_PORT` | `8081` | Bind port |
| `CONTROL_PLANE_SHARED_SECRET` | *(empty)* | Shared with the Go engine, which sends it as a bearer token on `GET /candidates/{id}/engine-contract` and `POST /sessions/{id}/ingest`. Same value in both processes' environments. **Unset, those two routes answer 503** — voice sessions cannot start, by design |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated browser origins allowed to call this API cross-origin. **Empty or unset installs no CORS middleware at all** — the console under `ui/` is same-origin and needs none, and a wildcard would let any page on the internet call this service with the caller's cookies. Set it to the portal's origin to serve it, e.g. `http://localhost:3002`. Whitespace around each entry is trimmed |
| `RECORDINGS_DIR` | `recordings` | Where browser-uploaded voice-session audio lands, one file per session. Local disk on this host only — see [Session recording](/concepts/contracts/session-recording.md) for the consent/retention decisions. Retention is manual; nothing purges it. |
| `OBJECT_STORE_DIR` | `objects` | Root of the filesystem [object store](/concepts/contracts/storage-ports.md) when `S3_BUCKET` is unset. Read by `object_store_from_env()`; **nothing in the request path calls the object store yet** |
| `S3_BUCKET`, `S3_REGION`, `S3_PREFIX`, `S3_ENDPOINT`, `S3_FORCE_PATH_STYLE` | *(empty)* | Selects and configures `S3ObjectStore` (`S3_ENDPOINT` + path style for MinIO). Shared names with the Go engine, which requires bucket and region; the Python side needs only `S3_BUCKET` to pick S3 |

`build_app()` calls `load_dotenv()`, so `.env` is picked up automatically when
running the service. Scripts and tests that build agents directly rely on the
environment already being set.

## The Go engine's variables

Everything under the `Go engine` banner in `.env.example` (`SPEAKER_MODEL_ID`,
`THINKER_MODEL_ID`, the deadlines, the TURN settings, `METRICS_ADDR`, …) is read
**only** by `engine/internal/config` and is documented in the engine page —
[Live-session engine § Configuration](/concepts/subsystems/engine.md#configuration).
Four names are shared with this service and must carry the same value in both
processes' environments: `GEMINI_API_KEY`, `OPENAI_API_KEY`,
`CONTROL_PLANE_SHARED_SECRET` and `SPOOL_DIR` (plus the `S3_*` set once the
object store is wired).

## Postgres — being built beside SQLite

The service still runs on SQLite; the Postgres schema and its migration runner
landed first so the switch can be a separate, reviewable change. Local setup is
one command, because the default DSN is a socket connection as the current user:

```bash
createdb interview_watcher
.venv/bin/python -m control_plane.migrate            # apply pending migrations
.venv/bin/python -m control_plane.migrate --check    # 0 current, 1 pending, 2 drift
```

Schema is **never** applied on startup — that is the habit `init_db` had, and it
is what made a renamed column invisible on an existing database. See
[Database schema](/concepts/contracts/database-schema.md) for the type mapping,
the foreign key that is deliberately absent, and why there are no
down-migrations.

## Test infrastructure

`TEST_DATABASE_URL`, `TEST_S3_ENDPOINT`, `TEST_S3_ACCESS_KEY`,
`TEST_S3_SECRET_KEY` — leave them blank and the suite provisions throwaway
Postgres and MinIO containers with **Apple `container`**; set them and it uses
what you point at and provisions nothing.

```bash
container system start        # once per machine; installs a kernel on first run
container system status       # what tests/infra.py checks before provisioning
```

Docker is not installed and is not used here. `docker.io/...` in the image names
is a registry hostname, not a runtime. If the runtime is unavailable and nothing
is configured, `scripts/check.sh` reports the database gates as **NOT RUN** and
fails — see [Checks](/concepts/runbooks/checks.md).

## Secrets hygiene

`.gitignore` covers `.env`, `.env.*` (keeping `.env.example`), `*.db`,
`recordings/` (`RECORDINGS_DIR`'s default, regenerated by live voice sessions),
and `node_modules/`. The `owner_handover/` and `docs/` rules that used to hide
the deliverables were removed on 2026-08-22.
