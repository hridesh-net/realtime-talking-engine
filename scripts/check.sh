#!/usr/bin/env bash
# Every standards check in one command. CI runs this; run it before pushing.
#
#   scripts/check.sh          # everything that does not call a model
#   scripts/check.sh --live   # also run the scenario tests (needs an API key, costs money)
#
# Each check prints PASS/FAIL and the script exits non-zero if any failed, so a
# single failure does not hide the rest.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

FAILED=()
run() {
    local name=$1
    shift
    printf '\n\033[1m▶ %s\033[0m\n' "$name"
    if "$@"; then
        printf '\033[32m  PASS\033[0m  %s\n' "$name"
    else
        printf '\033[31m  FAIL\033[0m  %s\n' "$name"
        FAILED+=("$name")
    fi
}

skip() { printf '\n\033[1m▶ %s\033[0m\n\033[33m  SKIP\033[0m  %s\n' "$1" "$2"; }

# missing is for a gate that could not run because its tooling is absent, as
# opposed to skip, which is for a gate deliberately not requested (--live).
# The two were the same call once, and the consequence was that a machine
# without golangci-lint ran no linter at all and still printed "All checks
# passed" — unused-code, gosec and revive were silently inactive for the whole
# life of the module. A gate that did not run must never read as one that did.
NOT_RUN=()
missing() {
    printf '\n\033[1m▶ %s\033[0m\n\033[31m  NOT RUN\033[0m  %s\n' "$1" "$2"
    NOT_RUN+=("$1 — $2")
}

if [[ ! -x "$PY" ]]; then
    echo "No virtualenv at $PY — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# ---------------------------------------------------------------- python ----
run "python lint (ruff)"            $PY -m ruff check .
run "python format (ruff format)"   $PY -m ruff format --check .
run "python types (mypy)"           $PY -m mypy
run "SOLID + layering"              $PY -m pytest tests/test_architecture.py -q
run "persona rubric (offline)"      $PY -m pytest tests/test_candidate_rubric.py -q
run "live session (offline)"        $PY -m pytest tests/test_session.py -q
run "voice session (offline)"       $PY -m pytest tests/test_voice.py -q
run "session recording (offline)"   $PY -m pytest tests/test_recording.py -q
run "trait composition (offline)"   $PY -m pytest tests/test_trait_dimensions.py -q
run "custom personas (offline)"     $PY -m pytest tests/test_custom_persona_integration.py -q
run "candidates API (offline)"      $PY -m pytest tests/test_control_plane_candidates_api.py -q
run "provider errors (offline)"     $PY -m pytest tests/test_model_error_surfacing.py -q
run "key failover (offline)"        $PY -m pytest tests/test_key_failover.py -q
run "analysis agent (offline)"     $PY -m pytest tests/test_analysis_agent.py -q
run "report engine (offline)"      $PY -m pytest tests/test_report_engine.py -q
run "report judge (offline)"       $PY -m pytest tests/test_report_judge.py -q
run "full pipeline (offline)"       $PY -m pytest tests/test_full_interview_pipeline_integration.py -q

# -------------------------------------------------------------------- go ----
# The live-session engine is a Go module rooted at engine/, so every gate runs
# from inside that module — a repo-root `go vet ./...` finds no packages.
# The race detector is always on: this codebase is all concurrency, and a data
# race that only shows up under load is exactly what these gates exist to catch.
if [[ -f engine/go.mod ]]; then
    if command -v go >/dev/null 2>&1; then
        run "go format (gofmt)" bash -c '[[ -z "$(gofmt -l engine)" ]] || { gofmt -l engine; false; }'
        run "go vet"            bash -c 'cd engine && go vet ./...'
        run "go build"          bash -c 'cd engine && go build ./...'
        run "go tests (-race)"  bash -c 'cd engine && go test -race ./...'
        # Layering gate. Guard on a test file, not the directory: the package
        # exists from the skeleton onward, and `go test` on a package with no
        # tests exits 0 — which would report a PASS for a check that never ran.
        if compgen -G "engine/internal/arch/*_test.go" >/dev/null 2>&1; then
            run "go architecture" bash -c 'cd engine && go test ./internal/arch'
        else
            skip "go architecture" "internal/arch has no test yet (phase 0 task 7)"
        fi
        if command -v golangci-lint >/dev/null 2>&1; then
            run "go lint (golangci-lint)" \
                bash -c 'cd engine && golangci-lint run --config ../.golangci.yml'
        else
            missing "go lint (golangci-lint)" "not installed (brew install golangci-lint)"
        fi
    else
        missing "go checks" "go toolchain not installed"
    fi
else
    skip "go checks" "no engine/go.mod yet — standard recorded in .golangci.yml"
fi

# ---------------------------------------------------------------- schemas ----
run "handover schemas match the code" $PY scripts/export_schemas.py --check

# ------------------------------------------------------------------- live ----
if (( LIVE )); then
    run "expectation scenarios (live)" $PY tests/test_expectation_agent.py
    run "candidate scenarios (live)"   $PY tests/test_candidate_agent.py
    # Not a scenario — a smoke test that the Live API still accepts the sealed
    # session config on the configured model id. Cheap, and the offline suite
    # cannot see it.
    run "gemini live mint (live)"      $PY tests/test_gemini_live_mint.py
    # Same convention on the Go side: vendor calls cost money, so they sit
    # behind a build tag and never run in the default offline gate.
    if [[ -f engine/go.mod ]] && command -v go >/dev/null 2>&1; then
        run "engine vendor scenarios (live)" \
            bash -c 'cd engine && go test -tags live ./...'
    fi
else
    skip "live model scenarios" "pass --live to run (calls the model, costs money)"
fi

# ----------------------------------------------------------------- result ----
echo
if (( ${#FAILED[@]} )); then
    printf '\033[31m%d check(s) failed:\033[0m\n' "${#FAILED[@]}"
    printf '  - %s\n' "${FAILED[@]}"
    exit 1
fi
if (( ${#NOT_RUN[@]} )); then
    printf '\033[31m%d gate(s) could not run:\033[0m\n' "${#NOT_RUN[@]}"
    printf '  - %s\n' "${NOT_RUN[@]}"
    printf 'Install the missing tooling, or set ALLOW_MISSING_TOOLS=1 to accept the gap.\n'
    [[ "${ALLOW_MISSING_TOOLS:-0}" == "1" ]] || exit 1
fi
printf '\033[32mAll checks passed.\033[0m\n'
