"""
Tests for the database factory.
Ensures the right service is returned based on environment.
"""
import pytest
from unittest.mock import patch

from db import get_db_service

@pytest.mark.asyncio
async def test_factory_returns_sqlalchemy_in_dev():
    """Should return SQLAlchemyService when APP_ENV=development."""
    with patch('app.config.config.APP_ENV', 'development'):
        service = get_db_service()
        from app.db.sqlalchemy_service import SQLAlchemyService
        assert isinstance(service, SQLAlchemyService)

@pytest.mark.asyncio
async def test_factory_returns_supabase_in_prod():
    """Should return SupabaseService when APP_ENV=production."""
    with patch('app.config.config.APP_ENV', 'production'):
        service = get_db_service()
        from app.db.supabase_service import SupabaseService
        assert isinstance(service, SupabaseService)

@pytest.mark.asyncio
async def test_factory_caches_service():
    """Should return same instance on subsequent calls."""
    with patch('app.config.config.APP_ENV', 'development'):
        service1 = get_db_service()
        service2 = get_db_service()
        assert service1 is service2  # Same instance