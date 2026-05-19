"""Reranking provider abstraction and shared input/output types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from db.base import ChunkMatch


@dataclass(frozen=True)
class RerankRequest:
    """Standard reranking input."""

    query: str
    candidates: list[ChunkMatch]
    top_k: int | None = None


@dataclass(frozen=True)
class RerankResult:
    """Standard reranking output with stable ordering metadata."""

    candidates: list[ChunkMatch]
    original_order: list[str]
    reranked_order: list[str]


class RerankerProvider(ABC):
    """Reorders retrieved chunks after initial retrieval, before context assembly."""

    @abstractmethod
    async def rerank(self, request: RerankRequest) -> RerankResult:
        """Return candidates reordered by relevance to the query."""
