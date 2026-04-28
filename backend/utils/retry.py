"""
Async retry with per-attempt timeout, full jitter on backoff, and transient-error
filtering (message patterns + asyncio.TimeoutError). Non-transient errors fail fast.

Example:

    result = await retry_async(
        lambda: service.save(payload),
        max_retries=3,      # up to 3 retries after the first attempt (4 total)
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name="service.save",
    )
"""

import asyncio
import logging
import random
from typing import Type, Tuple, Callable, Any, Optional

logger = logging.getLogger(__name__)

TRANSIENT_DB_ERROR_PATTERNS = [
    "timeout",
    "connection",
    "deadlock",
    "temporarily",
    "too many clients",
    "network",
    "reset",
    "broken pipe",
    "unavailable",
    "quota",
    "resource_exhausted",
    "rate limit",
]


def is_transient_error(exception: Exception) -> bool:
    if isinstance(exception, asyncio.TimeoutError):
        return True

    # Provider-layer transient errors (rate limits, timeouts) are always retryable
    # regardless of which provider is active.
    from services.providers.base import ProviderRateLimitError, ProviderTimeoutError

    if isinstance(exception, (ProviderRateLimitError, ProviderTimeoutError)):
        return True

    error_str = str(exception).lower()
    logger.debug(f"Checking if error is transient: {error_str}")

    for pattern in TRANSIENT_DB_ERROR_PATTERNS:
        if pattern in error_str:
            logger.debug(f"Error matched transient pattern: {pattern}")
            return True

    return False


async def retry_async(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    timeout: float | None = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    func_name: Optional[str] = None,
) -> Any:
    if func_name is None:
        func_name = getattr(func, '__name__', 'unknown_function')

    last_exception = None
    max_attempts = max_retries + 1

    for attempt in range(max_attempts):
        try:
            if timeout is not None:
                return await asyncio.wait_for(func(), timeout=timeout)
            else:
                return await func()
        except asyncio.TimeoutError as e:
            last_exception = e
            if attempt == max_attempts - 1:
                logger.error(
                    f"Final attempt timed out for {func_name}",
                    extra={
                        "error_type": "TimeoutError",
                        "timeout_seconds": timeout,
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                    },
                )
                raise
            cap = base_delay * (backoff ** attempt)
            delay = random.uniform(0, cap)
            logger.warning(
                f"Attempt {attempt + 1}/{max_attempts} timed out for "
                f"{func_name} after {timeout}s, retrying in {delay:.2f}s",
                extra={
                    "error_type": "TimeoutError",
                    "timeout_seconds": timeout,
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "next_retry_delay": delay,
                },
            )
            await asyncio.sleep(delay)
            continue
        except retryable_exceptions as e:
            last_exception = e

            if not is_transient_error(e):
                logger.error(
                    f"Non-transient error in {func_name}, not retrying",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                    }
                )
                raise

            if attempt == max_attempts - 1:
                logger.error(
                    f"Final attempt failed for {func_name}",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                    }
                )
                raise

            cap = base_delay * (backoff ** attempt)
            delay = random.uniform(0, cap)

            logger.warning(
                f"Transient error in {func_name}, "
                f"retrying in {delay:.2f}s (attempt {attempt + 1}/{max_attempts})",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "next_retry_delay": delay,
                }
            )

            await asyncio.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError(f"Unexpected state in retry_async for {func_name}")
