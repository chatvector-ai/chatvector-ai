import os
import sys
import pytest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure imports relying on backend/.env do not crash test collection.
# Default to "test" so log routing in logging_config.setup_logging() sends
# output to logs/test.log when pytest is invoked directly. `make tests`
# (Docker) already injects APP_ENV=test via docker-compose.yml, so this
# only changes the local-pytest path.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GEN_AI_KEY", "test-genai-key")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
)

# Force logging setup BEFORE any app modules are imported.
# This ensures all log output (including startup/shutdown) goes to test.log,
# keeping app.log clean for development server traffic only.
from logging_config.logging_config import setup_logging
setup_logging()

env_file = BACKEND_DIR / ".env"
if not env_file.exists():
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                "GEN_AI_KEY=test-genai-key",
                "LOG_LEVEL=DEBUG",
                "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    import sys
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()

@pytest.fixture(scope="session", autouse=True)
def clear_test_logs():
    """Clear test log files at the start of each test session.

    Prevents test output from accumulating across runs and keeps the
    test log stream readable. Only clears logs/test.log and
    logs/test_access.log — production log files are never touched.
    """
    logs_dir = BACKEND_DIR / "logs"
    test_log_files = [
        logs_dir / "test.log",
        logs_dir / "test_access.log",
    ]
    for log_file in test_log_files:
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")
    yield


@pytest.fixture(autouse=True)
def _reset_db_service_singleton():
    """Clear cached SQLAlchemyService between tests.

    pytest-asyncio uses a fresh event loop per async test, but ``db.db_service``
    binds its async engine to the first loop that created it. Reusing that cache
    in a later test (especially sync TestClient lifespan startup) triggers asyncpg
    "another operation is in progress" errors.
    """
    import db as db_module
    from services.api_key_service import reset_session_factory

    db_module.db_service = None
    reset_session_factory()
    yield
    db_module.db_service = None
    reset_session_factory()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Join RQ workers before pytest closes the captured stderr stream."""
    from services.queue_redis import shutdown_lingering_redis_workers

    shutdown_lingering_redis_workers()
