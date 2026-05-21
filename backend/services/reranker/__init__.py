"""Reranker provider factory."""

from __future__ import annotations

import logging

from core.config import config
from db.base import ChunkMatch
from services.reranker.base import RerankRequest, RerankResult, RerankerProvider
from services.reranker.noop import NoopRerankerProvider
from services.reranker.similarity import SimilarityRerankerProvider

logger = logging.getLogger(__name__)

_reranker_provider: RerankerProvider | None = None

VALID_RERANKER_PROVIDERS = {"similarity"}


def _reset_reranker_provider() -> None:
    """Clear cached provider (for tests)."""
    global _reranker_provider
    _reranker_provider = None


def get_reranker_provider() -> RerankerProvider:
    """Return singleton reranker based on configuration."""
    global _reranker_provider

    if _reranker_provider is not None:
        return _reranker_provider

    if not config.ENABLE_RERANKING:
        _reranker_provider = NoopRerankerProvider()
        return _reranker_provider

    name = config.RERANKER_PROVIDER
    if name == "similarity":
        _reranker_provider = SimilarityRerankerProvider()
        logger.info("Using similarity reranker provider")
    else:
        raise ValueError(
            f"Unknown RERANKER_PROVIDER={name!r}. "
            f"Expected one of: {', '.join(sorted(VALID_RERANKER_PROVIDERS))}."
        )

    return _reranker_provider


async def rerank_chunks_if_enabled(
    query: str,
    chunks: list[ChunkMatch],
    *,
    top_k: int | None = None,
) -> list[ChunkMatch]:
    """
    Apply configured reranking after retrieval and before context construction.

    When ENABLE_RERANKING is false, returns chunks unchanged (no top_k truncation).
    """
    if not chunks:
        return []

    if not config.ENABLE_RERANKING:
        return chunks

    provider = get_reranker_provider()
    request = RerankRequest(query=query, candidates=chunks, top_k=top_k)
    result = await provider.rerank(request)

    if config.ENABLE_RERANKING and result.original_order != result.reranked_order:
        logger.debug(
            "Reranked %d chunk(s): original=%s -> reranked=%s",
            len(result.candidates),
            result.original_order,
            result.reranked_order,
        )
    elif config.ENABLE_RERANKING:
        logger.debug(
            "Reranking enabled; order unchanged for %d chunk(s): %s",
            len(result.candidates),
            result.reranked_order,
        )

    return result.candidates
