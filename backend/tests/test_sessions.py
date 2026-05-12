import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

from core.auth import AuthContext
from core.session import Session
from request_utils import make_test_request
from routes.sessions import create_session, get_session, list_sessions, delete_session, SessionCreateRequest


@pytest.mark.asyncio
async def test_create_session():
    with patch("routes.sessions.session_service.create_session") as mock_create:
        mock_create.return_value = Session(id="test-id", tenant_id="tenant-1")
        
        result = await create_session(SessionCreateRequest(session_id="test-id"), auth=AuthContext(tenant_id="tenant-1"))
        
        assert result.id == "test-id"
        assert result.tenant_id == "tenant-1"
        mock_create.assert_called_once_with(session_id="test-id", tenant_id="tenant-1")

@pytest.mark.asyncio
async def test_create_session_conflict():
    with patch("routes.sessions.session_service.create_session", side_effect=ValueError("Conflict")):
        with pytest.raises(HTTPException) as excinfo:
            await create_session(SessionCreateRequest(session_id="test-id"), auth=AuthContext(tenant_id="tenant-1"))
        assert excinfo.value.status_code == 409

@pytest.mark.asyncio
async def test_get_session_success():
    with patch("routes.sessions.session_service.get_session") as mock_get:
        mock_get.return_value = Session(id="test-id", tenant_id="tenant-1")
        
        result = await get_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        
        assert result.id == "test-id"
        assert result.tenant_id == "tenant-1"
        mock_get.assert_called_once_with(session_id="test-id", tenant_id="tenant-1")

@pytest.mark.asyncio
async def test_get_session_not_found():
    with patch("routes.sessions.session_service.get_session", return_value=None):
        with pytest.raises(HTTPException) as excinfo:
            await get_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        assert excinfo.value.status_code == 404

@pytest.mark.asyncio
async def test_list_sessions():
    with patch("routes.sessions.session_service.list_sessions") as mock_list:
        mock_list.return_value = [
            Session(id="test-id-1", tenant_id="tenant-1"),
            Session(id="test-id-2", tenant_id="tenant-1")
        ]
        
        result = await list_sessions(auth=AuthContext(tenant_id="tenant-1"))
        
        assert "sessions" in result
        assert len(result["sessions"]) == 2
        assert result["sessions"][0]["id"] == "test-id-1"
        mock_list.assert_called_once_with(tenant_id="tenant-1")

@pytest.mark.asyncio
async def test_delete_session_success():
    with patch("routes.sessions.session_service.delete_session", return_value=True) as mock_delete:
        await delete_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        mock_delete.assert_called_once_with(session_id="test-id", tenant_id="tenant-1")

@pytest.mark.asyncio
async def test_delete_session_not_found():
    with patch("routes.sessions.session_service.delete_session", return_value=False):
        with pytest.raises(HTTPException) as excinfo:
            await delete_session("test-id", auth=AuthContext(tenant_id="tenant-1"))
        assert excinfo.value.status_code == 404
