#!/usr/bin/env bash
# Portable .env read/write helpers.

set_env_var() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp found=0

  tmp="$(mktemp "${env_file}.XXXXXX")"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" =~ ^${key}= ]]; then
      printf '%s=%s\n' "${key}" "${value}" >>"${tmp}"
      found=1
    else
      printf '%s\n' "${line}" >>"${tmp}"
    fi
  done <"${env_file}"

  if [[ "${found}" -eq 0 ]]; then
    printf '%s=%s\n' "${key}" "${value}" >>"${tmp}"
  fi

  mv "${tmp}" "${env_file}"
}

set_env_vars() {
  local env_file="$1"
  shift
  local pair key value
  for pair in "$@"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    set_env_var "${env_file}" "${key}" "${value}"
  done
}

env_value_or_default() {
  local file="$1"
  local key="$2"
  local default_value="$3"
  local value

  value="$(read_env_value "${file}" "${key}")"
  if [[ -z "${value}" ]]; then
    printf '%s' "${default_value}"
  else
    printf '%s' "${value}"
  fi
}

to_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_placeholder_value() {
  local value="$1"
  shift
  local placeholder

  [[ -z "${value}" ]] && return 0
  for placeholder in "$@"; do
    [[ -n "${placeholder}" && "${value}" == "${placeholder}" ]] && return 0
  done
  return 1
}
