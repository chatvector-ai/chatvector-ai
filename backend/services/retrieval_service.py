"""
Retrieval orchestration helpers: Hybrid search (RRF), optional reranking,
and scoped retrieval (session vs tenant).
"""

from __future__ import annotations

from enum import Enum

from db.base import (
    SCORE_TYPE_HYBRID_RRF,
    SCORE_TYPE_RERANKED,
    SCORE_TYPE_VECTOR,
    ChunkMatch,
)
from services.reranker import rerank_chunks_if_enabled

# Standard RRF constant (Cormack et al.)
RRF_K_DEFAULT = 60


class RetrievalScope(str, Enum):
    SESSION = "session"
    TENANT = "tenant"


DEFAULT_RETRIEVAL_SCOPE = RetrievalScope.SESSION


class InvalidRetrievalScopeError(ValueError):
    """Raised when an unsupported retrieval scope value is provided."""

    def __init__(self, scope: str) -> None:
        super().__init__(
            f"Invalid retrieval scope: {scope!r}. Must be one of: session, tenant"
        )
        self.scope = scope


def parse_retrieval_scope(value: str | None) -> RetrievalScope:
    """Parse and validate a retrieval scope string. Defaults to session."""
    if value is None:
        return DEFAULT_RETRIEVAL_SCOPE
    normalized = value.strip().lower()
    try:
        return RetrievalScope(normalized)
    except ValueError as exc:
        raise InvalidRetrievalScopeError(value) from exc


def resolve_scoped_doc_ids(
    scope: RetrievalScope,
    *,
    requested_doc_ids: list[str],
    session_doc_ids: list[str] | None = None,
    tenant_doc_ids: list[str] | None = None,
) -> list[str]:
    """
    Determine which document IDs to search based on retrieval scope.

    Session scope (default):
      - When the session has registered documents, search only those in the
        session set (intersected with any explicitly requested IDs).
      - When the session has no registered documents, use requested IDs
        unchanged for backward compatibility.

    Tenant scope:
      - Search all documents registered to the tenant, ignoring any explicitly
        requested IDs. Cross-tenant leakage is prevented because the registry
        only contains documents registered under the authenticated tenant.
    """
    session_docs = session_doc_ids or []
    tenant_docs = tenant_doc_ids or []

    if scope == RetrievalScope.SESSION:
        if session_docs:
            if requested_doc_ids:
                session_set = set(session_docs)
                return [doc_id for doc_id in requested_doc_ids if doc_id in session_set]
            return list(session_docs)
        return list(requested_doc_ids)

    # Tenant scope — search all documents registered to the tenant.
    if tenant_docs:
        return list(tenant_docs)

    # No tenant registry entries — fall back to requested IDs (dev / single-tenant)
    return list(requested_doc_ids)


def filter_doc_ids_for_tenant(
    doc_ids: list[str],
    tenant_doc_ids: list[str] | None,
    tenant_id: str | None,
) -> list[str]:
    """Remove document IDs that do not belong to the current tenant."""
    if not tenant_id or not tenant_doc_ids:
        return list(doc_ids)
    tenant_set = set(tenant_doc_ids)
    return [doc_id for doc_id in doc_ids if doc_id in tenant_set]


def assert_tenant_isolation(
    doc_ids: list[str],
    tenant_doc_ids: list[str] | None,
    tenant_id: str | None,
) -> None:
    """Raise ValueError if any doc_id is outside the tenant's document set."""
    if not tenant_id or not tenant_doc_ids:
        return
    tenant_set = set(tenant_doc_ids)
    leaked = [doc_id for doc_id in doc_ids if doc_id not in tenant_set]
    if leaked:
        raise ValueError(
            f"Document(s) not accessible for tenant {tenant_id!r}: {sorted(leaked)}"
        )


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = RRF_K_DEFAULT,
    limit: int | None = None,
) -> list[str]:
    """
    Merge multiple ranked lists of chunk IDs using Reciprocal Rank Fusion.

    score(d) = sum over each list L: 1 / (k + rank_L(d))
    """
    scores = reciprocal_rank_fusion_scores(ranked_lists, k=k, limit=limit)
    return list(scores.keys())


def reciprocal_rank_fusion_scores(
    ranked_lists: list[list[str]],
    *,
    k: int = RRF_K_DEFAULT,
    limit: int | None = None,
) -> dict[str, float]:
    """Return fused RRF scores keyed by chunk ID."""
    if not ranked_lists:
        return {}

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)

    ordered = sorted(scores.keys(), key=lambda item_id: scores[item_id], reverse=True)
    if limit is not None:
        ordered = ordered[:limit]
    return {item_id: scores[item_id] for item_id in ordered}


def merge_chunk_matches(
    ranked_ids: list[str],
    matches_by_id: dict[str, ChunkMatch],
) -> list[ChunkMatch]:
    """Return ChunkMatch objects in fused rank order, skipping unknown IDs."""
    merged: list[ChunkMatch] = []
    for chunk_id in ranked_ids:
        match = matches_by_id.get(chunk_id)
        if match is not None:
            merged.append(match)
    return merged


def merge_chunk_matches_with_scores(
    ranked_ids: list[str],
    matches_by_id: dict[str, ChunkMatch],
    scores_by_id: dict[str, float],
    *,
    score_type: str,
) -> list[ChunkMatch]:
    """Return ChunkMatch objects with fused scores and score type metadata."""
    merged: list[ChunkMatch] = []
    for chunk_id in ranked_ids:
        match = matches_by_id.get(chunk_id)
        if match is None:
            continue
        merged.append(
            ChunkMatch(
                id=match.id,
                chunk_text=match.chunk_text,
                document_id=match.document_id,
                embedding=match.embedding,
                created_at=match.created_at,
                similarity=scores_by_id.get(chunk_id, match.similarity),
                score_type=score_type,
                chunk_index=match.chunk_index,
                page_number=match.page_number,
                character_offset_start=match.character_offset_start,
                character_offset_end=match.character_offset_end,
                file_name=match.file_name,
            )
        )
    return merged

__all__ = [
    "DEFAULT_RETRIEVAL_SCOPE",
    "InvalidRetrievalScopeError",
    "RetrievalScope",
    "SCORE_TYPE_HYBRID_RRF",
    "SCORE_TYPE_RERANKED",
    "SCORE_TYPE_VECTOR",
    "assert_tenant_isolation",
    "filter_doc_ids_for_tenant",
    "merge_chunk_matches",
    "merge_chunk_matches_with_scores",
    "parse_retrieval_scope",
    "reciprocal_rank_fusion",
    "reciprocal_rank_fusion_scores",
    "rerank_chunks_if_enabled",
    "resolve_scoped_doc_ids",
]