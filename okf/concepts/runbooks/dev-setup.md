---
type: Runbook
title: Dev setup
description: Virtualenv, dependencies, and every environment variable the service reads.
resource: /README.md
tags: [runbook, setup, env]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
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
`python-dotenv`, `google-genai`, `openai`. Dev extras: `pytest`,
`pytest-asyncio`, `httpx`, `ruff` (plus `mypy`, used by `check.sh`).

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

## Credentials — at least one required

| Var | Used when |
|---|---|
| `GEMINI_API_KEY` | provider is `gemini` (the default pick) |
| `OPENAI_API_KEY` | provider is `openai` |

With no `*_PROVIDER` set, the factory takes the first provider whose key is
present, checking Gemini first.

## Provider and model selection

Resolution per role: `<ROLE>_PROVIDER`/`<ROLE>_MODEL` → `LLM_PROVIDER`/`LLM_MODEL`
→ provider default. Roles: `EXPECTATION`, `CANDIDATE`.

| Var | Default |
|---|---|
| `EXPECTATION_PROVIDER` / `CANDIDATE_PROVIDER` | — (auto-detect) |
| `EXPECTATION_MODEL` / `CANDIDATE_MODEL` | — |
| `LLM_PROVIDER` / `LLM_MODEL` | — |
| provider default model | `gemini-2.5-flash` / `gpt-4o-mini` |

Model IDs are config, never hardcoded at a call site.

⚠️ `LLM_MODEL` applies **regardless of provider** — setting it while forcing a
different per-role provider sends the wrong model id. Prefer the per-role vars.

## Service

| Var | Default | Meaning |
|---|---|---|
| `CONTROL_PLANE_DB` | `control_plane.db` | SQLite path |
| `CONTROL_PLANE_PORT` | `8081` | Bind port |

`build_app()` calls `load_dotenv()`, so `.env` is picked up automatically when
running the service. Scripts and tests that build agents directly rely on the
environment already being set.

## Secrets hygiene

`.gitignore` covers `.env`, `.env.*` (keeping `.env.example`), `*.db`, and
`node_modules/`. ⚠️ It **also** ignores `owner_handover/` and `docs/`, which is a
bug — see [Owner handover](/concepts/subsystems/owner-handover.md).
