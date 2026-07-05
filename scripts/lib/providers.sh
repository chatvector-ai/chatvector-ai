#!/usr/bin/env bash
# Guided provider setup and configuration validation.

GEN_AI_KEY_PLACEHOLDER="your_google_ai_studio_api_key_here"
OPENAI_API_KEY_PLACEHOLDER="your_openai_api_key_here"
ANTHROPIC_API_KEY_PLACEHOLDER="your_anthropic_api_key_here"
VOYAGE_API_KEY_PLACEHOLDER="your_voyage_api_key_here"

OLLAMA_DEFAULT_LLM_MODEL="llama3"
OLLAMA_DEFAULT_EMBEDDING_MODEL="nomic-embed-text"

effective_llm_provider() {
  to_lower "$(env_value_or_default "${BACKEND_ENV}" "LLM_PROVIDER" "gemini")"
}

effective_embedding_provider() {
  to_lower "$(env_value_or_default "${BACKEND_ENV}" "EMBEDDING_PROVIDER" "gemini")"
}

env_var_is_set() {
  local key="$1"
  grep -qE "^${key}=" "${BACKEND_ENV}" 2>/dev/null
}

provider_env_var_name() {
  case "$1" in
    gemini) printf '%s' "GEN_AI_KEY" ;;
    openai) printf '%s' "OPENAI_API_KEY" ;;
    anthropic) printf '%s' "ANTHROPIC_API_KEY" ;;
    voyage) printf '%s' "VOYAGE_API_KEY" ;;
    *) return 1 ;;
  esac
}

gemini_key_valid() {
  local key
  key="$(read_env_value "${BACKEND_ENV}" "GEN_AI_KEY")"
  ! is_placeholder_value "${key}" "${GEN_AI_KEY_PLACEHOLDER}"
}

openai_key_valid() {
  local key
  key="$(read_env_value "${BACKEND_ENV}" "OPENAI_API_KEY")"
  ! is_placeholder_value "${key}" "${OPENAI_API_KEY_PLACEHOLDER}"
}

anthropic_key_valid() {
  local key
  key="$(read_env_value "${BACKEND_ENV}" "ANTHROPIC_API_KEY")"
  ! is_placeholder_value "${key}" "${ANTHROPIC_API_KEY_PLACEHOLDER}"
}

voyage_key_valid() {
  local key
  key="$(read_env_value "${BACKEND_ENV}" "VOYAGE_API_KEY")"
  ! is_placeholder_value "${key}" "${VOYAGE_API_KEY_PLACEHOLDER}"
}

provider_key_requirement_met() {
  local provider="$1"
  case "${provider}" in
    gemini) gemini_key_valid ;;
    openai) openai_key_valid ;;
    ollama) return 0 ;;
    anthropic) anthropic_key_valid ;;
    voyage) voyage_key_valid ;;
    *) return 1 ;;
  esac
}

has_explicit_provider_selection() {
  env_var_is_set "LLM_PROVIDER" || env_var_is_set "EMBEDDING_PROVIDER"
}

is_guided_preset_pair() {
  local llm emb
  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"
  [[ "${llm}" == "${emb}" && ( "${llm}" == "gemini" || "${llm}" == "openai" || "${llm}" == "ollama" ) ]]
}

list_missing_provider_env_vars() {
  local llm emb var
  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"

  if ! provider_key_requirement_met "${llm}"; then
    if var="$(provider_env_var_name "${llm}")"; then
      printf '%s\n' "${var}"
    fi
  fi

  if ! provider_key_requirement_met "${emb}"; then
    if var="$(provider_env_var_name "${emb}")"; then
      printf '%s\n' "${var}"
    fi
  fi
}

describe_provider_requirements() {
  local llm emb missing_vars
  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"
  missing_vars="$(list_missing_provider_env_vars | sort -u | tr '\n' ' ')"

  if [[ -n "${missing_vars// /}" ]]; then
    echo "Missing or placeholder values for: LLM_PROVIDER=${llm}, EMBEDDING_PROVIDER=${emb}." >&2
    echo "Set these environment variables in backend/.env: ${missing_vars% }" >&2
    return 1
  fi
  return 0
}

is_provider_configuration_complete() {
  local llm emb
  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"

  case "${llm}" in
    gemini|openai|ollama|anthropic) ;;
    *)
      echo "Unsupported LLM_PROVIDER=${llm}." >&2
      return 1
      ;;
  esac

  case "${emb}" in
    gemini|openai|ollama|voyage) ;;
    *)
      echo "Unsupported EMBEDDING_PROVIDER=${emb}." >&2
      return 1
      ;;
  esac

  provider_key_requirement_met "${llm}" && provider_key_requirement_met "${emb}"
}

print_keep_existing_provider_next_steps() {
  cat <<EOF

Keep your existing provider selections and edit:
  backend/.env

See:
  backend/.env.example

When configuration is complete, run:
  make
EOF
}

print_manual_provider_next_steps() {
  cat <<EOF

Advanced provider configuration selected.

Edit:
  backend/.env

See:
  backend/.env.example

When configuration is complete, run:
  make
EOF
}

default_ollama_docker_base_url() {
  printf '%s' "http://host.docker.internal:11434"
}

ollama_host_check_url() {
  local url="$1"
  url="${url//host.docker.internal/localhost}"
  printf '%s' "${url}"
}

prompt_for_api_key() {
  local provider_name="$1"
  local prompt_text="$2"
  local help_url="$3"
  local var_name="$4"
  local input=""
  local attempt=0

  while [[ -z "${input}" ]]; do
    attempt=$((attempt + 1))
    if [[ "${attempt}" -eq 1 ]]; then
      prompt_hidden "${prompt_text}" input
    else
      echo "Hidden input is unavailable in this terminal." >&2
      prompt_visible \
        "Enter your ${provider_name} API key (key only, not VAR=...): " \
        input
    fi

    if [[ -z "${input}" ]]; then
      echo "A valid ${provider_name} API key is required." >&2
      echo "Enter the key value only — do not include GEN_AI_KEY= or quotes." >&2
      echo "Get one at ${help_url}" >&2
    fi
  done
  printf -v "${var_name}" '%s' "${input}"
}

apply_gemini_preset() {
  local key_input=""
  prompt_for_api_key \
    "Google Gemini" \
    "Enter your Google Gemini API key (key only, hidden): " \
    "https://aistudio.google.com/" \
    key_input

  set_env_vars "${BACKEND_ENV}" \
    "LLM_PROVIDER=gemini" \
    "EMBEDDING_PROVIDER=gemini" \
    "GEN_AI_KEY=${key_input}"

  echo "Configured Gemini for generation and embeddings (key not shown)."
}

apply_openai_preset() {
  local key_input=""
  prompt_for_api_key \
    "OpenAI" \
    "Enter your OpenAI API key (key only, hidden): " \
    "https://platform.openai.com/api-keys" \
    key_input

  set_env_vars "${BACKEND_ENV}" \
    "LLM_PROVIDER=openai" \
    "EMBEDDING_PROVIDER=openai" \
    "OPENAI_API_KEY=${key_input}"

  echo "Configured OpenAI for generation and embeddings (key not shown)."
}

ollama_model_available() {
  local tags="$1"
  local model="$2"
  grep -q "\"name\":\"${model}\"" <<<"${tags}" \
    || grep -q "\"name\":\"${model}:" <<<"${tags}"
}

check_ollama_models_present() {
  local tags_url="$1"
  local llm_model="$2"
  local embed_model="$3"
  local tags llm_ok=1 embed_ok=1

  if ! tags="$(curl -sf "${tags_url}" 2>/dev/null)"; then
    echo "Could not list Ollama models at ${tags_url}." >&2
    return 1
  fi

  if ollama_model_available "${tags}" "${llm_model}"; then
    llm_ok=0
  else
    echo "Ollama LLM model '${llm_model}' is not available locally." >&2
    echo "  ollama pull ${llm_model}" >&2
  fi

  if ollama_model_available "${tags}" "${embed_model}"; then
    embed_ok=0
  else
    echo "Ollama embedding model '${embed_model}' is not available locally." >&2
    echo "  ollama pull ${embed_model}" >&2
  fi

  if [[ "${llm_ok}" -ne 0 || "${embed_ok}" -ne 0 ]]; then
    return 1
  fi
  return 0
}

check_ollama_host_reachable() {
  local host_url="$1"
  curl -sf "${host_url}/api/tags" >/dev/null 2>&1
}

check_ollama_container_reachable() {
  local docker_url="$1"

  if docker_compose exec -T api curl -sf "${docker_url}/api/tags" >/dev/null 2>&1; then
    return 0
  fi

  docker_compose run --rm --no-deps --entrypoint curl api \
    -sf "${docker_url}/api/tags" >/dev/null 2>&1
}

check_ollama_host_and_models() {
  local docker_base_url="$1"
  local llm_model="$2"
  local embed_model="$3"
  local host_url tags_url

  host_url="$(ollama_host_check_url "${docker_base_url}")"
  tags_url="${host_url}/api/tags"

  if ! check_ollama_host_reachable "${host_url}"; then
    echo "Ollama is not running or not reachable on the host at ${host_url}." >&2
    echo "Install and start Ollama on your host machine, then rerun setup." >&2
    return 1
  fi

  check_ollama_models_present "${tags_url}" "${llm_model}" "${embed_model}"
}

verify_ollama_docker_connectivity() {
  local docker_url llm emb host_url

  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"
  if [[ "${llm}" != "ollama" && "${emb}" != "ollama" ]]; then
    return 0
  fi

  docker_url="$(read_env_value "${BACKEND_ENV}" "OLLAMA_BASE_URL")"
  if [[ -z "${docker_url}" ]]; then
    docker_url="$(default_ollama_docker_base_url)"
  fi
  host_url="$(ollama_host_check_url "${docker_url}")"

  if ! check_ollama_container_reachable "${docker_url}"; then
    if check_ollama_host_reachable "${host_url}"; then
      echo "Ollama is reachable on the host at ${host_url}, but not from the API container at ${docker_url}." >&2
      echo "Ensure docker-compose.yml maps host.docker.internal for the api service (extra_hosts: host-gateway)." >&2
    else
      echo "Ollama is not reachable from the API container at ${docker_url}." >&2
      echo "Install and start Ollama on your host, then rerun: make" >&2
    fi
    return 1
  fi

  return 0
}

apply_ollama_preset() {
  local docker_base_url llm_model embed_model

  prompt_with_default \
    "Ollama base URL for the API container" \
    "$(default_ollama_docker_base_url)" \
    docker_base_url
  prompt_with_default "Ollama LLM model" "${OLLAMA_DEFAULT_LLM_MODEL}" llm_model
  prompt_with_default "Ollama embedding model" "${OLLAMA_DEFAULT_EMBEDDING_MODEL}" embed_model

  set_env_vars "${BACKEND_ENV}" \
    "LLM_PROVIDER=ollama" \
    "EMBEDDING_PROVIDER=ollama" \
    "OLLAMA_BASE_URL=${docker_base_url}" \
    "LLM_MODEL=${llm_model}" \
    "EMBEDDING_MODEL=${embed_model}"

  echo "Configured Ollama for generation and embeddings."

  if ! check_ollama_host_and_models "${docker_base_url}" "${llm_model}" "${embed_model}"; then
    echo "Ollama settings were saved, but host readiness checks failed." >&2
    echo "Fix Ollama on your host, then run: make" >&2
    return 0
  fi
}

apply_advanced_mode() {
  print_manual_provider_next_steps
}

offer_incomplete_configuration_choice() {
  local selection=""

  cat <<'EOF'

Existing provider configuration is incomplete.

1) Keep it and edit backend/.env manually
2) Replace it with a guided provider preset

Selection [1]:
EOF
  IFS= read -r selection || true
  selection="${selection:-1}"

  case "${selection}" in
    1|"")
      describe_provider_requirements || true
      print_keep_existing_provider_next_steps
      return 0
      ;;
    2)
      run_provider_wizard
      return $?
      ;;
    *)
      echo "Invalid selection. Choose 1 or 2." >&2
      return 1
      ;;
  esac
}

show_provider_menu() {
  cat <<'EOF'

Choose a provider setup:

1) Gemini — recommended, simplest setup
2) OpenAI
3) Ollama — local, no API key
4) Advanced / mixed providers

Selection [1]:
EOF
}

run_provider_wizard() {
  local selection=""

  show_provider_menu
  IFS= read -r selection || true
  selection="${selection:-1}"

  case "${selection}" in
    1|"")
      apply_gemini_preset
      ;;
    2)
      apply_openai_preset
      ;;
    3)
      apply_ollama_preset
      ;;
    4)
      apply_advanced_mode
      return 0
      ;;
    *)
      echo "Invalid selection. Choose 1, 2, 3, or 4." >&2
      return 1
      ;;
  esac
}

configure_backend_provider() {
  if [[ ! -f "${BACKEND_ENV}" ]]; then
    cp "${BACKEND_ENV_EXAMPLE}" "${BACKEND_ENV}"
    echo "Created backend/.env from backend/.env.example"
  else
    echo "Preserving existing backend/.env"
  fi

  if is_provider_configuration_complete; then
    echo "Provider configuration already complete (LLM=$(effective_llm_provider), embeddings=$(effective_embedding_provider))."
    return 0
  fi

  echo "Backend provider configuration is missing or incomplete."

  if has_explicit_provider_selection; then
    if ! offer_incomplete_configuration_choice; then
      return 1
    fi
  else
    if ! describe_provider_requirements; then
      echo "Guided setup can configure Gemini, OpenAI, or Ollama, or you can choose Advanced for manual editing."
    fi
    if ! run_provider_wizard; then
      return 1
    fi
  fi

  if is_provider_configuration_complete; then
    return 0
  fi

  return 0
}

ensure_frontend_env() {
  if [[ ! -f "${FRONTEND_ENV}" ]]; then
    printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\n' >"${FRONTEND_ENV}"
    echo "Created frontend-demo/.env.local"
    return 0
  fi

  echo "Preserving existing frontend-demo/.env.local"
  if ! grep -qE '^NEXT_PUBLIC_API_URL=' "${FRONTEND_ENV}"; then
    echo "Warning: frontend-demo/.env.local exists but lacks NEXT_PUBLIC_API_URL." >&2
    echo "Add NEXT_PUBLIC_API_URL=http://localhost:8000 or recreate the file via setup on a fresh clone." >&2
  fi
}
