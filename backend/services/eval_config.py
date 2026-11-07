"""Eval-arm records mapped onto request-scoped retrieval config.

Retrieval itself runs through ``chat_service.retrieve_for_documents``. This
module does not mutate process config or the reranker cache.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from core.config import config
from services import context_service
from services.retrieval_config import (
    EffectiveRetrievalConfig as RequestRetrievalConfig,
    RetrievalProcessDefaults,
    resolve_retrieval_config,
)


@dataclass
class EffectiveRetrievalConfig:
    """One eval arm: retrieval knobs under comparison.

    Execution uses :func:`to_request_config`, which is the immutable
    request-scoped config. ``max_context_chars`` is an eval context-assembly
    override, not a chat request field. The process value is still recorded
    on ``ResolvedEnvironmentSnapshot``.
    """

    label: str
    hybrid_retrieval_enabled: bool
    enable_reranking: bool
    reranker_provider: str = "similarity"
    match_count: int = 10
    max_context_chars: int = 32000
    allow_embedding_cache: bool = False
    query_transformation_enabled: bool | None = False
    query_transformation_strategy: str | None = "none"
    skip_history_transform: bool = True

    def to_request_config(self) -> RequestRetrievalConfig:
        """Map this arm onto the request-scoped retrieval config.

        Query transformation defaults off so an eval run stays deterministic
        unless the arm sets it. ``None`` omits the field and inherits process env.
        """
        fields: dict = {
            "match_count": self.match_count,
            "hybrid_enabled": self.hybrid_retrieval_enabled,
            "reranking_enabled": self.enable_reranking,
            "reranker_provider": self.reranker_provider,
            "skip_history_transform": self.skip_history_transform,
        }
        if self.query_transformation_enabled is not None:
            fields["query_transformation_enabled"] = self.query_transformation_enabled
        if self.query_transformation_strategy is not None:
            fields["query_transformation_strategy"] = self.query_transformation_strategy
        return resolve_retrieval_config(fields, RetrievalProcessDefaults.from_process())


@dataclass
class ResolvedEnvironmentSnapshot:
    """Ambient env-derived retrieval/context config, captured for export reproducibility."""

    hybrid_retrieval_enabled: bool
    enable_reranking: bool
    reranker_provider: str
    enable_embedding_cache: bool
    max_context_chars: int
    embedding_provider: str
    embedding_model: str | None
    query_transformation_enabled: bool
    query_transformation_strategy: str
    chunk_size: int
    chunk_overlap: int
    chunking_strategy: str
    prompt_persona: str
    # Answer-generation identity. Left null unless generation is enabled, and
    # never filled from LLM_PROVIDER / LLM_MODEL on a retrieval-only capture.
    llm_provider: str | None = None
    llm_model: str | None = None

    @classmethod
    def capture(
        cls,
        *,
        answer_generation_enabled: bool = False,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> "ResolvedEnvironmentSnapshot":
        if answer_generation_enabled:
            generation_provider = llm_provider
            generation_model = llm_model
        else:
            generation_provider = None
            generation_model = None
        return cls(
            hybrid_retrieval_enabled=config.HYBRID_RETRIEVAL_ENABLED,
            enable_reranking=config.ENABLE_RERANKING,
            reranker_provider=config.RERANKER_PROVIDER,
            enable_embedding_cache=config.ENABLE_EMBEDDING_CACHE,
            max_context_chars=context_service.MAX_CONTEXT_CHARS,
            embedding_provider=config.EMBEDDING_PROVIDER,
            embedding_model=config.EMBEDDING_MODEL,
            query_transformation_enabled=config.QUERY_TRANSFORMATION_ENABLED,
            query_transformation_strategy=config.QUERY_TRANSFORMATION_STRATEGY,
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            chunking_strategy=config.CHUNKING_STRATEGY,
            prompt_persona=config.PROMPT_PERSONA,
            llm_provider=generation_provider,
            llm_model=generation_model,
        )

    def as_dict(self) -> dict:
        return asdict(self)
