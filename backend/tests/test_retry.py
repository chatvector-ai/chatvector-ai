"""
Tests for the retry utility.
Tests both the retry mechanism and error classification.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from app.utils.retry import retry_async, is_transient_error

@pytest.mark.asyncio
async def test_retry_success_on_third_try():
    """Should retry until success."""
    mock_func = AsyncMock()
    mock_func.side_effect = [
        Exception("connection timeout"),
        Exception("connection reset"), 
        "success"
    ]
    
    with patch('app.utils.retry.is_transient_error', return_value=True):
        result = await retry_async(mock_func, max_retries=3)
    
    assert result == "success"
    assert mock_func.call_count == 3

@pytest.mark.asyncio
async def test_retry_fails_on_permanent_error():
    """Should fail immediately on permanent errors."""
    mock_func = AsyncMock()
    mock_func.side_effect = Exception("constraint violation")
    
    with patch('app.utils.retry.is_transient_error', return_value=False):
        with pytest.raises(Exception, match="constraint violation"):
            await retry_async(mock_func, max_retries=3)
    
    assert mock_func.call_count == 1  # Only called once

@pytest.mark.asyncio
async def test_retry_exhaustion():
    """Should raise after max retries."""
    mock_func = AsyncMock()
    mock_func.side_effect = Exception("timeout")
    
    with patch('app.utils.retry.is_transient_error', return_value=True):
        with pytest.raises(Exception, match="timeout"):
            await retry_async(mock_func, max_retries=2)
    
    assert mock_func.call_count == 2

@pytest.mark.asyncio
async def test_exponential_backoff():
    """Should wait increasingly longer between retries."""
    mock_func = AsyncMock()
    mock_func.side_effect = [Exception("timeout"), Exception("timeout"), "success"]
    
    with patch('app.utils.retry.is_transient_error', return_value=True):
        with patch('asyncio.sleep') as mock_sleep:
            await retry_async(
                mock_func, 
                max_retries=3,
                base_delay=1.0,
                backoff=2.0
            )
    
    # Should sleep 1s then 2s
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)

def test_transient_error_detection():
    """Test that transient errors are correctly identified."""
    # Should be transient
    assert is_transient_error(Exception("connection timeout")) is True
    assert is_transient_error(Exception("database deadlock detected")) is True
    assert is_transient_error(Exception("network unreachable")) is True
    
    # Should not be transient
    assert is_transient_error(Exception("constraint violation")) is False
    assert is_transient_error(Exception("invalid input syntax")) is False
    assert is_transient_error(Exception("permission denied")) is False