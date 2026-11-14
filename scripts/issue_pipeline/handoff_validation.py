"""Validation helpers for worker and review handoff fields."""

from __future__ import annotations

import re

_PYTEST_PREFIX = re.compile(r"^pytest:\s*", re.I)
_PASSED_SUMMARY = re.compile(
    r"(?:^passed(?:\s|$)|\b\d+\s+passed\b)",
    re.I,
)
_FAILED = re.compile(r"\bfailed\b", re.I)


def pytest_result_passed(text: str | None) -> bool:
    """Accept normalized pytest summaries such as ``1434 passed, 4 skipped``."""

    raw = (text or "").strip()
    if not raw:
        return False
    cleaned = _PYTEST_PREFIX.sub("", raw).strip()
    if _FAILED.search(cleaned):
        return False
    return bool(_PASSED_SUMMARY.search(cleaned))
