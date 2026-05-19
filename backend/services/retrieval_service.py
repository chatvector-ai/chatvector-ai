"""
Retrieval orchestration helpers.

Reranking runs after chunk retrieval and before context assembly.
"""

from services.reranker import rerank_chunks_if_enabled

__all__ = ["rerank_chunks_if_enabled"]
