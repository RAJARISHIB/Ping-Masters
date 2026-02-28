#!/usr/bin/env bash

# One-command local setup and startup for Ping Masters (macOS/Linux).
# - Creates Python virtual environment (.venv) if missing
# - Installs backend dependencies
# - Installs frontend dependencies
# - Starts backend and frontend together

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
BACKEND_DIR="${REPO_ROOT}/backend"
UI_DIR="${REPO_ROOT}/ping_masters_ui"
VENV_DIR="${REPO_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

SKIP_INSTALL="false"
for arg in "$@"; do
  case "${arg}" in
    --skip-install)
      SKIP_INSTALL="true"
      ;;
    *)
      echo "Unknown argument: ${arg}"
      echo "Usage: bash ./setup_and_run.sh [--skip-install]"
      exit 1
      ;;
  esac
done

BACKEND_PID=""
FRONTEND_PID=""

log_step() {
  printf '==> %s\n' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Error: required command "%s" not found in PATH.\n' "$1" >&2
    exit 1
  fi
}

cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

require_command npm

if [[ "${SKIP_INSTALL}" != "true" ]]; then
  log_step "Preparing Python environment"
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    if command -v python3 >/dev/null 2>&1; then
      python3 -m venv "${VENV_DIR}"
    elif command -v python >/dev/null 2>&1; then
      python -m venv "${VENV_DIR}"
    else
      echo "Error: Python 3.10+ was not found. Install Python and rerun." >&2
      exit 1
    fi
  fi

  log_step "Installing backend dependencies"
  "${VENV_PYTHON}" -m pip install --upgrade pip
  "${VENV_PYTHON}" -m pip install -r "${BACKEND_DIR}/requirement.txt"

  log_step "Installing frontend dependencies"
  (
    cd "${UI_DIR}"
    npm install
  )
else
  log_step "Skip install enabled: dependency installation skipped"
fi

log_step "Starting backend server"
(
  cd "${BACKEND_DIR}"
  "${VENV_PYTHON}" ./main.py
) &
BACKEND_PID="$!"

log_step "Starting frontend server"
(
  cd "${UI_DIR}"
  npm start
) &
FRONTEND_PID="$!"

echo
echo "Ping Masters startup initiated."
echo "Backend:  http://127.0.0.1:8000/docs"
echo "Frontend: http://localhost:4200"
echo
echo "Press Ctrl+C to stop both services."

while true; do
  if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    echo "Backend process exited. Stopping frontend."
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    echo "Frontend process exited. Stopping backend."
    exit 1
  fi
  sleep 2
done
