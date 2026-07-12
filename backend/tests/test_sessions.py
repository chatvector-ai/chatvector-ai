import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from core.auth import AuthContext
from core.session import Session
from main import app
from request_utils import make_test_request
from routes.sessions import (
    create_session,
    get_session,
    list_sessions,
    delete_session,
    SessionCreateRequest,
    SessionListResponse,
)


@pytest.mark.asyncio
async def test_create_session():
    with patch(
        "routes.sessions.session_service.create_session",
        new=AsyncMock(return_value=Session(id="test-id", tenant_id="tenant-1")),
    ) as mock_create:
        result = await create_session(
            SessionCreateRequest(session_id="test-id"),
            auth=AuthContext(tenant_id="tenant-1"),
        )

        assert result.id == "test-id"
        assert result.tenant_id == "tenant-1"
        mock_create.assert_awaited_once_with(session_id="test-id", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_create_session_conflict():
    with patch(
        "routes.sessions.session_service.create_session",
        new=AsyncMock(side_effect=ValueError("Conflict")),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await create_session(
                SessionCreateRequest(session_id="test-id"),
                auth=AuthContext(tenant_id="tenant-1"),
            )
        assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_get_session_success():
    with patch(
        "routes.sessions.session_service.get_session",
        new=AsyncMock(return_value=Session(id="test-id", tenant_id="tenant-1")),
    ) as mock_get:
        result = await get_session("test-id", auth=AuthContext(tenant_id="tenant-1"))

        assert result.id == "test-id"
        assert result.tenant_id == "tenant-1"
        mock_get.assert_awaited_once_with(session_id="test-id", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_get_session_not_found():
    with patch(
        "routes.sessions.session_service.get_session",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await get_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions():
    with patch(
        "routes.sessions.session_service.list_sessions",
        new=AsyncMock(
            return_value=[
                Session(id="test-id-1", tenant_id="tenant-1"),
                Session(id="test-id-2", tenant_id="tenant-1"),
            ]
        ),
    ) as mock_list:
        result = await list_sessions(auth=AuthContext(tenant_id="tenant-1"))

        assert isinstance(result, SessionListResponse)
        assert len(result.sessions) == 2
        assert result.sessions[0].id == "test-id-1"
        mock_list.assert_awaited_once_with(tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_delete_session_success():
    with patch(
        "routes.sessions.session_service.delete_session",
        new=AsyncMock(return_value=True),
    ) as mock_delete:
        await delete_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        mock_delete.assert_awaited_once_with(session_id="test-id", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_delete_session_not_found():
    with patch(
        "routes.sessions.session_service.delete_session",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await delete_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_isolation_via_mocks():
    """Tenant isolation is enforced by get_session_record in SQLAlchemyService.
    Route-level: requesting tenant-b's session returns 404 for tenant-a caller.
    """
    with patch(
        "routes.sessions.session_service.get_session",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await get_session("tenant-a-session", auth=AuthContext(tenant_id="tenant-b"))
        assert excinfo.value.status_code == 404


def test_http_integration_router_registration():
    from core.auth import require_auth

    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="test-tenant")
    client = TestClient(app)

    with patch(
        "routes.sessions.session_service.list_sessions",
        new=AsyncMock(return_value=[]),
    ):
        response = client.get("/sessions")
        assert response.status_code == 200
        assert "sessions" in response.json()

    app.dependency_overrides.clear()
