"""Handoff text parsing for worker and review outputs."""

from __future__ import annotations

import re

from .models import PipelineError

_REVIEW_KEYS = frozenset(
    {
        "Issue",
        "Work",
        "Verdict",
        "Reviewed-SHA",
        "Base-SHA",
        "Tasks-checked",
        "Pytest",
        "Verification",
        "Findings",
        "Notes",
    }
)

_WORKER_KEYS = frozenset(
    {
        "Issue",
        "Work",
        "Status",
        "Tasks",
        "Branch",
        "SHA",
        "Base-SHA",
        "Verification",
        "Assumptions",
        "Blocker",
        "Notes",
        "Pipeline-next",
    }
)

_MULTILINE_KEYS = frozenset({"Findings", "Verification", "Blocker", "Notes"})

_NUMBERED_FINDING = re.compile(r"^\s*\d+\.\s+")
_BULLET_FINDING = re.compile(r"^\s*[-*]\s+")


def parse_handoff(text: str, header: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == header)
    except StopIteration as exc:
        raise PipelineError(f"missing {header}", "handoff") from exc

    header_keys = _REVIEW_KEYS if header == "REVIEW_HANDOFF" else _WORKER_KEYS
    data: dict[str, str] = {}
    multiline_key: str | None = None
    multiline_lines: list[str] = []

    def flush_multiline() -> None:
        nonlocal multiline_key, multiline_lines
        if multiline_key is None:
            return
        existing = data.get(multiline_key, "")
        block = "\n".join(multiline_lines).strip()
        if existing and block:
            data[multiline_key] = existing + "\n" + block
        elif block:
            data[multiline_key] = block
        elif existing:
            data[multiline_key] = existing
        multiline_key = None
        multiline_lines = []

    def is_known_key_line(line: str) -> bool:
        stripped = line.strip()
        if ":" not in stripped:
            return False
        key = stripped.split(":", 1)[0].strip()
        return key in header_keys

    def is_finding_continuation(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if _NUMBERED_FINDING.match(stripped) or _BULLET_FINDING.match(stripped):
            return True
        if multiline_key == "Findings" and multiline_lines:
            return True
        return False

    index = start + 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            if multiline_key and multiline_lines:
                index += 1
                continue
            flush_multiline()
            if data:
                break
            index += 1
            continue

        if line.startswith((" ", "\t")) and multiline_key:
            multiline_lines.append(stripped)
            index += 1
            continue

        if multiline_key:
            if is_finding_continuation(line) or not is_known_key_line(line):
                multiline_lines.append(stripped)
                index += 1
                continue
            flush_multiline()

        if ":" not in line:
            break

        key, value = line.split(":", 1)
        key = key.strip()
        if key not in header_keys:
            if multiline_key == "Findings" or data.get("Findings") is not None:
                # Numbered lines like `1. path: detail` are not top-level keys.
                if _NUMBERED_FINDING.match(stripped):
                    multiline_key = "Findings"
                    multiline_lines = [stripped]
                    index += 1
                    continue
            break

        value = value.strip()
        data[key] = value
        if key in _MULTILINE_KEYS:
            multiline_key = key
            multiline_lines = []
            if value:
                multiline_lines.append(value)
        index += 1

    flush_multiline()

    if not data:
        raise PipelineError(f"empty {header}", "handoff")
    return data
