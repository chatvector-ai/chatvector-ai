from pathlib import Path
from dotenv import load_dotenv
import logging
import os

from core.provider_capabilities import (
    EMBEDDING_PROVIDER_NAMES,
    LLM_PROVIDER_NAMES,
)

logger = logging.getLogger(__name__)

# Backend root is the expected location of .env
ROOT_DIR = Path(__file__).resolve().parent.parent  # core/ -> backend/
dotenv_path = ROOT_DIR / ".env"

if dotenv_path.exists():
    load_dotenv(dotenv_path)
    logger.debug("Loaded environment variables from %s", dotenv_path)
else:
    # CI and some containers inject all settings via the process environment.
    # Local developers should still add backend/.env; we only warn here.
    logger.warning(
        ".env not found at %s — using process environment only",
        dotenv_path,
    )

# Statuses that indicate a document was mid-flight when the server last stopped.
STALE_INGESTION_STATUSES = [
    "uploaded",
    "queued",
    "retrying",
    "extracting",
    "chunking",
    "embedding",
    "storing",
]
VALID_CHUNKING_STRATEGIES = {"fixed", "paragraph", "semantic"}
VALID_QUERY_TRANSFORMATION_STRATEGIES = {"rewrite", "expand", "stepback"}
VALID_RERANKER_PROVIDERS = {"similarity", "cohere"}
VALID_LLM_PROVIDERS = set(LLM_PROVIDER_NAMES)
VALID_EMBEDDING_PROVIDERS = set(EMBEDDING_PROVIDER_NAMES)


def _get_chunking_strategy() -> str:
    strategy = os.getenv("CHUNKING_STRATEGY", "fixed").strip().lower()
    if strategy not in VALID_CHUNKING_STRATEGIES:
        valid_strategies = ", ".join(sorted(VALID_CHUNKING_STRATEGIES))
        raise ValueError(
            f"Invalid CHUNKING_STRATEGY={strategy!r}. "
            f"Expected one of: {valid_strategies}."
        )
    return strategy


def _get_query_transformation_strategy() -> str:
    strategy = os.getenv("QUERY_TRANSFORMATION_STRATEGY", "rewrite").strip().lower()
    if strategy not in VALID_QUERY_TRANSFORMATION_STRATEGIES:
        valid_strategies = ", ".join(sorted(VALID_QUERY_TRANSFORMATION_STRATEGIES))
        raise ValueError(
            f"Invalid QUERY_TRANSFORMATION_STRATEGY={strategy!r}. "
            f"Expected one of: {valid_strategies}."
        )
    return strategy


def _get_llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in VALID_LLM_PROVIDERS:
        valid = ", ".join(sorted(VALID_LLM_PROVIDERS))
        raise ValueError(
            f"Invalid LLM_PROVIDER={provider!r}. Expected one of: {valid}."
        )
    return provider


def _get_embedding_provider() -> str:
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini").strip().lower()
    if provider not in VALID_EMBEDDING_PROVIDERS:
        valid = ", ".join(sorted(VALID_EMBEDDING_PROVIDERS))
        raise ValueError(
            f"Invalid EMBEDDING_PROVIDER={provider!r}. Expected one of: {valid}."
        )
    return provider


def _get_reranker_provider() -> str:
    provider = os.getenv("RERANKER_PROVIDER", "similarity").strip().lower()
    if provider not in VALID_RERANKER_PROVIDERS:
        valid = ", ".join(sorted(VALID_RERANKER_PROVIDERS))
        raise ValueError(
            f"Invalid RERANKER_PROVIDER={provider!r}. Expected one of: {valid}."
        )
    return provider


VALID_PERSONAS = {"default", "concise", "conversational", "academic", "technical"}


def _get_persona() -> str:
    persona = os.getenv("PROMPT_PERSONA", "default").strip().lower()
    if persona not in VALID_PERSONAS:
        valid_personas_str = ", ".join(sorted(VALID_PERSONAS))
        logger.warning(
            "Invalid PROMPT_PERSONA=%r. Expected one of: %s. Falling back to 'default'.",
            persona,
            valid_personas_str,
        )
        persona = "default"
    return persona


def _get_system_prompt_path(persona: str) -> str:
    custom_path = os.getenv("SYSTEM_PROMPT_PATH")
    if custom_path:
        return custom_path

    if persona == "default":
        return str(ROOT_DIR / "prompts" / "default_system.txt")
    
    return str(ROOT_DIR / "prompts" / "personas" / f"{persona}.txt")


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "production")
    IS_PROD = APP_ENV.lower() == "production"
    ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "false").lower() in ("1", "true", "yes")
    GEN_AI_KEY: str | None = os.getenv("GEN_AI_KEY")

    # Provider selection
    LLM_PROVIDER: str = _get_llm_provider()
    LLM_MODEL: str | None = os.getenv("LLM_MODEL") or None
    EMBEDDING_PROVIDER: str = _get_embedding_provider()
    EMBEDDING_MODEL: str | None = os.getenv("EMBEDDING_MODEL") or None
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    ANTHROPIC_BASE_URL: str | None = os.getenv("ANTHROPIC_BASE_URL") or None
    VOYAGE_API_KEY: str | None = os.getenv("VOYAGE_API_KEY") or None

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "TEXT").upper()  # TEXT or JSON
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")

    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    MAX_UPLOAD_SIZE_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    # Bounds for the optional `metadata` multipart field on POST /upload.
    DOCUMENT_METADATA_MAX_KEYS: int = max(1, int(os.getenv("DOCUMENT_METADATA_MAX_KEYS", "20")))
    DOCUMENT_METADATA_MAX_BYTES: int = max(2, int(os.getenv("DOCUMENT_METADATA_MAX_BYTES", "4096")))
    DOCX_MAX_UNCOMPRESSED_MB: int = int(
        os.getenv("DOCX_MAX_UNCOMPRESSED_MB", str(max(50, MAX_UPLOAD_SIZE_MB * 10)))
    )
    DOCX_MAX_UNCOMPRESSED_BYTES: int = DOCX_MAX_UNCOMPRESSED_MB * 1024 * 1024
    DOCX_MAX_ZIP_ENTRIES: int = max(1, int(os.getenv("DOCX_MAX_ZIP_ENTRIES", "500")))
    DOCX_MAX_COMPRESSION_RATIO: int = max(
        1, int(os.getenv("DOCX_MAX_COMPRESSION_RATIO", "100"))
    )
    CHUNK_SIZE: int = max(1, int(os.getenv("CHUNK_SIZE", "1000")))
    CHUNK_OVERLAP: int = max(0, int(os.getenv("CHUNK_OVERLAP", "200")))
    CHUNKING_STRATEGY: str = _get_chunking_strategy()
    QUERY_TRANSFORMATION_ENABLED: bool = os.getenv(
        "QUERY_TRANSFORMATION_ENABLED", "false"
    ).lower() in ("1", "true", "yes")
    QUERY_TRANSFORMATION_STRATEGY: str = _get_query_transformation_strategy()
    RETRIEVAL_MAX_CONCURRENCY: int = max(1, int(os.getenv("RETRIEVAL_MAX_CONCURRENCY", "8")))
    RETRIEVAL_DEBUG_MAX_ELIGIBLE_IDS: int = max(
        1, int(os.getenv("RETRIEVAL_DEBUG_MAX_ELIGIBLE_IDS", "100"))
    )
    ENABLE_RERANKING: bool = os.getenv("ENABLE_RERANKING", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    RERANKER_PROVIDER: str = _get_reranker_provider()
    # Hosted reranker (Cohere). The key is process-env only, never request-supplied.
    COHERE_API_KEY: str | None = os.getenv("COHERE_API_KEY") or None
    COHERE_RERANK_MODEL: str = os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5").strip()
    COHERE_RERANK_URL: str = os.getenv(
        "COHERE_RERANK_URL", "https://api.cohere.com/v2/rerank"
    ).strip()
    RERANKER_TIMEOUT_SEC: float = max(0.1, float(os.getenv("RERANKER_TIMEOUT_SEC", "5")))
    RERANKER_MAX_CANDIDATES: int = max(1, int(os.getenv("RERANKER_MAX_CANDIDATES", "50")))
    HYBRID_RETRIEVAL_ENABLED: bool = os.getenv(
        "HYBRID_RETRIEVAL_ENABLED", "false"
    ).lower() in ("1", "true", "yes")
    # Experimental GraphRAG overlay. Default off — must not change chat
    # behavior or add required runtime deps. See backend/rfcs/graph-retrieval.md.
    ENABLE_GRAPH_RETRIEVAL: bool = os.getenv(
        "ENABLE_GRAPH_RETRIEVAL", "false"
    ).lower() in ("1", "true", "yes")
    GRAPH_RETRIEVAL_FIXTURE_PATH: str | None = (
        os.getenv("GRAPH_RETRIEVAL_FIXTURE_PATH") or None
    )
    # Optional process-local named retrieval presets (see retrieval_presets.py).
    RETRIEVAL_PRESETS_PATH: str | None = os.getenv("RETRIEVAL_PRESETS_PATH") or None
    RETRIEVAL_PRESETS: str | None = os.getenv("RETRIEVAL_PRESETS") or None
    CHAT_BATCH_MAX_ITEMS: int = max(1, int(os.getenv("CHAT_BATCH_MAX_ITEMS", "20")))
    CHAT_MAX_DOC_IDS_PER_QUERY: int = max(1, int(os.getenv("CHAT_MAX_DOC_IDS_PER_QUERY", "10")))
    CHAT_BATCH_LLM_CONCURRENCY: int = max(
        1, int(os.getenv("CHAT_BATCH_LLM_CONCURRENCY", "4"))
    )
    MAX_SESSION_HISTORY_MESSAGES: int = max(1, int(os.getenv("MAX_SESSION_HISTORY_MESSAGES", "20")))
    QUERY_TRANSFORMATION_HISTORY_WINDOW: int = max(1, int(os.getenv("QUERY_TRANSFORMATION_HISTORY_WINDOW", "6")))
    # Phase 4 default: gated standalone resolution runs even when query
    # transformation strategies are off. Set false to restore Phase 3 coupling
    # (resolve only when QUERY_TRANSFORMATION_ENABLED is true, and then always).
    HISTORY_AWARE_RETRIEVAL_DEFAULT: bool = os.getenv(
        "HISTORY_AWARE_RETRIEVAL_DEFAULT", "true"
    ).lower() in ("1", "true", "yes")
    GENERATION_HISTORY_WINDOW: int = max(0, int(os.getenv("GENERATION_HISTORY_WINDOW", "10")))
    SQLALCHEMY_POOL_SIZE: int = max(1, int(os.getenv("SQLALCHEMY_POOL_SIZE", "5")))
    SQLALCHEMY_MAX_OVERFLOW: int = max(0, int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "10")))
    SQLALCHEMY_POOL_TIMEOUT_SEC: int = max(1, int(os.getenv("SQLALCHEMY_POOL_TIMEOUT_SEC", "30")))
    SQLALCHEMY_STATEMENT_TIMEOUT_SEC: int = max(
        1, int(os.getenv("SQLALCHEMY_STATEMENT_TIMEOUT_SEC", "30"))
    )
    SQLALCHEMY_RETRIEVAL_CONCURRENCY: int = max(1, int(os.getenv("SQLALCHEMY_RETRIEVAL_CONCURRENCY", "8")))

    # Queue backend selection
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_SOCKET_TIMEOUT_SEC: float = max(
        0.1, float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5"))
    )
    QUEUE_BACKEND: str = os.getenv(
        "QUEUE_BACKEND", 
        "redis" if APP_ENV.lower() == "production" else "memory"
    ).strip().lower()
    # Horizontal API replicas. When true: tenant lists are DB-authoritative
    # by default, stale reconciliation uses a Redis lock, and split API/worker
    # hosts require ARTIFACT_STORAGE=s3.
    MULTI_API_INSTANCE: bool = os.getenv("MULTI_API_INSTANCE", "false").lower() in (
        "1", "true", "yes"
    )
    TENANT_REGISTRY_DISABLED: bool = (
        MULTI_API_INSTANCE
        if not (os.getenv("TENANT_REGISTRY_DISABLED") or "").strip()
        else os.getenv("TENANT_REGISTRY_DISABLED", "").lower() in ("1", "true", "yes")
    )
    STALE_RECONCILE_LOCK_TTL_SECONDS: int = max(
        1, int(os.getenv("STALE_RECONCILE_LOCK_TTL_SECONDS", "600"))
    )

    # Background ingestion queue
    QUEUE_WORKER_COUNT: int = max(1, min(5, int(os.getenv("QUEUE_WORKER_COUNT", "3"))))
    QUEUE_MAX_SIZE: int = max(1, int(os.getenv("QUEUE_MAX_SIZE", "100")))
    QUEUE_EMBEDDING_RPS: float = max(0.1, float(os.getenv("QUEUE_EMBEDDING_RPS", "2.0")))
    QUEUE_SPILL_DIR: str = os.getenv("QUEUE_SPILL_DIR", "/tmp/chatvector")
    # Durable upload artifacts. ``local`` keeps Redis spill on QUEUE_SPILL_DIR
    # (single-host default). ``s3`` is required when API and workers do not
    # share a filesystem.
    ARTIFACT_STORAGE: str = os.getenv("ARTIFACT_STORAGE", "local").strip().lower()
    ARTIFACT_TTL_SECONDS: int = max(0, int(os.getenv("ARTIFACT_TTL_SECONDS", "86400")))
    ARTIFACT_S3_BUCKET: str | None = os.getenv("ARTIFACT_S3_BUCKET") or None
    ARTIFACT_S3_ENDPOINT_URL: str | None = os.getenv("ARTIFACT_S3_ENDPOINT_URL") or None
    ARTIFACT_S3_REGION: str = os.getenv("ARTIFACT_S3_REGION", "us-east-1").strip() or "us-east-1"
    ARTIFACT_S3_ACCESS_KEY: str | None = (
        os.getenv("ARTIFACT_S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or None
    )
    ARTIFACT_S3_SECRET_KEY: str | None = (
        os.getenv("ARTIFACT_S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or None
    )
    ARTIFACT_S3_PREFIX: str = os.getenv("ARTIFACT_S3_PREFIX", "chatvector/artifacts/")
    ARTIFACT_S3_FORCE_PATH_STYLE: bool = os.getenv(
        "ARTIFACT_S3_FORCE_PATH_STYLE", "true"
    ).lower() in ("1", "true", "yes")
    QUEUE_DLQ_MAX_ENTRIES: int = max(1, int(os.getenv("QUEUE_DLQ_MAX_ENTRIES", "1000")))
    QUEUE_JOB_MAX_RETRIES: int = max(0, int(os.getenv("QUEUE_JOB_MAX_RETRIES", "3")))
    QUEUE_RETRY_BASE_DELAY: float = max(
        0.1, float(os.getenv("QUEUE_RETRY_BASE_DELAY", "2.0"))
    )
    HEALTH_CHECK_CACHE_TTL_SECONDS: int = max(
        0, int(os.getenv("HEALTH_CHECK_CACHE_TTL_SECONDS", "60"))
    )

    RATE_LIMIT_DEV_IP_FALLBACK: bool = os.getenv(
        "RATE_LIMIT_DEV_IP_FALLBACK", "false"
    ).lower() in ("1", "true", "yes")

    RATE_LIMIT_UPLOAD: str = os.getenv("RATE_LIMIT_UPLOAD", "20/hour")
    RATE_LIMIT_CHAT: str = os.getenv("RATE_LIMIT_CHAT", "30/minute")
    RATE_LIMIT_CHAT_BATCH: str = os.getenv("RATE_LIMIT_CHAT_BATCH", "10/minute")
    RATE_LIMIT_STATUS: str = os.getenv("RATE_LIMIT_STATUS", "10/minute")
    RATE_LIMIT_QUEUE_STATS: str = os.getenv("RATE_LIMIT_QUEUE_STATS", "10/minute")
    RATE_LIMIT_DOCUMENT_STATUS: str = os.getenv(
        "RATE_LIMIT_DOCUMENT_STATUS", "120/minute"
    )
    RATE_LIMIT_DOCUMENT_DELETE: str = os.getenv(
        "RATE_LIMIT_DOCUMENT_DELETE", "60/hour"
    )
    RATE_LIMIT_FEEDBACK: str = os.getenv("RATE_LIMIT_FEEDBACK", "60/minute")

    PROMPT_PERSONA: str = _get_persona()
    SYSTEM_PROMPT_PATH: str = _get_system_prompt_path(PROMPT_PERSONA)
    
    LLM_TEMPERATURE: float = max(
        0.0,
        min(2.0, float(os.getenv("LLM_TEMPERATURE", "0.2"))),
    )
    LLM_MAX_OUTPUT_TOKENS: int = max(1, int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024")))
    LLM_HTTP_TIMEOUT_MS: int = max(
        1000, int(os.getenv("LLM_HTTP_TIMEOUT_MS", "60000"))
    )
    # Outbound calls to embedding providers (and embedding_service retry_async).
    EMBEDDING_HTTP_TIMEOUT_SEC: int = max(
        1, int(os.getenv("EMBEDDING_HTTP_TIMEOUT_SEC", "60"))
    )
    # /status health probe for the embedding sub-check only.
    EMBEDDING_HEALTH_CHECK_TIMEOUT_SEC: int = max(
        1, int(os.getenv("EMBEDDING_HEALTH_CHECK_TIMEOUT_SEC", "10"))
    )
    LLM_HEALTH_CHECK_TIMEOUT_SEC: int = max(
        1, int(os.getenv("LLM_HEALTH_CHECK_TIMEOUT_SEC", "10"))
    )

    # Optional Redis-backed embedding cache (default off).
    ENABLE_EMBEDDING_CACHE: bool = os.getenv(
        "ENABLE_EMBEDDING_CACHE", "false"
    ).lower() in ("1", "true", "yes")
    EMBEDDING_CACHE_KEY_PREFIX: str = os.getenv(
        "EMBEDDING_CACHE_KEY_PREFIX", "chatvector:embedcache"
    )
    # 0 means no expiry (persist until evicted/overwritten).
    EMBEDDING_CACHE_TTL_SECONDS: int = max(
        0, int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "0"))
    )
    EMBEDDING_CACHE_INCLUDE_TENANT: bool = os.getenv(
        "EMBEDDING_CACHE_INCLUDE_TENANT", "false"
    ).lower() in ("1", "true", "yes")
    # Cache reads are optional and fail-open. Keep this well below
    # REDIS_SOCKET_TIMEOUT_SEC so a sick cache cannot add seconds to embedding.
    EMBEDDING_CACHE_REDIS_TIMEOUT_SEC: float = max(
        0.05, float(os.getenv("EMBEDDING_CACHE_REDIS_TIMEOUT_SEC", "0.25"))
    )

    # Mutating-route idempotency (Idempotency-Key header → Redis TTL store).
    IDEMPOTENCY_KEY_PREFIX: str = os.getenv(
        "IDEMPOTENCY_KEY_PREFIX", "chatvector:idempotency"
    )
    IDEMPOTENCY_TTL_SECONDS: int = max(
        60, int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
    )
    IDEMPOTENCY_KEY_MAX_LENGTH: int = max(
        1, int(os.getenv("IDEMPOTENCY_KEY_MAX_LENGTH", "255"))
    )
    IDEMPOTENCY_WAIT_TIMEOUT_SECONDS: float = max(
        0.5, float(os.getenv("IDEMPOTENCY_WAIT_TIMEOUT_SECONDS", "30"))
    )
    IDEMPOTENCY_POLL_INTERVAL_SECONDS: float = max(
        0.01, float(os.getenv("IDEMPOTENCY_POLL_INTERVAL_SECONDS", "0.05"))
    )

    WEBHOOK_ENABLED: bool = os.getenv("WEBHOOK_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    WEBHOOK_URL: str | None = os.getenv("WEBHOOK_URL") or None
    WEBHOOK_SECRET: str | None = os.getenv("WEBHOOK_SECRET") or None
    WEBHOOK_MAX_ATTEMPTS: int = max(1, int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "5")))
    WEBHOOK_TIMEOUT_SECONDS: float = max(
        0.1, float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
    )

VALID_QUEUE_BACKENDS = {"memory", "redis"}
VALID_ARTIFACT_STORAGES = {"local", "s3"}


def _validate_queue_backend(backend: str) -> None:
    if backend not in VALID_QUEUE_BACKENDS:
        valid = ", ".join(sorted(VALID_QUEUE_BACKENDS))
        raise ValueError(
            f"Invalid QUEUE_BACKEND={backend!r}. Expected one of: {valid}."
        )


def _validate_queue_backend_for_env(app_env: str, backend: str) -> None:
    _validate_queue_backend(backend)
    if app_env.lower() == "production" and backend == "memory":
        raise ValueError(
            "QUEUE_BACKEND=memory is not supported when APP_ENV=production. "
            "Set QUEUE_BACKEND=redis and ensure REDIS_URL is reachable."
        )


def _validate_webhook_settings(settings: Settings) -> None:
    if not settings.WEBHOOK_ENABLED:
        return
    missing: list[str] = []
    if not settings.WEBHOOK_URL or not settings.WEBHOOK_URL.strip():
        missing.append("WEBHOOK_URL")
    if not settings.WEBHOOK_SECRET or not settings.WEBHOOK_SECRET.strip():
        missing.append("WEBHOOK_SECRET")
    if missing:
        raise ValueError(
            "WEBHOOK_ENABLED is true but required settings are missing: "
            + ", ".join(missing)
        )


def _validate_artifact_storage(settings: Settings) -> None:
    backend = settings.ARTIFACT_STORAGE
    if backend not in VALID_ARTIFACT_STORAGES:
        valid = ", ".join(sorted(VALID_ARTIFACT_STORAGES))
        raise ValueError(
            f"Invalid ARTIFACT_STORAGE={backend!r}. Expected one of: {valid}."
        )
    if backend == "s3" and not (settings.ARTIFACT_S3_BUCKET or "").strip():
        raise ValueError(
            "ARTIFACT_STORAGE=s3 requires ARTIFACT_S3_BUCKET."
        )


def _validate_multi_api_instance(settings: Settings) -> None:
    if not settings.MULTI_API_INSTANCE:
        return
    if settings.QUEUE_BACKEND != "redis":
        raise ValueError(
            "MULTI_API_INSTANCE=true requires QUEUE_BACKEND=redis "
            "(needed for the stale-document reconciler lock)."
        )
    if settings.ARTIFACT_STORAGE != "s3":
        raise ValueError(
            "MULTI_API_INSTANCE=true requires ARTIFACT_STORAGE=s3. "
            "Local spill is not visible across split API/worker hosts."
        )


config = Settings()
_validate_queue_backend_for_env(config.APP_ENV, config.QUEUE_BACKEND)
_validate_webhook_settings(config)
_validate_artifact_storage(config)
_validate_multi_api_instance(config)

# Requested history windows (0–100) are loaded up to history_config.MAX_HISTORY_WINDOW.
# MAX_SESSION_HISTORY_MESSAGES is the default load floor, not a silent request ceiling.


def _validate_cors_origins(origins: list[str]) -> None:
    for origin in origins:
        if origin.strip() == "*":
            import warnings

            warnings.warn(
                "CORS_ORIGINS contains '*' but allow_credentials=True is set. "
                "Browsers will reject credentialed requests to wildcard origins. "
                "Set explicit origins in CORS_ORIGINS.",
                stacklevel=2,
            )


_validate_cors_origins(config.CORS_ORIGINS)


def get_embedding_dim() -> int:
    """Return the embedding vector dimension for the current configuration.

    Resolution order:
    1. Explicit ``EMBEDDING_DIM`` env var (override for unknown/custom models).
    2. The configured provider's ``embedding_dim`` property (authoritative;
       each provider knows the width of its own model).
    """
    raw = os.getenv("EMBEDDING_DIM")
    if raw:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(
                f"EMBEDDING_DIM={raw!r} is not a valid integer. "
                f"Set it to the embedding dimension of your model "
                f"(e.g. 3072 for Gemini, 1536 for OpenAI text-embedding-3-small)."
            )

    # Deferred import: avoids a circular import at module load time and
    # keeps the provider factory lazy for everything except this single call.
    from services.providers import get_embedding_provider

    return get_embedding_provider().embedding_dim


def redis_connection_kwargs(**extra) -> dict:
    """Keyword args for redis-py ``Redis.from_url`` with bounded socket waits."""
    timeout = config.REDIS_SOCKET_TIMEOUT_SEC
    return {
        "socket_timeout": timeout,
        "socket_connect_timeout": timeout,
        **extra,
    }
