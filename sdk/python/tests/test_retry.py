"""Unit tests for the internal ``retry_sync`` helper."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from chatvector._retry import WantsRetry, retry_sync


class RetrySyncTests(unittest.TestCase):
    """Exercise ``retry_sync`` timing and control flow."""

    def test_success_on_first_attempt(self) -> None:
        """A successful ``func`` should return immediately without sleeping."""
        calls = [0]

        def func() -> str:
            calls[0] += 1
            return "ok"

        with patch("chatvector._retry.time.sleep") as mock_sleep:
            result = retry_sync(func, max_retries=3, base_delay=1.0, backoff=2.0)

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 1)
        mock_sleep.assert_not_called()

    def test_retry_after_failure_then_success(self) -> None:
        """Failures that raise ``WantsRetry`` should be retried until success."""
        calls = [0]

        def func() -> int:
            calls[0] += 1
            if calls[0] < 3:
                raise WantsRetry(0.0)
            return 42

        with patch("chatvector._retry.time.sleep", return_value=None) as mock_sleep:
            result = retry_sync(func, max_retries=5, base_delay=0.5, backoff=2.0)

        self.assertEqual(result, 42)
        self.assertEqual(calls[0], 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(mock_sleep.call_args_list[0].args[0], 0.5)
        self.assertEqual(mock_sleep.call_args_list[1].args[0], 1.0)

    def test_max_retries_exhausted_raises_last_exception(self) -> None:
        """After the final attempt, ``WantsRetry`` should propagate."""
        calls = [0]

        def func() -> None:
            calls[0] += 1
            raise WantsRetry(0.0)

        with patch("chatvector._retry.time.sleep", return_value=None) as mock_sleep:
            with self.assertRaises(WantsRetry):
                retry_sync(func, max_retries=3, base_delay=1.0, backoff=2.0)

        self.assertEqual(calls[0], 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_exponential_backoff_uses_base_delay_and_backoff(self) -> None:
        """Sleep durations should follow ``base_delay * (backoff ** attempt)``."""
        calls = [0]

        def func() -> str:
            calls[0] += 1
            if calls[0] < 4:
                raise WantsRetry(0.0)
            return "done"

        with patch("chatvector._retry.time.sleep", return_value=None) as mock_sleep:
            retry_sync(func, max_retries=4, base_delay=0.1, backoff=3.0)

        self.assertEqual(mock_sleep.call_count, 3)
        self.assertAlmostEqual(mock_sleep.call_args_list[0].args[0], 0.1)
        self.assertAlmostEqual(mock_sleep.call_args_list[1].args[0], 0.3)
        self.assertAlmostEqual(mock_sleep.call_args_list[2].args[0], 0.9)

    def test_non_retry_exception_propagates_immediately(self) -> None:
        """Exceptions other than ``WantsRetry`` should not be retried."""
        calls = [0]

        def func() -> None:
            calls[0] += 1
            raise ValueError("no retry")

        with patch("chatvector._retry.time.sleep", return_value=None) as mock_sleep:
            with self.assertRaises(ValueError):
                retry_sync(func, max_retries=5, base_delay=1.0, backoff=2.0)

        self.assertEqual(calls[0], 1)
        mock_sleep.assert_not_called()

    def test_min_additional_delay_extends_sleep(self) -> None:
        """``WantsRetry(min_additional_delay=...)`` should floor the sleep duration."""
        calls = [0]

        def func() -> str:
            calls[0] += 1
            if calls[0] == 1:
                raise WantsRetry(5.0)
            return "ok"

        with patch("chatvector._retry.time.sleep", return_value=None) as mock_sleep:
            result = retry_sync(func, max_retries=3, base_delay=0.5, backoff=2.0)

        self.assertEqual(result, "ok")
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(mock_sleep.call_args_list[0].args[0], 5.0)


if __name__ == "__main__":
    unittest.main()
