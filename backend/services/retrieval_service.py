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
from services.reranker import rerank_chunks_if_enabled, rerank_chunks_with_debug

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


def _merge_hybrid_chunk_match(
    existing: ChunkMatch | None,
    incoming: ChunkMatch,
) -> ChunkMatch:
    """Combine vector and keyword rows for the same chunk ID."""
    if existing is None:
        return incoming
    return ChunkMatch(
        id=existing.id,
        chunk_text=existing.chunk_text,
        document_id=existing.document_id,
        embedding=existing.embedding,
        created_at=existing.created_at,
        similarity=existing.similarity,
        score_type=existing.score_type,
        vector_score=(
            existing.vector_score
            if existing.vector_score is not None
            else incoming.vector_score
        ),
        full_text_score=(
            existing.full_text_score
            if existing.full_text_score is not None
            else incoming.full_text_score
        ),
        rrf_score=existing.rrf_score,
        chunk_index=existing.chunk_index,
        page_number=existing.page_number,
        page_end=existing.page_end,
        character_offset_start=existing.character_offset_start,
        character_offset_end=existing.character_offset_end,
        file_name=existing.file_name,
    )


def _global_component_rank(
    matches: list[ChunkMatch],
    score_attr: str,
) -> list[str]:
    """Order chunk IDs by a component score across the request candidate set."""
    ordered = sorted(
        matches,
        key=lambda match: (
            getattr(match, score_attr) is None,
            -float(getattr(match, score_attr) or 0.0),
            match.document_id is None,
            "" if match.document_id is None else str(match.document_id),
            match.chunk_index is None,
            -1 if match.chunk_index is None else int(match.chunk_index),
        ),
    )
    ranked_ids: list[str] = []
    seen: set[str] = set()
    for match in ordered:
        if match.id in seen:
            continue
        seen.add(match.id)
        ranked_ids.append(match.id)
    return ranked_ids


def fuse_request_level_hybrid_rrf(
    vector_matches: list[ChunkMatch],
    keyword_matches: list[ChunkMatch],
    *,
    k: int = RRF_K_DEFAULT,
) -> list[ChunkMatch]:
    """
    Fuse hybrid retrieval across one request's vector and FTS candidate pools.

    ``ChunkMatch.similarity`` is set to request-scoped RRF; global top-k cutting
    happens later in the chat retrieval pipeline.
    """
    matches_by_id: dict[str, ChunkMatch] = {}
    for match in vector_matches:
        matches_by_id[match.id] = match
    for match in keyword_matches:
        matches_by_id[match.id] = _merge_hybrid_chunk_match(
            matches_by_id.get(match.id),
            match,
        )

    vector_ranked = _global_component_rank(vector_matches, "vector_score")
    keyword_ranked = _global_component_rank(keyword_matches, "full_text_score")
    rrf_scores = reciprocal_rank_fusion_scores(
        [vector_ranked, keyword_ranked],
        k=k,
        limit=None,
    )
    fused_ids = list(rrf_scores.keys())
    return merge_chunk_matches_with_scores(
        fused_ids,
        matches_by_id,
        rrf_scores,
        score_type=SCORE_TYPE_HYBRID_RRF,
    )


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
                vector_score=match.vector_score,
                full_text_score=match.full_text_score,
                rrf_score=scores_by_id.get(chunk_id),
                chunk_index=match.chunk_index,
                page_number=match.page_number,
                page_end=match.page_end,
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
    "fuse_request_level_hybrid_rrf",
    "merge_chunk_matches",
    "merge_chunk_matches_with_scores",
    "parse_retrieval_scope",
    "reciprocal_rank_fusion",
    "reciprocal_rank_fusion_scores",
    "rerank_chunks_if_enabled",
    "rerank_chunks_with_debug",
    "resolve_scoped_doc_ids",
]