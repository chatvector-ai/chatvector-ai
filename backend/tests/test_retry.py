"""
Tests for the retry utility.
Tests both the retry mechanism and error classification.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from utils.retry import retry_async, is_transient_error

@pytest.mark.asyncio
async def test_retry_success_on_third_try():
    """Should retry until success."""
    mock_func = AsyncMock()
    mock_func.side_effect = [
        Exception("connection timeout"),
        Exception("connection reset"), 
        "success"
    ]
    
    with patch('utils.retry.is_transient_error', return_value=True):
        with patch('utils.retry.asyncio.sleep', new_callable=AsyncMock):
            result = await retry_async(mock_func, max_retries=3, timeout=None)
    
    assert result == "success"
    assert mock_func.call_count == 3

@pytest.mark.asyncio
async def test_retry_fails_on_permanent_error():
    """Should fail immediately on permanent errors."""
    mock_func = AsyncMock()
    mock_func.side_effect = Exception("constraint violation")
    
    with patch('utils.retry.is_transient_error', return_value=False):
        with pytest.raises(Exception, match="constraint violation"):
            await retry_async(mock_func, max_retries=3, timeout=None)
    
    assert mock_func.call_count == 1  # Only called once

@pytest.mark.asyncio
async def test_retry_exhaustion():
    """Should raise after max retries."""
    mock_func = AsyncMock()
    mock_func.side_effect = Exception("timeout")
    
    with patch('utils.retry.is_transient_error', return_value=True):
        with patch('utils.retry.asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(Exception, match="timeout"):
                await retry_async(mock_func, max_retries=2, timeout=None)
    
    assert mock_func.call_count == 2

@pytest.mark.asyncio
async def test_exponential_backoff():
    """Should wait with full jitter between retries (delay in [0, cap])."""
    mock_func = AsyncMock()
    mock_func.side_effect = [Exception("timeout"), Exception("timeout"), "success"]
    
    with patch('utils.retry.is_transient_error', return_value=True):
        with patch('utils.retry.asyncio.sleep') as mock_sleep:
            await retry_async(
                mock_func, 
                max_retries=3,
                base_delay=1.0,
                backoff=2.0,
                timeout=None,
            )
    
    assert mock_sleep.call_count == 2
    assert 0.0 <= mock_sleep.call_args_list[0].args[0] <= 1.0
    assert 0.0 <= mock_sleep.call_args_list[1].args[0] <= 2.0

@pytest.mark.asyncio
async def test_timeout_error_retried_when_attempts_remain():
    """asyncio.TimeoutError from wait_for should retry with jitter sleep."""
    wf_calls = 0
    mock_inner = AsyncMock(return_value="ok")

    async def wait_for_impl(coro, timeout=None):
        nonlocal wf_calls
        wf_calls += 1
        if wf_calls < 3:
            coro.close()
            raise asyncio.TimeoutError()
        return await coro

    with patch("utils.retry.asyncio.wait_for", side_effect=wait_for_impl):
        with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await retry_async(
                mock_inner,
                max_retries=3,
                base_delay=1.0,
                backoff=2.0,
                timeout=30.0,
                func_name="test.wait_for_retries",
            )

    assert result == "ok"
    assert mock_inner.call_count == 3
    assert mock_sleep.call_count == 2
    assert 0.0 <= mock_sleep.call_args_list[0].args[0] <= 1.0
    assert 0.0 <= mock_sleep.call_args_list[1].args[0] <= 2.0

@pytest.mark.asyncio
async def test_timeout_error_after_max_retries_exhausted():
    """asyncio.TimeoutError should propagate after the final attempt."""

    async def always_timeout(coro, timeout=None):
        coro.close()
        raise asyncio.TimeoutError()

    mock_inner = AsyncMock(return_value="never")

    with patch("utils.retry.asyncio.wait_for", side_effect=always_timeout):
        with patch("utils.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.TimeoutError):
                await retry_async(
                    mock_inner,
                    max_retries=2,
                    base_delay=0.01,
                    backoff=2.0,
                    timeout=1.0,
                    func_name="test.always_timeout",
                )

    assert mock_inner.call_count == 2

@pytest.mark.asyncio
async def test_timeout_none_skips_wait_for():
    """timeout=None should call func directly without asyncio.wait_for."""
    mock_func = AsyncMock(return_value="done")
    with patch("utils.retry.asyncio.wait_for") as mock_wait_for:
        result = await retry_async(mock_func, timeout=None)
    mock_wait_for.assert_not_called()
    assert result == "done"
    assert mock_func.call_count == 1

def test_is_transient_error_timeout_error():
    """asyncio.TimeoutError has empty str(); classify by type."""
    assert is_transient_error(asyncio.TimeoutError()) is True

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
