"""
In-memory tenant document registry for Phase 3 tenant isolation.

Documents are registered at upload time. In a future phase this would
move to PostgreSQL alongside a tenant_id column on documents.
"""

from __future__ import annotations

from collections import defaultdict

_TENANT_DOCUMENTS: dict[str, set[str]] = defaultdict(set)


def register_tenant_document(tenant_id: str | None, doc_id: str) -> None:
    """Associate a document with a tenant."""
    if tenant_id and doc_id:
        _TENANT_DOCUMENTS[tenant_id].add(doc_id)


def get_tenant_document_ids(tenant_id: str | None) -> list[str]:
    """Return sorted document IDs belonging to a tenant."""
    if not tenant_id:
        return []
    return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))


def clear_tenant_registry() -> None:
    """Reset registry — for tests only."""
    _TENANT_DOCUMENTS.clear()
