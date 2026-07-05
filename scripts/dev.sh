#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPTS_DIR}/lib/common.sh"

OPEN_BROWSER="${OPEN_BROWSER:-0}"

LOGS_PID=""
FRONTEND_PID=""
STARTED_BACKEND=0

stop_log_follower() {
  if [[ -n "${LOGS_PID}" ]] && kill -0 "${LOGS_PID}" 2>/dev/null; then
    kill "${LOGS_PID}" 2>/dev/null || true
    wait "${LOGS_PID}" 2>/dev/null || true
  fi
  LOGS_PID=""
}

stop_frontend_process() {
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
  FRONTEND_PID=""
  clear_frontend_pid_file
}

cleanup() {
  local exit_code=$?
  stop_log_follower
  stop_frontend_process

  if [[ "${STARTED_BACKEND}" -eq 1 ]]; then
    echo ""
    echo "Frontend stopped. Backend Docker services are still running."
    echo "Stop them with: make stop"
  fi

  exit "${exit_code}"
}

start_backend() {
  echo "Starting backend Docker stack..."
  if ! docker_compose_backend_up; then
    echo "Error: Failed to start backend Docker stack." >&2
    exit 1
  fi
  STARTED_BACKEND=1

  docker_compose logs -f api &
  LOGS_PID=$!
}

start_frontend() {
  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "Frontend dependencies are missing. Run 'make setup' first." >&2
    exit 1
  fi

  ensure_frontend_not_running

  if ! require_frontend_port_available; then
    exit 1
  fi

  echo "Starting frontend demo (Next.js) on port ${FRONTEND_PORT}..."
  (
    cd "${FRONTEND_DIR}"
    exec npm run dev
  ) &
  FRONTEND_PID=$!
  write_frontend_pid "${FRONTEND_PID}"
}

main() {
  trap cleanup EXIT INT TERM

  check_prerequisites
  check_docker_daemon
  require_complete_provider_configuration

  start_backend

  if ! wait_for_backend; then
    exit 1
  fi

  if ! verify_ollama_docker_connectivity; then
    exit 1
  fi

  start_frontend

  if ! wait_for_frontend "${FRONTEND_PID}"; then
    echo "Error: Frontend demo failed to become ready." >&2
    exit 1
  fi

  if [[ "${OPEN_BROWSER}" == "1" ]]; then
    "${SCRIPTS_DIR}/open-dev.sh" || true
  fi

  echo ""
  echo "Development environment running."
  echo "  Frontend : ${FRONTEND_DEV_URL}"
  echo "  API docs : http://localhost:8000/docs"
  echo "Press Ctrl+C to stop the frontend (backend containers keep running)."
  echo ""

  wait "${FRONTEND_PID}"
}

main "$@"
