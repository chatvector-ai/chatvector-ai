"""Build and persist ingestion job metadata for document status/SSE payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.base import REPLACEMENT_FAILED

# Documented fallback when an error cannot be classified (see _classify_ingestion_error).
FALLBACK_FAILURE_CLASS = "pipeline_error"

_PUBLIC_JOB_KEYS = (
    "enqueued_at",
    "started_at",
    "completed_at",
    "attempt",
    "durations_ms",
    "failure_class",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def failure_class_from_error(error: dict | None) -> str:
    if not error:
        return FALLBACK_FAILURE_CLASS
    code = error.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return FALLBACK_FAILURE_CLASS


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


def compute_durations_ms(stored: dict[str, Any]) -> dict[str, int] | None:
    enqueued = parse_iso_timestamp(stored.get("enqueued_at"))
    started = parse_iso_timestamp(stored.get("started_at"))
    completed = parse_iso_timestamp(stored.get("completed_at"))
    total = _duration_ms(enqueued, completed)
    if total is None:
        total = _duration_ms(started, completed)
    if total is None:
        return None
    return {"total": total}


def finalize_stored_job_metadata(stored: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted job_metadata after a merge."""
    result = dict(stored)
    attempt = result.get("attempt")
    if attempt is not None:
        try:
            result["attempt"] = int(attempt)
        except (TypeError, ValueError):
            result.pop("attempt", None)

    durations = compute_durations_ms(result)
    if durations is not None:
        result["durations_ms"] = durations
    return result


def patch_enqueued(*, enqueued_at: datetime | None = None, attempt: int) -> dict[str, Any]:
    return {
        "enqueued_at": isoformat_utc(enqueued_at or utc_now()),
        "attempt": max(1, int(attempt)),
    }


def patch_started(*, started_at: datetime | None = None) -> dict[str, Any]:
    return {"started_at": isoformat_utc(started_at or utc_now())}


def patch_terminal_success(*, completed_at: datetime | None = None) -> dict[str, Any]:
    return {"completed_at": isoformat_utc(completed_at or utc_now())}


def patch_terminal_failure(
    error: dict | None,
    *,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "completed_at": isoformat_utc(completed_at or utc_now()),
        "failure_class": failure_class_from_error(error),
    }


def merge_job_metadata(existing: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    base = dict(existing or {})
    base.update(patch)
    return finalize_stored_job_metadata(base)


def build_public_job(
    job_metadata: dict[str, Any] | None,
    *,
    status: str | None,
    status_detail: str | None,
    error: dict | None,
) -> dict[str, Any] | None:
    if not job_metadata:
        return None

    public: dict[str, Any] = {}
    for key in _PUBLIC_JOB_KEYS:
        if key == "failure_class":
            continue
        if key in job_metadata and job_metadata[key] is not None:
            public[key] = job_metadata[key]

    if not public and status not in ("failed",) and status_detail != REPLACEMENT_FAILED:
        return None

    terminal_failed = status == "failed" or status_detail == REPLACEMENT_FAILED
    if terminal_failed:
        failure_class = job_metadata.get("failure_class")
        if not failure_class:
            failure_class = failure_class_from_error(error)
        public["failure_class"] = failure_class

    if not public:
        return None
    return public


def build_document_status_response(
    document_id: str,
    status_payload: dict[str, Any],
    *,
    queue_position: int | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "document_id": str(document_id),
        "status": status_payload.get("status"),
        "chunks": status_payload.get("chunks"),
        "metadata": status_payload.get("metadata") or {},
        "created_at": status_payload.get("created_at"),
        "updated_at": status_payload.get("updated_at"),
    }

    if status_payload.get("status_detail") is not None:
        response["status_detail"] = status_payload["status_detail"]

    if status_payload.get("error") is not None:
        response["error"] = status_payload["error"]

    # Present when the document row has a name. Omitted when the payload has
    # no file_name so older callers still receive the rest of the status.
    file_name = status_payload.get("file_name")
    if isinstance(file_name, str):
        response["file_name"] = file_name

    if queue_position is not None:
        response["queue_position"] = queue_position

    job = build_public_job(
        status_payload.get("job_metadata"),
        status=status_payload.get("status"),
        status_detail=status_payload.get("status_detail"),
        error=status_payload.get("error"),
    )
    if job is not None:
        response["job"] = job

    return response
