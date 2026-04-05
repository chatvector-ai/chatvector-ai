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
