"""
Tests for the database factory.
Ensures the right service is returned based on environment.
"""
import pytest
from unittest.mock import patch

import db
from db import get_db_service


@pytest.fixture(autouse=True)
def reset_db_service_cache():
    """Reset cached DB service between tests."""
    db.db_service = None
    yield
    db.db_service = None

@pytest.mark.asyncio
async def test_factory_returns_sqlalchemy_in_dev():
    """Should return SQLAlchemyService when APP_ENV=development."""
    with patch('core.config.config.APP_ENV', 'development'):  # Changed from app.config
        service = get_db_service()
        from db.sqlalchemy_service import SQLAlchemyService  # Changed from app.db
        assert isinstance(service, SQLAlchemyService)

@pytest.mark.asyncio
async def test_factory_returns_supabase_in_prod():
    """Should return SupabaseService when APP_ENV=production."""
    with patch('core.config.config.APP_ENV', 'production'):  # Changed from app.config
        service = get_db_service()
        from db.supabase_service import SupabaseService  # Changed from app.db
        assert isinstance(service, SupabaseService)

@pytest.mark.asyncio
async def test_factory_caches_service():
    """Should return same instance on subsequent calls."""
    with patch('core.config.config.APP_ENV', 'development'):  # Changed from app.config
        service1 = get_db_service()
        service2 = get_db_service()
        assert service1 is service2  # Same instance