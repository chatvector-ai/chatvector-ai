"""
In-memory tenant document registry for Phase 3 tenant isolation.

Documents are registered at upload and chat time for O(1) look-ups
during the same process lifetime.  On server restart the in-memory
registry is empty, so any code that needs an authoritative list of a
tenant's documents must fall back to a DB query via
``get_tenant_document_ids``.

Design:
  - Write path  : register_tenant_document() is called by upload and chat routes.
  - Read path   : get_tenant_document_ids() returns the in-memory set when it is
                  non-empty; otherwise it queries the database so that retrieval
                  works correctly after a restart.
  - Durable truth: the database (documents.tenant_id column) is authoritative.
                   The in-memory registry is a performance cache only.
"""

from __future__ import annotations

from collections import defaultdict

import logging

logger = logging.getLogger(__name__)

_TENANT_DOCUMENTS: dict[str, set[str]] = defaultdict(set)


def register_tenant_document(tenant_id: str | None, doc_id: str) -> None:
    """Associate a document with a tenant in the in-memory cache."""
    if tenant_id and doc_id:
        _TENANT_DOCUMENTS[tenant_id].add(doc_id)


def get_tenant_document_ids_cached(tenant_id: str | None) -> list[str]:
    """Return document IDs from the in-memory cache only (may be empty after restart)."""
    if not tenant_id:
        return []
    return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))


async def get_tenant_document_ids(tenant_id: str | None) -> list[str]:
    """Return document IDs for tenant_id.

    Falls back to a database query when the in-memory cache is empty so that
    retrieval works correctly after a server restart.  The DB result is written
    back into the cache for subsequent in-process calls.
    """
    if not tenant_id:
        return []

    cached = _TENANT_DOCUMENTS.get(tenant_id)
    if cached:
        return sorted(cached)

    import db as _db
    try:
        doc_ids = await _db.list_tenant_documents(tenant_id)
    except Exception:
        logger.exception(
            "Failed to load tenant document list for tenant=%s from DB; "
            "returning empty list — retrieval may miss documents from before restart",
            tenant_id,
        )
        return []

    for doc_id in doc_ids:
        _TENANT_DOCUMENTS[tenant_id].add(doc_id)

    return sorted(doc_ids)


def clear_tenant_registry() -> None:
    """Reset registry — for tests only."""
    _TENANT_DOCUMENTS.clear()
