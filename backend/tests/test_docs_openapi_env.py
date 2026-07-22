"""OpenAPI / docs URLs depend on APP_ENV (see main.FastAPI configuration)."""

import importlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from db.migration_ledger import migration_filenames


def _reload_app(monkeypatch, app_env: str):
    """Reload config/main for the requested APP_ENV."""
    monkeypatch.setenv("APP_ENV", app_env)
    if app_env == "development":
        # Prevent backend/.env QUEUE_BACKEND=redis from enabling Redis startup in dev tests.
        monkeypatch.setenv("QUEUE_BACKEND", "memory")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)
    return main


@pytest.fixture(autouse=True)
def _restore_main_after_test(monkeypatch):
    yield
    from services.api_key_service import reset_session_factory

    reset_session_factory()
    import db

    db.db_service = None
    monkeypatch.setenv("APP_ENV", "test")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)


def test_docs_returns_404_when_app_env_production(monkeypatch):
    main = _reload_app(monkeypatch, "production")

    with patch(
        "main._read_migration_ledger_with_retry",
        new_callable=AsyncMock,
        return_value=migration_filenames(),
    ), patch("core.clients.redis_client.ping", new_callable=AsyncMock), TestClient(
        main.app
    ) as client:
        response = client.get("/docs")
        assert response.status_code == 404


def test_docs_returns_200_when_app_env_development(monkeypatch):
    main = _reload_app(monkeypatch, "development")

    with patch(
        "main._read_migration_ledger_with_retry",
        new_callable=AsyncMock,
        return_value=migration_filenames(),
    ), patch(
        "services.api_key_service.bootstrap_development_tenant",
        new_callable=AsyncMock,
    ), TestClient(main.app) as client:
        assert client.get("/docs").status_code == 200


def test_global_exception_handler_masks_errors(monkeypatch):
    main = _reload_app(monkeypatch, "development")

    @main.app.get("/force-error-for-test")
    def force_error():
        raise RuntimeError("SENSITIVE_DB_PASSWORD_LEAK")

    with patch(
        "main._read_migration_ledger_with_retry",
        new_callable=AsyncMock,
        return_value=migration_filenames(),
    ), patch(
        "services.api_key_service.bootstrap_development_tenant",
        new_callable=AsyncMock,
    ), TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/force-error-for-test")

    assert response.status_code == 500
    data = response.json()

    assert data["detail"]["code"] == "internal_error"
    assert data["detail"]["message"] == "An unexpected error occurred."

    assert "SENSITIVE_DB_PASSWORD_LEAK" not in response.text
