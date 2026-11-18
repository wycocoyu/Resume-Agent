#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Ensure nvm-managed node/npm/pm2 binaries are reachable in non-interactive shells
if ! command -v pm2 >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  for nvm_bin in /www/server/nvm/versions/node/*/bin "$HOME"/.nvm/versions/node/*/bin; do
    if [ -d "${nvm_bin}" ]; then
      PATH="${nvm_bin}:${PATH}"
    fi
  done
  export PATH
fi

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
