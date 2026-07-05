#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

main() {
  require_command node
  require_command npm

  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "Frontend dependencies are missing. Run 'make setup' first." >&2
    exit 1
  fi

  ensure_frontend_not_running
  if ! require_frontend_port_available; then
    exit 1
  fi

  cd "${FRONTEND_DIR}"
  exec npm run dev
}

main "$@"
