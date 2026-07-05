#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

FRONTEND_URL="${FRONTEND_DEV_URL}"
DOCS_URL="http://localhost:8000/docs"

open_with_command() {
  local opener="$1"
  local url="$2"

  if [[ "${opener}" == /* ]] || [[ "${opener}" == ./* ]]; then
    "${opener}" "${url}" >/dev/null 2>&1
    return $?
  fi

  case "${opener}" in
    open)
      open "${url}" >/dev/null 2>&1
      ;;
    xdg-open)
      xdg-open "${url}" >/dev/null 2>&1
      ;;
    cmd)
      cmd.exe /c start "" "${url}" >/dev/null 2>&1
      ;;
    powershell)
      powershell.exe -NoProfile -Command "Start-Process '${url}'" >/dev/null 2>&1
      ;;
    *)
      return 1
      ;;
  esac
}

detect_browser_opener() {
  if [[ -n "${BROWSER:-}" ]]; then
    if [[ "${BROWSER}" == /* && -x "${BROWSER}" ]]; then
      printf '%s' "${BROWSER}"
      return 0
    fi
    if command -v "${BROWSER}" >/dev/null 2>&1; then
      printf '%s' "${BROWSER}"
      return 0
    fi
  fi
  if command -v open >/dev/null 2>&1; then
    printf 'open'
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    printf 'xdg-open'
    return 0
  fi
  if command -v cmd.exe >/dev/null 2>&1; then
    printf 'cmd'
    return 0
  fi
  if command -v powershell.exe >/dev/null 2>&1; then
    printf 'powershell'
    return 0
  fi
  return 1
}

open_url() {
  local opener="$1"
  local url="$2"
  open_with_command "${opener}" "${url}"
}

main() {
  local opener failures=0

  if ! opener="$(detect_browser_opener)"; then
    echo "Could not find a browser-opening command on this system."
    echo "Open these URLs manually:"
    echo "  ${FRONTEND_URL}"
    echo "  ${DOCS_URL}"
    return 0
  fi

  if ! open_url "${opener}" "${FRONTEND_URL}"; then
    failures=$((failures + 1))
  fi
  if ! open_url "${opener}" "${DOCS_URL}"; then
    failures=$((failures + 1))
  fi

  if [[ "${failures}" -gt 0 ]]; then
    echo "Could not open one or more browser tabs automatically."
    echo "Open these URLs manually:"
    echo "  ${FRONTEND_URL}"
    echo "  ${DOCS_URL}"
  else
    echo "Opened browser tabs:"
    echo "  ${FRONTEND_URL}"
    echo "  ${DOCS_URL}"
  fi
}

main "$@"
