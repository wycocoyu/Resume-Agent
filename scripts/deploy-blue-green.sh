#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -x "${REPO_DIR}/venv/bin/python" ]; then
  PY_BIN="${REPO_DIR}/venv/bin/python"
elif [ -x "${REPO_DIR}/.venv/bin/python" ]; then
  PY_BIN="${REPO_DIR}/.venv/bin/python"
else
  PY_BIN="python3"
fi

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 {status|deploy|rollback} [options]" >&2
  exit 2
fi

exec "${PY_BIN}" "${SCRIPT_DIR}/blue_green_deploy.py" "$@"
