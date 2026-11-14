"""Review findings validation for correction handoffs."""

from __future__ import annotations

import re

from .escalation import normalize_findings

_VERDICT_ONLY = re.compile(r"^(fix\s+first|not\s+close)\.?$", re.I)
_PLACEHOLDERS = frozenset(
    {
        "",
        "none",
        "n/a",
        "na",
        "tbd",
        "todo",
        "fix first",
        "not close",
        "see above",
        "see review",
    }
)


def validate_actionable_findings(findings: str | None, *, verdict: str) -> str | None:
    """Return an error message when findings are not substantive; else None."""

    raw = (findings or "").strip()
    if not raw:
        return "Findings are required for FIX FIRST and NOT CLOSE reviews"
    lowered = raw.lower()
    if lowered in _PLACEHOLDERS or lowered == verdict.strip().lower():
        return "Findings must be substantive, not empty or verdict-only"
    if _VERDICT_ONLY.match(raw):
        return "Findings must describe actionable defects, not repeat the verdict"
    tokens = normalize_findings(raw)
    if tokens:
        return None
    # Prose without bullet structure: require minimum substance and a defect signal.
    if len(raw) < 32:
        return "Findings are too short to be actionable"
    if not re.search(r"[a-z]", raw, re.I):
        return "Findings must describe actionable defects"
    return None
