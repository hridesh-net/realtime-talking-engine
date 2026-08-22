---
type: Runbook
title: Checks
description: One command for every standard — what each check enforces and when to run the live ones.
resource: /scripts/check.sh
tags: [runbook, ci, lint, tests]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /scripts/check.sh
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
| `mypy` | `disallow_untyped_defs`, no implicit Optional, pydantic plugin, over all four packages |
| `pytest tests/test_architecture.py` | [SOLID and layering](/concepts/architecture.md) |
| `pytest tests/test_candidate_rubric.py` | Determinism, clamping, scorecard integrity, prompt byte-stability |
| `pytest tests/test_session.py` | The live text session — contract-verbatim prompt, transcript ordering, session SQL, and the session endpoints under `TestClient`. Offline: a fake `ChatModel`, an in-memory database |
| `pytest tests/test_voice.py` | The voice session — deterministic voice/speed/eagerness, prompt verbatimness, the never-leak-the-prompt guarantee, and the voice endpoints. Offline: a fake `RealtimeBroker` |
| gofmt / go vet / go build / `go test -race` / go architecture / golangci-lint | The [live-session engine](/concepts/subsystems/engine.md) in `engine/`. Every gate runs **from inside the module** — a repo-root `go vet ./...` finds no packages. Race detector always on. Activates when `engine/go.mod` exists; `golangci-lint` skips with a hint when not installed |
| `export_schemas.py --check` | `owner_handover/` matches the Pydantic models |
| Live scenarios | Only with `--live` — Python model scenarios plus the engine's `//go:build live` vendor tests |

## Live scenarios

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

Run these after changing a prompt, a guardrail, or a schema the model fills.
The offline suite cannot catch a model that started dropping skills or drifting
outside its band — that is exactly what these assert.

## When a check fails

* **`export_schemas.py --check`** — you changed a public Pydantic model. Run it without `--check` and commit the regenerated files.
* **`test_system_prompt_is_byte_stable`** — you changed the compiled persona prompt. Intended? Bump `ENGINE_CONTRACT_VERSION` and update the expectation. Unintended? Revert.
* **A layering or DIP test** — the message names the file and the offending import. Do not add an exception; move the code.
* **`test_ocp_*`** — an agent grew a dependency on a specific archetype or provider. Push the special case back into the catalog or factory.
* **`go architecture`** — the engine's layering rule broke: a package outside `cmd/engined` imported a vendor, transport or store adapter, `os.Getenv` escaped `internal/config`, a model id was hardcoded, or `internal/session` called `time.Now` instead of the injected `Clock`. Move the code; do not add an exception.
