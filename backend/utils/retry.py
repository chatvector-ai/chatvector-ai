import asyncio
import logging
from typing import Type, Tuple, Callable, Any, Optional

logger = logging.getLogger(__name__)

# Common transient database errors
# These are substrings to match against error messages
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
]

# Supabase specific error codes (if you find them)
# TRANSIENT_ERROR_CODES = ["40P01", "55P03", "57P01"]  # Example: deadlock, lock, etc.

def is_transient_error(exception: Exception) -> bool:
    """
    Determine if an error is retryable.
    
    Returns:
        True if the error is transient and should be retried,
        False if it's permanent and should fail immediately.
    """
    error_str = str(exception).lower()
    
    # Log the full error for debugging
    logger.debug(f"Checking if error is transient: {error_str}")
    
    # Check against transient patterns
    for pattern in TRANSIENT_DB_ERROR_PATTERNS:
        if pattern in error_str:
            logger.debug(f"Error matched transient pattern: {pattern}")
            return True
    
    # If you add error code checking:
    # if hasattr(exception, 'code') and exception.code in TRANSIENT_ERROR_CODES:
    #     return True
    
    return False

async def retry_async(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    func_name: Optional[str] = None,
) -> Any:
    """
    Retry an async function with exponential backoff.
    
    Args:
        func: Async function to retry (must be a callable with no args)
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        backoff: Multiplier for exponential backoff
        retryable_exceptions: Tuple of exception types that might be retryable
        func_name: Optional function name for logging (auto-detected if not provided)
    
    Returns:
        Result of the function call
    
    Raises:
        The last exception if all retries fail or error is permanent
    
    Example:
        result = await retry_async(
            lambda: insert_chunks_batch(doc_id, chunks),
            max_retries=3,
            base_delay=1.0
        )
    """
    if func_name is None:
        func_name = getattr(func, '__name__', 'unknown_function')
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func()
        except retryable_exceptions as e:
            last_exception = e
            
            # Check if this error is retryable
            if not is_transient_error(e):
                logger.error(
                    f"Non-transient error in {func_name}, not retrying",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                    }
                )
                raise
            
            # If this was our last attempt, raise the exception
            if attempt == max_retries - 1:
                logger.error(
                    f"Final retry attempt failed for {func_name}",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                    }
                )
                raise
            
            # Calculate delay with exponential backoff
            delay = base_delay * (backoff ** attempt)
            
            logger.warning(
                f"Transient error in {func_name}, "
                f"retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "next_retry_delay": delay,
                }
            )
            
            await asyncio.sleep(delay)
    
    # This should never be reached, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError(f"Unexpected state in retry_async for {func_name}")