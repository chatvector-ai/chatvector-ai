"""OpenAPI / docs URLs depend on APP_ENV (see main.FastAPI configuration)."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_main_after_test(monkeypatch):
    yield
    monkeypatch.setenv("APP_ENV", "production")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)


def test_docs_returns_404_when_app_env_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)

    with TestClient(main.app) as client:
        assert client.get("/docs").status_code == 404


def test_docs_returns_200_when_app_env_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)

    with TestClient(main.app) as client:
        assert client.get("/docs").status_code == 200


def test_global_exception_handler_masks_errors(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    import core.config
    import main

    importlib.reload(core.config)
    importlib.reload(main)

    @main.app.get("/force-error-for-test")
    def force_error():
        raise RuntimeError("SENSITIVE_DB_PASSWORD_LEAK")

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/force-error-for-test")

    assert response.status_code == 500
    data = response.json()
    
    assert data["detail"]["code"] == "internal_error"
    assert data["detail"]["message"] == "An unexpected error occurred."
    
    assert "SENSITIVE_DB_PASSWORD_LEAK" not in response.text