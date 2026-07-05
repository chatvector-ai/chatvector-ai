#!/usr/bin/env bash
# Shared helpers for local development scripts.

set -euo pipefail

# Resolve repository root regardless of caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BACKEND_ENV="${REPO_ROOT}/backend/.env"
BACKEND_ENV_EXAMPLE="${REPO_ROOT}/backend/.env.example"
FRONTEND_DIR="${REPO_ROOT}/frontend-demo"
FRONTEND_ENV="${FRONTEND_DIR}/.env.local"
FRONTEND_PID_FILE="${REPO_ROOT}/.chatvector-dev-frontend.pid"

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  DOCKER_COMPOSE=(docker compose)
fi

BACKEND_SERVICES=(db redis api)

LEGACY_FIXED_CONTAINER_NAMES=(chatvector-db chatvector-redis chatvector-api chatvector-tests)

read_env_value() {
  local file="$1"
  local key="$2"
  local line value

  line="$(grep -E "^${key}=" "${file}" 2>/dev/null | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 0
  fi
  value="${line#*=}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value}"
}

# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"
# shellcheck source=providers.sh
source "${SCRIPT_DIR}/providers.sh"

docker_compose() {
  (cd "${REPO_ROOT}" && "${DOCKER_COMPOSE[@]}" "$@")
}

legacy_fixed_name_containers() {
  local name state
  for name in "${LEGACY_FIXED_CONTAINER_NAMES[@]}"; do
    if docker container inspect "${name}" >/dev/null 2>&1; then
      state="$(docker container inspect -f '{{.State.Running}}' "${name}" 2>/dev/null || echo false)"
      if [[ "${state}" == "true" ]]; then
        printf '%s\n' "${name}"
      fi
    fi
  done
}

print_legacy_fixed_name_container_error() {
  local names=()
  local name

  while IFS= read -r name; do
    [[ -n "${name}" ]] && names+=("${name}")
  done < <(legacy_fixed_name_containers)

  [[ ${#names[@]} -gt 0 ]] || return 1

  echo "Error: Legacy fixed-name Docker containers from an older checkout are still present:" >&2
  for name in "${names[@]}"; do
    echo "  ${name}" >&2
  done
  echo "" >&2
  echo "Older docker-compose.yml files used global container_name values. They occupy" >&2
  echo "host ports 5432, 6379, and 8000 and can block other local checkouts and worktrees." >&2
  echo "" >&2
  echo "Stop them from the original checkout with:" >&2
  echo "  make stop" >&2
  echo "" >&2
  echo "If make stop does not remove them, delete the legacy containers once:" >&2
  echo "  docker rm -f ${names[*]}" >&2
  return 0
}

diagnose_docker_compose_startup_failure() {
  local output="$1"

  if print_legacy_fixed_name_container_error; then
    return 0
  fi

  if grep -qiE 'port is already allocated|address already in use' <<<"${output}"; then
    echo "Error: A host port required by docker-compose.yml is already in use." >&2
    echo "Another ChatVector checkout or local service may already be using 5432, 6379, or 8000." >&2
    echo "Stop the other stack from that checkout with: make stop" >&2
    return 0
  fi

  if grep -qiE 'container name .* is already in use|Conflict.*container name' <<<"${output}"; then
    print_legacy_fixed_name_container_error || true
    return 0
  fi

  echo "Error: Failed to start backend Docker stack." >&2
}

check_docker_compose_startup_blockers() {
  if print_legacy_fixed_name_container_error; then
    return 1
  fi
  return 0
}

docker_compose_backend_up() {
  local output=""

  if ! check_docker_compose_startup_blockers; then
    return 1
  fi

  if output="$(docker_compose up -d "${BACKEND_SERVICES[@]}" 2>&1)"; then
    printf '%s\n' "${output}"
    return 0
  fi

  diagnose_docker_compose_startup_failure "${output}"
  printf '%s\n' "${output}" >&2
  return 1
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Error: '${name}' is required but was not found in PATH." >&2
    echo "Install it and rerun setup." >&2
    exit 1
  fi
}

check_prerequisites() {
  require_command docker
  require_command curl
  require_command node
  require_command npm
  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    echo "Error: Docker Compose is required (use 'docker compose' or 'docker-compose')." >&2
    exit 1
  fi
}

check_docker_daemon() {
  if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is installed but the daemon is not running or not accessible." >&2
    echo "Start Docker Desktop (or your Docker service) and try again." >&2
    exit 1
  fi
}

is_repo_frontend_pid() {
  local pid="$1"
  local cmd="" cwd="" file_repo="" file_frontend="" file_pid=""

  if ! kill -0 "${pid}" 2>/dev/null; then
    return 1
  fi

  if [[ -f "${FRONTEND_PID_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${FRONTEND_PID_FILE}" 2>/dev/null || true
    if [[ -n "${repo_root:-}" && "${repo_root}" != "${REPO_ROOT}" ]]; then
      return 1
    fi
    if [[ -n "${frontend_dir:-}" && "${frontend_dir}" != "${FRONTEND_DIR}" ]]; then
      return 1
    fi
    file_pid="${pid:-}"
    if [[ -n "${file_pid}" && "${file_pid}" != "$1" ]]; then
      return 1
    fi
  fi

  cmd="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  [[ "${cmd}" == *"next dev"* ]] || return 1
  [[ "${cmd}" == *"${FRONTEND_DIR}"* || "${cmd}" == *"frontend-demo"* ]] || return 1

  if cwd="$(lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | grep '^n' | head -n1 | cut -c2-)"; then
    [[ "${cwd}" == "${FRONTEND_DIR}" || "${cwd}" == "${FRONTEND_DIR}/"* ]] || return 1
  elif cwd="$(ps -p "${pid}" -o cwd= 2>/dev/null | sed 's/^[[:space:]]*//')"; then
    [[ "${cwd}" == "${FRONTEND_DIR}" || "${cwd}" == "${FRONTEND_DIR}/"* ]] || return 1
  fi

  return 0
}

is_frontend_pid_running() {
  local pid="$1"
  is_repo_frontend_pid "${pid}"
}

write_frontend_pid() {
  local pid="$1"
  cat >"${FRONTEND_PID_FILE}" <<EOF
pid=${pid}
repo_root=${REPO_ROOT}
frontend_dir=${FRONTEND_DIR}
EOF
}

read_frontend_pid() {
  local pid_value=""

  if [[ ! -f "${FRONTEND_PID_FILE}" ]]; then
    return 1
  fi

  # shellcheck disable=SC1090
  source "${FRONTEND_PID_FILE}" 2>/dev/null || return 1
  pid_value="${pid:-}"
  [[ -n "${pid_value}" ]] || return 1
  printf '%s' "${pid_value}"
}

clear_frontend_pid_file() {
  rm -f "${FRONTEND_PID_FILE}"
}

stop_local_frontend() {
  local pid=""

  if ! pid="$(read_frontend_pid 2>/dev/null)"; then
    return 0
  fi

  if is_repo_frontend_pid "${pid}"; then
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
    echo "Stopped frontend demo (PID ${pid})."
  else
    echo "Removed stale frontend PID file (PID ${pid} is not this repo's Next.js dev server)." >&2
  fi

  clear_frontend_pid_file
}

ensure_frontend_not_running() {
  local pid=""

  if ! pid="$(read_frontend_pid 2>/dev/null)"; then
    return 0
  fi

  if is_frontend_pid_running "${pid}"; then
    echo "Frontend demo is already running (PID ${pid})." >&2
    echo "Stop it with: make stop" >&2
    exit 1
  fi

  clear_frontend_pid_file
}

install_frontend_dependencies() {
  echo "Installing frontend dependencies..."
  (
    cd "${FRONTEND_DIR}"
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
  )
}

prepare_docker_services() {
  echo "Building Docker images (one-time or when Dockerfiles change)..."
  docker_compose build api
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local timeout="${3:-120}"
  local elapsed=0
  local interval=2

  echo "Waiting for ${label} at ${url}..."
  while (( elapsed < timeout )); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo "${label} is ready."
      return 0
    fi
    sleep "${interval}"
    elapsed=$((elapsed + interval))
  done

  echo "Error: ${label} did not become ready within ${timeout}s." >&2
  return 1
}

wait_for_backend() {
  if ! wait_for_http "http://localhost:8000/" "Backend API" "${BACKEND_WAIT_TIMEOUT:-120}"; then
    echo "Check backend logs with: make logs  (or: docker compose logs api)" >&2
    return 1
  fi
}

wait_for_frontend() {
  if ! wait_for_http "http://localhost:3000" "Frontend demo" "${FRONTEND_WAIT_TIMEOUT:-120}"; then
    echo "Check the frontend terminal output for Next.js errors." >&2
    return 1
  fi
}

require_complete_provider_configuration() {
  if [[ ! -f "${BACKEND_ENV}" ]]; then
    echo "backend/.env not found. Run 'make setup' first." >&2
    exit 1
  fi

  if ! is_provider_configuration_complete; then
    echo "Backend provider configuration is incomplete." >&2
    describe_provider_requirements || true
    echo "Complete backend/.env, then run: make" >&2
    exit 1
  fi
}
