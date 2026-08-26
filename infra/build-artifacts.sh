#!/usr/bin/env bash
# Builds the interview-watcher deploy artifact and uploads it to S3.
#
# This exists because infra/terraform/templates/bootstrap.sh.tftpl pulls a
# tarball from s3://<bucket>/artifacts/<project>-latest.tar.gz on every
# instance boot — without this script that key is never produced and the
# instance would come up with nothing to run.
#
# What it does:
#   1. npm ci && npm run build in ui/           -> ui/dist
#   2. Cross-compiles engined for linux/arm64   -> engined
#      (the instance is Graviton/t4g by default; see infra/terraform/variables.tf)
#   3. Packs the Python source packages control_plane/, candidate_agent/,
#      expectation_agent/, evaluation_agent/, report_engine/, llm/ (the same set
#      pyproject.toml's dependency graph pulls in — see CLAUDE.md's
#      "llm ← agents ← control_plane" rule) plus requirements.txt, the UI
#      build (as ui_dist/) and the engined binary into one tarball.
#   4. Uploads it to s3://<bucket>/artifacts/<project>-latest.tar.gz (the
#      fixed key cloud-init always pulls) and a second timestamped copy for
#      history/rollback.
#
# This script is NOT executed as part of writing this Terraform stack — it
# needs a real AWS principal with S3 write access, which the environment
# building this repo's infra explicitly does not have. Run it yourself,
# after `terraform apply`, from a machine with real AWS credentials:
#
#   infra/build-artifacts.sh <bucket-name>
#   # or
#   BUCKET=<bucket-name> infra/build-artifacts.sh
#
# BUCKET can also just be the `s3_bucket_name` Terraform output.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="interview-watcher"

BUCKET="${1:-${BUCKET:-}}"
AWS_REGION="${AWS_REGION:-ap-south-1}"

if [ -z "${BUCKET}" ]; then
  echo "usage: $0 <bucket-name>   (or set BUCKET=<bucket-name>)" >&2
  exit 1
fi

command -v npm >/dev/null 2>&1 || {
  echo "build-artifacts: npm not found — install Node.js to build ui/" >&2
  exit 1
}
command -v go >/dev/null 2>&1 || {
  echo "build-artifacts: go not found — install Go to cross-compile engined" >&2
  exit 1
}
command -v aws >/dev/null 2>&1 || {
  echo "build-artifacts: aws CLI not found — required to upload the artifact" >&2
  exit 1
}

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

echo "build-artifacts: building UI (npm ci && npm run build)"
(
  cd "${REPO_ROOT}/ui"
  npm ci
  npm run build
)

echo "build-artifacts: cross-compiling engined for linux/arm64"
(
  cd "${REPO_ROOT}/engine"
  GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o "${WORKDIR}/engined" ./cmd/engined
)

echo "build-artifacts: assembling artifact"
STAGE="${WORKDIR}/stage"
mkdir -p "${STAGE}"

# Python source the control plane needs at runtime — the same set the
# dependency-direction rule in CLAUDE.md names (llm <- agents <- control_plane).
for pkg in control_plane candidate_agent expectation_agent evaluation_agent report_engine llm; do
  cp -R "${REPO_ROOT}/${pkg}" "${STAGE}/${pkg}"
done
# Compiled caches are machine-specific and just inflate the tarball.
find "${STAGE}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp "${REPO_ROOT}/requirements.txt" "${STAGE}/requirements.txt"

cp -R "${REPO_ROOT}/ui/dist" "${STAGE}/ui_dist"
cp "${WORKDIR}/engined" "${STAGE}/engined"

# The package list above is hand-maintained, and a package missing from it does
# not fail the build -- it fails at *import time on the instance*, which takes
# the whole site down on the next boot. That happened once (report_engine was
# added to control_plane's imports and not to this list), so the staged tree is
# now proven importable before anything is uploaded.
echo "build-artifacts: verifying the staged tree imports"
VENV_PY="${REPO_ROOT}/.venv/bin/python"
if [ -x "${VENV_PY}" ]; then
  (
    cd "${STAGE}"
    PYTHONPATH="${STAGE}" "${VENV_PY}" -c "import control_plane.api" || {
      echo "build-artifacts: the staged tree cannot import control_plane.api." >&2
      echo "A first-party package it needs is missing from the copy list above." >&2
      exit 1
    }
  )
else
  echo "build-artifacts: no ${VENV_PY}, skipping the import check" >&2
fi

TARBALL="${WORKDIR}/${PROJECT}.tar.gz"
# --no-xattrs: without it a tarball built on macOS carries com.apple.provenance
# attributes that GNU tar on the instance cannot read, emitting a warning per
# file. ~130 lines of noise that a real error would hide in.
tar --no-xattrs -czf "${TARBALL}" -C "${STAGE}" . 2>/dev/null ||
  tar -czf "${TARBALL}" -C "${STAGE}" .

LATEST_KEY="artifacts/${PROJECT}-latest.tar.gz"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "nogit")"
HISTORY_KEY="artifacts/${PROJECT}-${TIMESTAMP}-${GIT_SHA}.tar.gz"

echo "build-artifacts: uploading to s3://${BUCKET}/${LATEST_KEY}"
aws s3 cp "${TARBALL}" "s3://${BUCKET}/${LATEST_KEY}" --region "${AWS_REGION}"

echo "build-artifacts: uploading history copy to s3://${BUCKET}/${HISTORY_KEY}"
aws s3 cp "${TARBALL}" "s3://${BUCKET}/${HISTORY_KEY}" --region "${AWS_REGION}"

echo "build-artifacts: done. New instances will pick this up on next boot;"
echo "an already-running instance needs a reboot (or a manual re-run of"
echo "bootstrap.sh) to pull the new artifact — this stack has no in-place"
echo "redeploy mechanism by design (single instance, no orchestrator)."
