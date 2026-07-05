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

normalize_secret_input() {
  local var_name="$1"
  local value="${!var_name}"

  value="${value//$'\r'/}"
  value="${value//$'\n'/}"
  value="${value#export }"
  value="${value#EXPORT }"
  if [[ "${value}" =~ ^GEN_AI_KEY= ]]; then
    value="${value#GEN_AI_KEY=}"
  fi
  if [[ "${value}" =~ ^OPENAI_API_KEY= ]]; then
    value="${value#OPENAI_API_KEY=}"
  fi
  if [[ "${value}" =~ ^ANTHROPIC_API_KEY= ]]; then
    value="${value#ANTHROPIC_API_KEY=}"
  fi
  if [[ "${value}" =~ ^VOYAGE_API_KEY= ]]; then
    value="${value#VOYAGE_API_KEY=}"
  fi
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"

  printf -v "${var_name}" '%s' "${value}"
}

read_line_hidden_from_stdin() {
  local prompt="$1"
  local var_name="$2"
  local input=""

  printf '%s' "${prompt}" >&2
  if stty -echo 2>/dev/null; then
    IFS= read -r input || true
    stty echo 2>/dev/null
  else
    IFS= read -rs input || true
  fi
  printf '\n' >&2
  printf -v "${var_name}" '%s' "${input}"
}

read_line_hidden_from_tty() {
  local prompt="$1"
  local var_name="$2"
  local input=""
  local tty="/dev/tty"

  [[ -r "${tty}" ]] || return 1

  printf '%s' "${prompt}" >"${tty}"
  if stty -echo 2>/dev/null <"${tty}"; then
    IFS= read -r input <"${tty}" || true
    stty echo 2>/dev/null <"${tty}"
  else
    IFS= read -rs input <"${tty}" || true
  fi
  printf '\n' >"${tty}"
  printf -v "${var_name}" '%s' "${input}"
}

prompt_hidden() {
  local prompt="$1"
  local var_name="$2"

  printf -v "${var_name}" ''

  if [[ -r /dev/tty ]]; then
    read_line_hidden_from_tty "${prompt}" "${var_name}" || true
  fi

  if [[ -z "${!var_name}" && -t 0 ]]; then
    read_line_hidden_from_stdin "${prompt}" "${var_name}"
  fi

  normalize_secret_input "${var_name}"
}

prompt_visible() {
  local prompt="$1"
  local var_name="$2"
  local input=""

  if [[ -r /dev/tty ]]; then
    printf '%s' "${prompt}" >/dev/tty
    IFS= read -r input </dev/tty || true
    printf '\n' >/dev/tty
  elif [[ -t 0 ]]; then
    printf '%s' "${prompt}" >&2
    IFS= read -r input || true
    printf '\n' >&2
  else
    printf '%s' "${prompt}" >&2
    IFS= read -r input || true
    printf '\n' >&2
  fi

  printf -v "${var_name}" '%s' "${input}"
  normalize_secret_input "${var_name}"
}

prompt_with_default() {
  local prompt="$1"
  local default_value="$2"
  local var_name="$3"
  local input=""

  printf '%s [%s]: ' "${prompt}" "${default_value}" >&2
  IFS= read -r input || true
  if [[ -z "${input}" ]]; then
    input="${default_value}"
  fi
  printf -v "${var_name}" '%s' "${input}"
}
