#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

main() {
  check_prerequisites
  check_docker_daemon
  exec docker_compose up "${BACKEND_SERVICES[@]}"
}

main "$@"
