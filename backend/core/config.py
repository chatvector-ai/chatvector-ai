from pathlib import Path
from dotenv import load_dotenv
import logging
import os

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
STALE_INGESTION_STATUSES = ["queued", "retrying", "extracting", "chunking", "embedding", "storing"]
VALID_CHUNKING_STRATEGIES = {"fixed", "paragraph", "semantic"}
VALID_QUERY_TRANSFORMATION_STRATEGIES = {"rewrite", "expand", "stepback"}
VALID_LLM_PROVIDERS = {"gemini", "openai", "ollama"}
VALID_EMBEDDING_PROVIDERS = {"gemini", "openai", "ollama"}


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


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "production")
    IS_PROD = APP_ENV.lower() == "production"
    ENABLE_STREAMING: bool = os.getenv("ENABLE_STREAMING", "false").lower() in ("1", "true", "yes")
    SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: str | None = os.getenv("SUPABASE_KEY")
    SUPABASE_HTTP_TIMEOUT_SEC: int = max(
        1, int(os.getenv("SUPABASE_HTTP_TIMEOUT_SEC", "30"))
    )
    GEN_AI_KEY: str | None = os.getenv("GEN_AI_KEY")

    # Provider selection
    LLM_PROVIDER: str = _get_llm_provider()
    LLM_MODEL: str | None = os.getenv("LLM_MODEL") or None
    EMBEDDING_PROVIDER: str = _get_embedding_provider()
    EMBEDDING_MODEL: str | None = os.getenv("EMBEDDING_MODEL") or None
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_USE_UTC: bool = os.getenv("LOG_USE_UTC", "false").lower() in ("1", "true", "yes")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "TEXT").upper()  # Add this line - TEXT or JSON
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")

    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    MAX_UPLOAD_SIZE_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    CHUNK_SIZE: int = max(1, int(os.getenv("CHUNK_SIZE", "1000")))
    CHUNK_OVERLAP: int = max(0, int(os.getenv("CHUNK_OVERLAP", "200")))
    CHUNKING_STRATEGY: str = _get_chunking_strategy()
    QUERY_TRANSFORMATION_ENABLED: bool = os.getenv(
        "QUERY_TRANSFORMATION_ENABLED", "false"
    ).lower() in ("1", "true", "yes")
    QUERY_TRANSFORMATION_STRATEGY: str = _get_query_transformation_strategy()
    RETRIEVAL_MAX_CONCURRENCY: int = max(1, int(os.getenv("RETRIEVAL_MAX_CONCURRENCY", "8")))
    SUPABASE_IO_CONCURRENCY: int = max(1, int(os.getenv("SUPABASE_IO_CONCURRENCY", "16")))
    CHAT_BATCH_MAX_ITEMS: int = max(1, int(os.getenv("CHAT_BATCH_MAX_ITEMS", "20")))
    CHAT_MAX_DOC_IDS_PER_QUERY: int = max(1, int(os.getenv("CHAT_MAX_DOC_IDS_PER_QUERY", "10")))
    SQLALCHEMY_POOL_SIZE: int = max(1, int(os.getenv("SQLALCHEMY_POOL_SIZE", "5")))
    SQLALCHEMY_MAX_OVERFLOW: int = max(0, int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "10")))
    SQLALCHEMY_POOL_TIMEOUT_SEC: int = max(1, int(os.getenv("SQLALCHEMY_POOL_TIMEOUT_SEC", "30")))
    SQLALCHEMY_STATEMENT_TIMEOUT_SEC: int = max(
        1, int(os.getenv("SQLALCHEMY_STATEMENT_TIMEOUT_SEC", "30"))
    )
    SQLALCHEMY_RETRIEVAL_CONCURRENCY: int = max(1, int(os.getenv("SQLALCHEMY_RETRIEVAL_CONCURRENCY", "8")))

    # Queue backend selection
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    QUEUE_BACKEND: str = os.getenv("QUEUE_BACKEND", "memory").strip().lower()

    # Background ingestion queue
    QUEUE_WORKER_COUNT: int = max(1, min(5, int(os.getenv("QUEUE_WORKER_COUNT", "3"))))
    QUEUE_MAX_SIZE: int = max(1, int(os.getenv("QUEUE_MAX_SIZE", "100")))
    QUEUE_EMBEDDING_RPS: float = max(0.1, float(os.getenv("QUEUE_EMBEDDING_RPS", "2.0")))
    QUEUE_JOB_MAX_RETRIES: int = max(0, int(os.getenv("QUEUE_JOB_MAX_RETRIES", "3")))
    QUEUE_RETRY_BASE_DELAY: float = max(
        0.1, float(os.getenv("QUEUE_RETRY_BASE_DELAY", "2.0"))
    )
    HEALTH_CHECK_CACHE_TTL_SECONDS: int = max(
        0, int(os.getenv("HEALTH_CHECK_CACHE_TTL_SECONDS", "60"))
    )

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

    SYSTEM_PROMPT_PATH: str = os.getenv(
        "SYSTEM_PROMPT_PATH",
        str(ROOT_DIR / "prompts" / "default_system.txt"),
    )
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
        1, int(os.getenv("LLM_HEALTH_CHECK_TIMEOUT_SEC", "120"))
    )

    # Backwards-compatible lowercase properties for accessing config values
    @property
    def supabase_url(self) -> str | None:
        return self.SUPABASE_URL

    @property
    def supabase_key(self) -> str | None:
        return self.SUPABASE_KEY


VALID_QUEUE_BACKENDS = {"memory", "redis"}


def _validate_queue_backend(backend: str) -> None:
    if backend not in VALID_QUEUE_BACKENDS:
        valid = ", ".join(sorted(VALID_QUEUE_BACKENDS))
        raise ValueError(
            f"Invalid QUEUE_BACKEND={backend!r}. Expected one of: {valid}."
        )


config = Settings()
_validate_queue_backend(config.QUEUE_BACKEND)


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
