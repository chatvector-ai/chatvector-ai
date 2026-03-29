"""Internal synchronous retry helper with exponential backoff."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class WantsRetry(Exception):
    """Raised by a retried callable to request another attempt after sleeping."""

    __slots__ = ("min_additional_delay",)

    def __init__(self, min_additional_delay: float = 0.0) -> None:
        super().__init__()
        self.min_additional_delay = max(0.0, float(min_additional_delay))


def retry_sync(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    func_name: Optional[str] = None,
) -> T:
    """
    Retry a synchronous callable with exponential backoff.

    Retries when ``func`` raises :class:`WantsRetry`. Sleeps
    ``max(base_delay * (backoff ** attempt), exc.min_additional_delay)`` before the
    next attempt so callers can raise ``WantsRetry(seconds)`` to honor a minimum
    delay (for example from ``Retry-After``) without putting protocol logic here.

    Args:
        func: Callable to invoke (no arguments).
        max_retries: Total number of attempts (same semantics as ``retry_async``).
        base_delay: Initial delay factor in seconds.
        backoff: Exponential multiplier applied per retry attempt.
        func_name: Optional label for logging.

    Returns:
        The return value of ``func``.

    Raises:
        The last exception if all attempts fail.
    """
    if func_name is None:
        func_name = getattr(func, "__name__", "unknown_function")

    last_exception: BaseException | None = None

    for attempt in range(max_retries):
        try:
            return func()
        except WantsRetry as e:
            last_exception = e
            if attempt == max_retries - 1:
                logger.error(
                    "Final retry attempt failed for %s",
                    func_name,
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                    },
                )
                raise

            extra = float(e.min_additional_delay or 0.0)
            delay = max(base_delay * (backoff**attempt), extra)

            logger.warning(
                "Transient error in %s, retrying in %.2fs (attempt %d/%d)",
                func_name,
                delay,
                attempt + 1,
                max_retries,
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "next_retry_delay": delay,
                },
            )

            time.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError(f"Unexpected state in retry_sync for {func_name}")
