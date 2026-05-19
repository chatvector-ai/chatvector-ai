"""Passthrough reranker used when reranking is disabled."""

from __future__ import annotations

from services.reranker.base import RerankRequest, RerankResult, RerankerProvider
from services.reranker.similarity import _chunk_key


class NoopRerankerProvider(RerankerProvider):
    """Returns candidates unchanged."""

    async def rerank(self, request: RerankRequest) -> RerankResult:
        order = [_chunk_key(chunk) for chunk in request.candidates]
        limit = request.top_k if request.top_k is not None else len(request.candidates)
        candidates = request.candidates[:limit]
        return RerankResult(
            candidates=candidates,
            original_order=order,
            reranked_order=[_chunk_key(chunk) for chunk in candidates],
        )
