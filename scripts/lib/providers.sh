#!/usr/bin/env bash
# Provider setup validation and manual-edit guidance.

GEN_AI_KEY_PLACEHOLDER="your_google_ai_studio_api_key_here"
OPENAI_API_KEY_PLACEHOLDER="your_openai_api_key_here"
ANTHROPIC_API_KEY_PLACEHOLDER="your_anthropic_api_key_here"
VOYAGE_API_KEY_PLACEHOLDER="your_voyage_api_key_here"

OLLAMA_DEFAULT_LLM_MODEL="llama3"
OLLAMA_DEFAULT_EMBEDDING_MODEL="nomic-embed-text"
MAX_PROVIDER_EDIT_ATTEMPTS="${MAX_PROVIDER_EDIT_ATTEMPTS:-5}"

effective_llm_provider() {
  to_lower "$(env_value_or_default "${BACKEND_ENV}" "LLM_PROVIDER" "gemini")"
}

effective_embedding_provider() {
  to_lower "$(env_value_or_default "${BACKEND_ENV}" "EMBEDDING_PROVIDER" "gemini")"
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

provider_env_var_example_line() {
  local var="$1"
  case "${var}" in
    GEN_AI_KEY) printf '%s\n' "GEN_AI_KEY=your_google_ai_studio_api_key" ;;
    OPENAI_API_KEY) printf '%s\n' "OPENAI_API_KEY=your_openai_api_key" ;;
    ANTHROPIC_API_KEY) printf '%s\n' "ANTHROPIC_API_KEY=your_anthropic_api_key" ;;
    VOYAGE_API_KEY) printf '%s\n' "VOYAGE_API_KEY=your_voyage_api_key" ;;
    *) printf '%s\n' "${var}=" ;;
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

ensure_backend_env_file() {
  if [[ ! -f "${BACKEND_ENV}" ]]; then
    cp "${BACKEND_ENV_EXAMPLE}" "${BACKEND_ENV}"
    echo "Created backend/.env from backend/.env.example"
  else
    echo "Preserving existing backend/.env"
  fi
}

print_provider_edit_instructions() {
  local llm emb var missing_vars=0

  llm="$(effective_llm_provider)"
  emb="$(effective_embedding_provider)"

  echo ""
  echo "Backend provider configuration is incomplete."
  echo ""
  echo "Current providers:"
  echo "  LLM_PROVIDER=${llm}"
  echo "  EMBEDDING_PROVIDER=${emb}"
  echo ""
  echo "Edit:"
  echo "  backend/.env"
  echo ""

  while IFS= read -r var; do
    [[ -n "${var}" ]] || continue
    if [[ "${missing_vars}" -eq 0 ]]; then
      echo "Set:"
      missing_vars=1
    fi
    printf '  '
    provider_env_var_example_line "${var}"
  done < <(list_missing_provider_env_vars | sort -u)

  if [[ "${missing_vars}" -eq 0 ]]; then
    describe_provider_requirements || true
  fi

  echo ""
  echo "See backend/.env.example for all provider options."
}

wait_for_provider_configuration_interactive() {
  local attempt=0

  while (( attempt < MAX_PROVIDER_EDIT_ATTEMPTS )); do
    print_provider_edit_instructions
    echo "Save the file, return to this terminal, and press Enter to continue."
    echo "Press Ctrl+C to cancel."
    echo ""

    IFS= read -r _ || return 1

    echo ""
    echo "Checking provider configuration..."

    if is_provider_configuration_complete; then
      echo "Provider configuration complete."
      echo "Continuing setup..."
      return 0
    fi

    attempt=$((attempt + 1))
    echo "Provider configuration is still incomplete."
    describe_provider_requirements || true
    echo ""
  done

  echo "Provider configuration is still incomplete after ${MAX_PROVIDER_EDIT_ATTEMPTS} attempts."
  print_provider_edit_instructions
  echo "Edit backend/.env, then run:"
  echo "  make"
  return 1
}

handle_quickstart_provider_configuration() {
  ensure_backend_env_file

  if is_provider_configuration_complete; then
    echo "Provider configuration already complete (LLM=$(effective_llm_provider), embeddings=$(effective_embedding_provider))."
    return 0
  fi

  if [[ -t 0 ]]; then
    if wait_for_provider_configuration_interactive; then
      return 0
    fi
    return 1
  fi

  print_provider_edit_instructions
  echo "Non-interactive session: edit backend/.env, then run:"
  echo "  make quickstart"
  echo "or:"
  echo "  make setup"
  echo "  make"
  return 1
}

handle_setup_provider_configuration() {
  ensure_backend_env_file

  if is_provider_configuration_complete; then
    echo "Provider configuration already complete (LLM=$(effective_llm_provider), embeddings=$(effective_embedding_provider))."
    return 0
  fi

  echo "Backend provider configuration is missing or incomplete."
  return 0
}

default_ollama_docker_base_url() {
  printf '%s' "http://host.docker.internal:11434"
}

ollama_host_check_url() {
  local url="$1"
  url="${url//host.docker.internal/localhost}"
  printf '%s' "${url}"
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
