"""Eval orchestration: dataset loading, per-arm retrieval, metrics, compare, export.

The default path never imports or calls answer generation. Retrieval goes
through ``chat_service.retrieve_for_documents`` and stops at assembled
context. ``--answers`` opts a run into calling the injected
``generate_answer`` for rows that carry answer labels, then scores those
labels. ``generate_answer_stream`` is never called.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import config
from db import filter_document_ids_by_metadata
from db.base import ChunkMatch
from services import eval_metrics
from services.chat_service import retrieve_for_documents
from services.eval_config import EffectiveRetrievalConfig, ResolvedEnvironmentSnapshot
from services.history_config import prepare_turn_history
from services.eval_fixtures import (
    EvalDataset,
    EvalQuery,
    ExpectedCitation,
    ExpectedFact,
    ExpectedRefusal,
    dataset_hash,
)
from services.metadata_filter import InvalidMetadataFilterError, validate_metadata_filter

EVAL_TOOL_VERSION = "0.1.0"
DEFAULT_K_VALUES: tuple[int, ...] = (5, 10)


_COMPONENT_SCORE_FIELDS = (
    "vector_score",
    "full_text_score",
    "rrf_score",
    "reranker_score",
    "rerank_order",
)


def _candidate_summary(chunk: ChunkMatch, *, logical_key: str | None = None) -> dict:
    summary = {
        "id": chunk.id,
        "document_id": chunk.document_id,
    }
    if logical_key is not None:
        summary["logical_key"] = logical_key
    summary["chunk_index"] = chunk.chunk_index
    summary["similarity"] = chunk.similarity
    summary["score_type"] = chunk.score_type
    for field_name in _COMPONENT_SCORE_FIELDS:
        value = getattr(chunk, field_name, None)
        if value is not None:
            summary[field_name] = value
    return summary


def _logical_keys_by_document(query: EvalQuery) -> dict[str, str]:
    """Map runtime document ids back to manifest logical keys.

    Empty when the dataset was not resolved through a manifest.
    """
    if not query.logical_doc_ids:
        return {}
    return {
        document_id: logical_key
        for logical_key, document_id in zip(query.logical_doc_ids, query.doc_ids)
        if document_id
    }


def _copied_retrieval_trace(retrieval) -> dict:
    """Copy query text and stage timings already stored on the retrieval result.

    Does not transform the query again or start a new clock.
    """
    transform = retrieval.transform_result
    return {
        "original_query": transform.original_query,
        "transformed_queries": list(transform.queries),
        "effective_retrieval_query": retrieval.primary_query,
        "timing_ms": dict(retrieval.timing_ms),
    }


_NO_RETRIEVAL_TRACE = {
    "original_query": None,
    "transformed_queries": None,
    "effective_retrieval_query": None,
    "timing_ms": None,
}


@dataclass
class QueryResult:
    query: str
    candidates: list[dict]
    metrics: dict[str, float]
    context_preview: str
    # Validated fixture filter that narrowed this query's documents, or None.
    metadata_filter: dict | None = None
    # True when ``metadata_filter`` removed every document: nothing was searched.
    filter_excluded_all_documents: bool = False
    # Copied from RetrievalResult. Null when retrieval did not run.
    original_query: str | None = None
    transformed_queries: list[str] | None = None
    effective_retrieval_query: str | None = None
    timing_ms: dict | None = None
    # Per relevant chunk: retrieved, globally selected, and packed.
    evidence: list[dict] = field(default_factory=list)
    # Set only when the answer arm generated this row.
    answer: str | None = None


@dataclass
class ArmResult:
    config: EffectiveRetrievalConfig
    resolved_env: ResolvedEnvironmentSnapshot
    query_results: list[QueryResult] = field(default_factory=list)
    aggregate_metrics: dict[str, float] = field(default_factory=dict)
    answer_generation: bool = False


@dataclass
class EvalRunResult:
    run_id: str
    timestamp: str
    tool_version: str
    dataset_name: str
    dataset_hash: str
    arms: list[ArmResult]

    def to_export_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "tool_version": self.tool_version,
            "dataset_name": self.dataset_name,
            "dataset_hash": self.dataset_hash,
            "arms": [
                {
                    "config_snapshot": {
                        "effective_config": {
                            **vars(arm.config),
                            "resolved": arm.config.to_request_config().to_debug_dict(),
                        },
                        "resolved_environment": arm.resolved_env.as_dict(),
                    },
                    "aggregate_metrics": arm.aggregate_metrics,
                    "per_query_metrics": [
                        _query_export(qr, include_answer=arm.answer_generation)
                        for qr in arm.query_results
                    ],
                }
                for arm in self.arms
            ],
        }


def _query_export(qr: QueryResult, *, include_answer: bool) -> dict:
    row = {
        "query": qr.query,
        "original_query": qr.original_query,
        "transformed_queries": qr.transformed_queries,
        "effective_retrieval_query": qr.effective_retrieval_query,
        "timing_ms": qr.timing_ms,
        "metrics": qr.metrics,
        "evidence": qr.evidence,
        "candidates": qr.candidates,
        "context_preview": qr.context_preview,
        "metadata_filter": qr.metadata_filter,
        "filter_excluded_all_documents": qr.filter_excluded_all_documents,
    }
    if include_answer:
        row["answer"] = qr.answer
    return row


def _aggregate(query_results: list[QueryResult]) -> dict[str, float]:
    """Mean of each metric over the rows that recorded it."""
    totals: dict[str, list[float]] = {}
    for qr in query_results:
        for key, value in qr.metrics.items():
            totals.setdefault(key, []).append(value)
    return {key: sum(values) / len(values) for key, values in totals.items()}


def _contains_label(text: str, label: str) -> bool:
    return label.casefold() in text.casefold()


def _fact_in_text(fact: ExpectedFact, text: str) -> bool:
    if _contains_label(text, fact.text):
        return True
    return any(_contains_label(text, alternate) for alternate in fact.alternates)


def _completeness(facts: list[ExpectedFact], answer: str) -> float:
    matched = sum(1 for fact in facts if _fact_in_text(fact, answer))
    return matched / len(facts)


def _refusal_correctness(refusal: ExpectedRefusal, answer: str) -> float:
    has_phrase = any(_contains_label(answer, phrase) for phrase in refusal.phrases)
    has_forbidden = any(_contains_label(answer, forbidden) for forbidden in refusal.forbidden)
    if has_phrase and not has_forbidden:
        return 1.0
    return 0.0


def _citation_supported(
    citation: ExpectedCitation,
    packed_chunks: list,
    logical_keys_by_document: dict[str, str],
) -> bool:
    """True when the citation target is on the packer's inclusion list.

    A chunk that was only retrieved or only globally selected does not
    count. The context string is not read.
    """
    targets = {citation.document}
    if citation.resolved_document_id:
        targets.add(citation.resolved_document_id)
    for chunk in packed_chunks:
        document_id = getattr(chunk, "document_id", None)
        identities: set[str] = set()
        if document_id:
            identities.add(document_id)
            logical_key = logical_keys_by_document.get(document_id)
            if logical_key:
                identities.add(logical_key)
        if not (targets & identities):
            continue
        chunk_index = getattr(chunk, "chunk_index", None)
        if citation.chunk_index is not None and chunk_index != citation.chunk_index:
            continue
        page_number = getattr(chunk, "page_number", None)
        if citation.page is not None and page_number != citation.page:
            continue
        return True
    return False


def _groundedness(
    facts: list[ExpectedFact],
    must_not_claim: list[str],
    answer: str,
    context: str,
) -> float:
    for fact in facts:
        if _fact_in_text(fact, answer) and not _fact_in_text(fact, context):
            return 0.0
    if any(_contains_label(answer, claim) for claim in must_not_claim):
        return 0.0
    return 1.0


def _answer_metrics(
    query: EvalQuery,
    answer: str,
    context: str,
    packed_chunks: list,
    logical_keys_by_document: dict[str, str],
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if query.expected_facts:
        metrics["completeness"] = _completeness(query.expected_facts, answer)
    if query.expected_refusal is not None:
        metrics["refusal_correctness"] = _refusal_correctness(query.expected_refusal, answer)
    if query.expected_citation is not None:
        supported = _citation_supported(
            query.expected_citation,
            packed_chunks,
            logical_keys_by_document,
        )
        metrics["citation_support"] = 1.0 if supported else 0.0
    if query.expected_facts or query.must_not_claim:
        metrics["groundedness"] = _groundedness(
            query.expected_facts,
            query.must_not_claim,
            answer,
            context,
        )
    return metrics


def _chunk_key(chunk):
    return eval_metrics.chunk_match_key(
        getattr(chunk, "document_id", None),
        getattr(chunk, "chunk_index", None),
    )


def _membership_keys(chunks: list) -> set:
    return {key for chunk in chunks if (key := _chunk_key(chunk)) is not None}


def _pages_by_key(*chunk_lists: list) -> dict:
    """Page number for a chunk identity. Later lists win, so the packed copy is kept."""
    pages: dict = {}
    for chunks in chunk_lists:
        for chunk in chunks:
            key = _chunk_key(chunk)
            page_number = getattr(chunk, "page_number", None)
            if key is not None and page_number is not None:
                pages[key] = page_number
    return pages


def _relevant_labels(query: EvalQuery) -> list[tuple[str, int | None, str | None]]:
    """Relevant labels in fixture order, with the logical key when a manifest resolved it."""
    mapped = _logical_keys_by_document(query)
    labels: list[tuple[str, int | None, str | None]] = []
    for index, (document_id, chunk_index) in enumerate(query.relevant_chunks):
        logical_key = None
        if index < len(query.logical_relevant_chunks):
            logical_key = query.logical_relevant_chunks[index][0]
        labels.append((document_id, chunk_index, logical_key or mapped.get(document_id)))
    for index, document_id in enumerate(query.relevant_doc_ids):
        logical_key = None
        if index < len(query.logical_relevant_doc_ids):
            logical_key = query.logical_relevant_doc_ids[index]
        labels.append((document_id, None, logical_key or mapped.get(document_id)))
    return labels


def _evidence_for_query(
    query: EvalQuery,
    retrieved_chunks: list,
    selected_chunks: list,
    packed_chunks: list,
) -> list[dict]:
    """Classify each relevant chunk from the three structured lists.

    Does not read the context string, sort the lists, or apply another top-k.
    """
    retrieved_keys = _membership_keys(retrieved_chunks)
    selected_keys = _membership_keys(selected_chunks)
    packed_keys = _membership_keys(packed_chunks)
    pages = _pages_by_key(retrieved_chunks, selected_chunks, packed_chunks)
    rows: list[dict] = []
    for document_id, chunk_index, logical_key in _relevant_labels(query):
        key = eval_metrics.chunk_match_key(document_id, chunk_index)
        row: dict = {"document_id": document_id}
        if chunk_index is not None:
            row["chunk_index"] = chunk_index
        if logical_key:
            row["logical_key"] = logical_key
        page_number = pages.get(key)
        if page_number is not None:
            row["page_number"] = page_number
        present = key is not None
        row["retrieved"] = present and key in retrieved_keys
        row["globally_selected"] = present and key in selected_keys
        row["packed"] = present and key in packed_keys
        rows.append(row)
    return rows


def _validated_filters(dataset: EvalDataset) -> list[dict | None]:
    """Validate every fixture ``metadata_filter`` with the chat validator.

    Runs before any retrieval so a malformed filter fails the run instead of
    being dropped (which would silently search the unfiltered documents).
    """
    filters: list[dict | None] = []
    for index, q in enumerate(dataset.queries):
        if q.metadata_filter is None:
            filters.append(None)
            continue
        try:
            filters.append(validate_metadata_filter(q.metadata_filter))
        except InvalidMetadataFilterError as exc:
            raise InvalidMetadataFilterError(f"Query #{index} ({q.query!r}): {exc}") from exc
    return filters


async def _filtered_doc_ids(
    q: EvalQuery, metadata_filter: dict | None, *, tenant_id: str
) -> list[str]:
    """Narrow the row's document ids with the same helper chat uses.

    The filter only narrows the ids already chosen for the row; it never
    widens them, and a filter that matches nothing returns an empty list.
    """
    if metadata_filter is None or not q.doc_ids:
        return list(q.doc_ids)
    return await filter_document_ids_by_metadata(
        tenant_id=tenant_id,
        doc_ids=list(q.doc_ids),
        metadata_filter=dict(metadata_filter),
    )


async def _run_arm(
    dataset: EvalDataset,
    effective: EffectiveRetrievalConfig,
    *,
    tenant_id: str,
    k_values: tuple[int, ...],
    resolved_env: ResolvedEnvironmentSnapshot,
    answer_generation: bool = False,
    generate_answer=None,
) -> tuple[ArmResult, str | None, bool]:
    query_results: list[QueryResult] = []
    recorded_model: str | None = None
    saw_generation = False

    request_config = effective.to_request_config()
    metadata_filters = _validated_filters(dataset)
    for q, metadata_filter in zip(dataset.queries, metadata_filters):
        doc_ids = await _filtered_doc_ids(q, metadata_filter, tenant_id=tenant_id)
        filter_excluded_all = metadata_filter is not None and bool(q.doc_ids) and not doc_ids
        # Rows opt into session simulation. Otherwise history stays out of
        # transform even when the process default would resolve follow-ups.
        history_kwargs: dict = {"skip_history_transform": effective.skip_history_transform}
        if q.simulate_session:
            plan = prepare_turn_history(
                q.session_history,
                None,
                skip_history_transform=False,
                apply_generation_history=False,
                global_query_transformation_enabled=bool(config.QUERY_TRANSFORMATION_ENABLED),
            )
            history_kwargs = {
                "skip_history_transform": False,
                "history_for_transform": plan.transform_history,
                "resolution_policy": plan.policy,
                "history_observation": plan.observation,
            }
        if filter_excluded_all:
            # Like chat, a filter miss never falls back to the unfiltered
            # documents: nothing is searched and metrics score no candidates.
            candidates: list[ChunkMatch] = []
            context_preview = ""
            trace = dict(_NO_RETRIEVAL_TRACE)
            retrieved_chunks: list = []
            packed_chunks: list = []
        else:
            retrieval = await retrieve_for_documents(
                q.query,
                doc_ids,
                tenant_id,
                request_config,
                use_embedding_cache=effective.allow_embedding_cache,
                max_context_chars=effective.max_context_chars,
                **history_kwargs,
            )
            candidates = retrieval.chunks
            context_preview = retrieval.context
            trace = _copied_retrieval_trace(retrieval)
            retrieved_chunks = retrieval.retrieved_chunks
            packed_chunks = retrieval.packed_chunks

        logical_keys = _logical_keys_by_document(q)
        evidence = _evidence_for_query(q, retrieved_chunks, candidates, packed_chunks)

        metrics: dict[str, float] = {}
        if q.relevant_doc_ids or q.relevant_chunks:
            ranked_keys = [
                eval_metrics.chunk_match_key(c.document_id, c.chunk_index)
                for c in candidates
            ]
            relevant = q.relevant_keys()
            metrics["mrr"] = eval_metrics.mrr(ranked_keys, relevant)
            for k in k_values:
                metrics[f"recall@{k}"] = eval_metrics.recall_at_k(ranked_keys, relevant, k)
                metrics[f"ndcg@{k}"] = eval_metrics.ndcg_at_k(ranked_keys, relevant, k)
            metrics["packed_presence"] = eval_metrics.packed_presence(
                [row["packed"] for row in evidence]
            )

        answer: str | None = None
        if answer_generation and q.has_answer_labels():
            answer, _latency_ms, model_name = await generate_answer(q.query, context_preview)
            if not saw_generation:
                recorded_model = model_name
            saw_generation = True
            metrics.update(
                _answer_metrics(q, answer, context_preview, packed_chunks, logical_keys)
            )

        query_results.append(
            QueryResult(
                query=q.query,
                candidates=[
                    _candidate_summary(
                        c,
                        logical_key=logical_keys.get(c.document_id) if c.document_id else None,
                    )
                    for c in candidates
                ],
                metrics=metrics,
                context_preview=context_preview,
                metadata_filter=metadata_filter,
                filter_excluded_all_documents=filter_excluded_all,
                original_query=trace["original_query"],
                transformed_queries=trace["transformed_queries"],
                effective_retrieval_query=trace["effective_retrieval_query"],
                timing_ms=trace["timing_ms"],
                evidence=evidence,
                answer=answer,
            )
        )

    return (
        ArmResult(
            config=effective,
            resolved_env=resolved_env,
            query_results=query_results,
            aggregate_metrics=_aggregate(query_results),
            answer_generation=answer_generation,
        ),
        recorded_model,
        saw_generation,
    )


async def run_eval(
    dataset: EvalDataset,
    arms: list[EffectiveRetrievalConfig],
    *,
    tenant_id: str,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
    export_path: str | Path | None = None,
    answer_generation: bool = False,
    generate_answer=None,
) -> EvalRunResult:
    """Run one or more config arms against ``dataset``.

    Arms run sequentially so a comparison does not stampede the database.
    Each arm carries its own request-scoped config and does not mutate
    process globals. Answer generation stays off unless
    ``answer_generation`` is set, and then only rows with answer labels
    are sent to ``generate_answer``.
    """
    if answer_generation and generate_answer is None:
        raise ValueError("answer generation requires generate_answer")

    resolved_env = ResolvedEnvironmentSnapshot.capture()
    arm_results: list[ArmResult] = []
    recorded_model: str | None = None
    saw_generation = False
    for effective in arms:
        arm_result, model_name, generated = await _run_arm(
            dataset,
            effective,
            tenant_id=tenant_id,
            k_values=k_values,
            resolved_env=resolved_env,
            answer_generation=answer_generation,
            generate_answer=generate_answer,
        )
        arm_results.append(arm_result)
        if generated and not saw_generation:
            saw_generation = True
            recorded_model = model_name
    if saw_generation:
        resolved_env.llm_provider = config.LLM_PROVIDER
        resolved_env.llm_model = recorded_model

    result = EvalRunResult(
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool_version=EVAL_TOOL_VERSION,
        dataset_name=dataset.name,
        dataset_hash=dataset_hash(dataset.source_path) if dataset.source_path else "",
        arms=arm_results,
    )

    if export_path is not None:
        export_run(result, export_path)

    return result


def export_run(result: EvalRunResult, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result.to_export_dict(), indent=2), encoding="utf-8")


def diff_arms(arm_results: list[ArmResult]) -> list[dict]:
    """Per-query candidate-set diff across 2+ arms (compare mode)."""
    if len(arm_results) < 2:
        return []

    diffs = []
    for i, first_qr in enumerate(arm_results[0].query_results):
        per_arm = []
        for arm in arm_results:
            qr = arm.query_results[i]
            per_arm.append(
                {
                    "label": arm.config.label,
                    "candidate_ids": [c["id"] for c in qr.candidates],
                    "context_preview": qr.context_preview,
                }
            )
        candidate_sets = [set(pa["candidate_ids"]) for pa in per_arm]
        differs = any(cs != candidate_sets[0] for cs in candidate_sets[1:])
        diffs.append({"query": first_qr.query, "arms": per_arm, "differs": differs})

    return diffs
