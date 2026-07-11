"""Deterministic baseline reranker using retrieval score and lexical overlap."""

from __future__ import annotations

import re

from db.base import SCORE_TYPE_RERANKED, ChunkMatch

from services.reranker.base import RerankRequest, RerankResult, RerankerProvider

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _chunk_key(chunk: ChunkMatch) -> str:
    return chunk.id or f"{chunk.document_id}:{chunk.chunk_index}"


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}


def _lexical_overlap_score(query: str, chunk_text: str) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    chunk_tokens = _tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def _retrieval_score(chunk: ChunkMatch) -> float:
    if chunk.similarity is not None:
        return float(chunk.similarity)
    return 0.0


class SimilarityRerankerProvider(RerankerProvider):
    """
    Baseline reranker: combine vector similarity with query/chunk token overlap.

    No external models or GPU dependencies.
    """

    def __init__(self, *, retrieval_weight: float = 0.7, lexical_weight: float = 0.3):
        total = retrieval_weight + lexical_weight
        if total <= 0:
            raise ValueError("retrieval_weight and lexical_weight must sum to a positive value")
        self._retrieval_weight = retrieval_weight / total
        self._lexical_weight = lexical_weight / total

    async def rerank(self, request: RerankRequest) -> RerankResult:
        original_order = [_chunk_key(chunk) for chunk in request.candidates]
        if not request.candidates:
            return RerankResult(
                candidates=[],
                original_order=original_order,
                reranked_order=[],
            )

        scored: list[tuple[float, ChunkMatch]] = []
        for chunk in request.candidates:
            lexical = _lexical_overlap_score(request.query, chunk.chunk_text)
            combined = (
                self._retrieval_weight * _retrieval_score(chunk)
                + self._lexical_weight * lexical
            )
            scored.append((combined, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        limit = request.top_k if request.top_k is not None else len(scored)
        reranked: list[ChunkMatch] = []
        for combined_score, chunk in scored[:limit]:
            reranked.append(
                ChunkMatch(
                    id=chunk.id,
                    chunk_text=chunk.chunk_text,
                    document_id=chunk.document_id,
                    embedding=chunk.embedding,
                    created_at=chunk.created_at,
                    similarity=combined_score,
                    score_type=SCORE_TYPE_RERANKED,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    character_offset_start=chunk.character_offset_start,
                    character_offset_end=chunk.character_offset_end,
                    file_name=chunk.file_name,
                )
            )

        return RerankResult(
            candidates=reranked,
            original_order=original_order,
            reranked_order=[_chunk_key(chunk) for chunk in reranked],
        )
