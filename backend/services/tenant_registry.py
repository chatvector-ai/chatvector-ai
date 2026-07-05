"""
In-memory tenant document registry for Phase 3 tenant isolation.

Design
──────
Write path  : register_tenant_document() is called by upload and chat routes.
Read path   : get_tenant_document_ids() is the public async API:
              - If a full DB scan has already been performed for this tenant
                (tracked by _TENANT_REGISTRY_LOADED), the in-memory set is
                authoritative and subsequent uploads keep it up to date via
                register_tenant_document().
              - If no full scan has occurred yet (e.g. after a restart), the
                function queries the database, merges the results into the
                cache, marks the tenant as fully loaded, and returns the
                merged set.

Completeness guarantee
──────────────────────
The cache is ONLY considered complete for a tenant after a full DB scan
succeeds.  Any document uploaded in the same process lifetime is added to
the cache via register_tenant_document() AFTER the scan has marked the
tenant as fully loaded.  Without this guarantee the following race was
possible:

  1. Restart.  Tenant T has 5 docs in DB; cache is empty.
  2. User uploads 6th document → register_tenant_document() adds doc-6 to
     cache (cache now has 1 entry).
  3. First tenant-scope retrieval → cache is non-empty → DB scan is skipped
     → only doc-6 is searched, docs 1-5 are silently omitted.

With _TENANT_REGISTRY_LOADED the cache is not trusted until the scan is
marked complete, so step 3 triggers the DB scan that returns all 6 docs.

Durable truth
─────────────
The database (documents.tenant_id column) is authoritative.  The in-memory
registry is a performance optimisation for a single-process deployment only.
Multi-process deployments (e.g. multi-worker uvicorn) must query the DB on
every tenant-scope retrieval; set TENANT_REGISTRY_DISABLED=true to disable
the cache and always query the DB.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

# Set TENANT_REGISTRY_DISABLED=true to bypass the cache entirely (recommended
# for multi-worker deployments where the registry cannot be shared).
_REGISTRY_DISABLED: bool = os.getenv("TENANT_REGISTRY_DISABLED", "false").lower() in (
    "1", "true", "yes"
)

_TENANT_DOCUMENTS: dict[str, set[str]] = defaultdict(set)
# Tenants for which a full DB scan has been completed in this process.
_TENANT_REGISTRY_LOADED: set[str] = set()


def register_tenant_document(tenant_id: str | None, doc_id: str) -> None:
    """Associate a document with a tenant in the in-memory cache."""
    if tenant_id and doc_id:
        _TENANT_DOCUMENTS[tenant_id].add(doc_id)


def get_tenant_document_ids_cached(tenant_id: str | None) -> list[str]:
    """Return document IDs from the in-memory cache only (may be incomplete)."""
    if not tenant_id:
        return []
    return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))


async def get_tenant_document_ids(tenant_id: str | None) -> list[str]:
    """Return the complete document ID list for tenant_id.

    The cache is only trusted when it has been explicitly populated via a
    full DB scan (``_TENANT_REGISTRY_LOADED``).  Until then the DB is
    queried, results are merged into the cache, and the tenant is marked
    as fully loaded so future calls skip the query.

    When TENANT_REGISTRY_DISABLED is true the DB is always queried.
    """
    if not tenant_id:
        return []

    if not _REGISTRY_DISABLED and tenant_id in _TENANT_REGISTRY_LOADED:
        # Cache is complete for this tenant.
        return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))

    import db as _db
    try:
        db_doc_ids = await _db.list_tenant_documents(tenant_id)
    except Exception:
        logger.exception(
            "Failed to load tenant document list for tenant=%s from DB; "
            "returning in-memory cache which may be incomplete",
            tenant_id,
        )
        # Return whatever we have in the cache; mark NOT complete so the
        # next request retries the DB.
        return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))

    # Merge DB results into the cache (keeps any in-flight uploads that
    # arrived after the list query started).
    for doc_id in db_doc_ids:
        _TENANT_DOCUMENTS[tenant_id].add(doc_id)

    if not _REGISTRY_DISABLED:
        _TENANT_REGISTRY_LOADED.add(tenant_id)

    return sorted(_TENANT_DOCUMENTS.get(tenant_id, set()))


def invalidate_tenant_cache(tenant_id: str) -> None:
    """Remove a tenant from the loaded set so the next read re-queries the DB.

    Call this after deleting a document so that tenant-scope retrieval does
    not continue to include the deleted document.
    """
    _TENANT_REGISTRY_LOADED.discard(tenant_id)
    _TENANT_DOCUMENTS.pop(tenant_id, None)


def clear_tenant_registry() -> None:
    """Reset all registry state — for tests only."""
    _TENANT_DOCUMENTS.clear()
    _TENANT_REGISTRY_LOADED.clear()
