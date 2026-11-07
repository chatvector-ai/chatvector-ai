"""Tests for the retrieval eval tool: metrics, compare mode, export, no-LLM guard."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.config import config
from db.base import ChunkMatch
from services import eval_metrics
from cli import cmd_eval
from services.chat_service import RetrievalResult
from services.eval_config import EffectiveRetrievalConfig, ResolvedEnvironmentSnapshot
from services.eval_fixtures import EvalDataset, load_dataset
from services.eval_service import ArmResult, EvalRunResult, diff_arms, run_eval
from services.query_service import QueryTransformResult
from services.retrieval_config import RetrievalProcessDefaults, resolve_retrieval_config
from services.metadata_filter import InvalidMetadataFilterError

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eval"


def _chunk(doc_id: str, chunk_index: int, *, score: float = 0.5) -> ChunkMatch:
    return ChunkMatch(
        id=f"{doc_id}:{chunk_index}",
        chunk_text=f"content for {doc_id} chunk {chunk_index}",
        document_id=doc_id,
        chunk_index=chunk_index,
        similarity=score,
        file_name=f"{doc_id}.txt",
    )


# ---------------------------------------------------------------------------
# eval_metrics — pure unit tests against hand-computed values
# ---------------------------------------------------------------------------


def test_recall_at_k():
    ranked = ["a", "b", "c", "d"]
    relevant = {"b", "d", "z"}
    assert eval_metrics.recall_at_k(ranked, relevant, k=2) == pytest.approx(1 / 3)
    assert eval_metrics.recall_at_k(ranked, relevant, k=4) == pytest.approx(2 / 3)


def test_recall_at_k_no_relevant_returns_zero():
    assert eval_metrics.recall_at_k(["a"], set(), k=5) == 0.0


def test_mrr_first_hit_rank():
    assert eval_metrics.mrr(["a", "b", "c"], {"b"}) == pytest.approx(0.5)
    assert eval_metrics.mrr(["a", "b", "c"], {"z"}) == 0.0


def test_ndcg_at_k_perfect_order_is_one():
    ranked = ["a", "b", "c"]
    relevant = {"a", "b"}
    assert eval_metrics.ndcg_at_k(ranked, relevant, k=2) == pytest.approx(1.0)


def test_ndcg_at_k_worse_order_is_less_than_one():
    ranked = ["c", "a", "b"]
    relevant = {"a", "b"}
    score = eval_metrics.ndcg_at_k(ranked, relevant, k=2)
    assert 0.0 < score < 1.0


def test_chunk_match_key_falls_back_to_document_id():
    assert eval_metrics.chunk_match_key("doc-1", 3) == ("doc-1", 3)
    assert eval_metrics.chunk_match_key("doc-1", None) == "doc-1"
    assert eval_metrics.chunk_match_key(None, 3) is None


# ---------------------------------------------------------------------------
# run_eval — single arm against the checked-in basic fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_eval_single_arm_reports_sane_metrics():
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")

    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        # One correct hit plus filler, regardless of arm config.
        return [_chunk(doc_id, 0), _chunk(doc_id, 1), _chunk(doc_id, 2)]

    arm = EffectiveRetrievalConfig(
        label="current-config",
        hybrid_retrieval_enabled=False,
        enable_reranking=False,
    )

    with patch("services.chat_service.find_similar_chunks", AsyncMock(side_effect=fake_find_similar_chunks)), \
         patch("services.chat_service.get_embeddings", AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts])):
        result = await run_eval(dataset, [arm], tenant_id="tenant-eval-test")

    assert len(result.arms) == 1
    arm_result = result.arms[0]
    assert len(arm_result.query_results) == len(dataset.queries)
    for metric_name in ("mrr", "recall@5", "recall@10", "ndcg@5", "ndcg@10"):
        value = arm_result.aggregate_metrics[metric_name]
        assert 0.0 <= value <= 1.0

    for qr in arm_result.query_results:
        assert qr.context_preview  # context assembled per query


# ---------------------------------------------------------------------------
# Compare mode — 2 arms against the diverging fixture must show real diffs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_mode_arms_produce_different_candidates():
    dataset = load_dataset(FIXTURES_DIR / "diverging_queries.json")

    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        # Branch on the request-scoped flag, not the process global.
        if hybrid_enabled:
            return [_chunk(doc_id, 9, score=0.9), _chunk(doc_id, 1, score=0.7)]
        return [_chunk(doc_id, 2, score=0.8), _chunk(doc_id, 3, score=0.6)]

    vector_only = EffectiveRetrievalConfig(
        label="vector-only", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    hybrid = EffectiveRetrievalConfig(
        label="hybrid", hybrid_retrieval_enabled=True, enable_reranking=False
    )

    with patch("services.chat_service.find_similar_chunks", AsyncMock(side_effect=fake_find_similar_chunks)), \
         patch("services.chat_service.get_embeddings", AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts])):
        result = await run_eval(dataset, [vector_only, hybrid], tenant_id="tenant-eval-test")

    diffs = diff_arms(result.arms)
    assert len(diffs) == len(dataset.queries)
    assert all(d["differs"] for d in diffs), "arms must diverge, not just match_count"
    for d in diffs:
        for arm_entry in d["arms"]:
            assert arm_entry["context_preview"]


# ---------------------------------------------------------------------------
# Export schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_writes_expected_schema(tmp_path):
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")

    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        return [_chunk(doc_id, 0)]

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    export_path = tmp_path / "run.json"

    with patch("services.chat_service.find_similar_chunks", AsyncMock(side_effect=fake_find_similar_chunks)), \
         patch("services.chat_service.get_embeddings", AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts])):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    for key in ("run_id", "timestamp", "tool_version", "dataset_name", "dataset_hash", "arms"):
        assert key in payload

    arm_payload = payload["arms"][0]
    assert "config_snapshot" in arm_payload
    assert "effective_config" in arm_payload["config_snapshot"]
    assert "resolved_environment" in arm_payload["config_snapshot"]
    assert "aggregate_metrics" in arm_payload
    assert "per_query_metrics" in arm_payload
    assert len(arm_payload["per_query_metrics"]) == len(dataset.queries)


def _retrieval_result(
    chunks: list[ChunkMatch],
    *,
    original_query: str,
    transformed_queries: list[str],
    primary_query: str,
    timing_ms: dict,
    context: str = "packed context",
) -> RetrievalResult:
    return RetrievalResult(
        chunks=list(chunks),
        queries=list(transformed_queries),
        primary_query=primary_query,
        context=context,
        timing_ms=dict(timing_ms),
        transform_result=QueryTransformResult(
            queries=list(transformed_queries),
            original_query=original_query,
        ),
        effective_config=resolve_retrieval_config({}, RetrievalProcessDefaults.from_process()),
    )


@pytest.mark.asyncio
async def test_export_copies_transformed_queries_and_timings_from_retrieval(tmp_path):
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    timing_ms = {
        "transform": 11,
        "embed": 22,
        "search": 33,
        "rerank": 44,
        "context": 55,
        "total": 66,
    }
    retrieval = _retrieval_result(
        [_chunk("fixture-doc-01", 2, score=0.4)],
        original_query="asked before transform",
        transformed_queries=["embedded query", "expanded query"],
        primary_query="embedded query",
        timing_ms=timing_ms,
        context="assembled context",
    )

    async def fake_retrieve(*args, **kwargs):
        del args, kwargs
        return retrieval

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    export_path = tmp_path / "run.json"

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        result = await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    row = result.arms[0].query_results[0]
    assert row.original_query == retrieval.transform_result.original_query
    assert row.transformed_queries == retrieval.transform_result.queries
    assert row.effective_retrieval_query == retrieval.primary_query
    assert row.timing_ms == retrieval.timing_ms
    assert list(row.timing_ms) == list(retrieval.timing_ms)

    exported = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["per_query_metrics"][0]
    assert exported["original_query"] == retrieval.transform_result.original_query
    assert exported["transformed_queries"] == list(retrieval.transform_result.queries)
    assert exported["effective_retrieval_query"] == retrieval.primary_query
    assert exported["timing_ms"] == retrieval.timing_ms
    assert list(exported["timing_ms"]) == ["transform", "embed", "search", "rerank", "context", "total"]


@pytest.mark.asyncio
async def test_export_keeps_chunk_order_and_present_component_scores(tmp_path):
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    low_then_high = [
        ChunkMatch(
            id="later-doc:0",
            chunk_text="low",
            document_id="later-doc",
            chunk_index=0,
            similarity=0.1,
            score_type="vector",
            vector_score=0.1,
        ),
        ChunkMatch(
            id="earlier-doc:3",
            chunk_text="high",
            document_id="earlier-doc",
            chunk_index=3,
            similarity=0.9,
            score_type="reranked",
            vector_score=0.4,
            full_text_score=0.2,
            rrf_score=0.03,
            reranker_score=0.9,
            rerank_order=1,
        ),
        ChunkMatch(
            id="plain-doc:1",
            chunk_text="plain",
            document_id="plain-doc",
            chunk_index=1,
            similarity=0.5,
            score_type="vector",
        ),
    ]
    retrieval = _retrieval_result(
        low_then_high,
        original_query="order query",
        transformed_queries=["order query"],
        primary_query="order query",
        timing_ms={"transform": 1, "embed": 1, "search": 1, "rerank": 1, "context": 1, "total": 5},
    )

    async def fake_retrieve(*args, **kwargs):
        del args, kwargs
        return retrieval

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    export_path = tmp_path / "order.json"

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    candidates = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["per_query_metrics"][0]["candidates"]
    assert [row["id"] for row in candidates] == [chunk.id for chunk in retrieval.chunks]
    assert [row["similarity"] for row in candidates] == [0.1, 0.9, 0.5]

    sparse, scored, plain = candidates
    assert sparse["score_type"] == "vector"
    assert sparse["vector_score"] == 0.1
    for absent in ("full_text_score", "rrf_score", "reranker_score", "rerank_order"):
        assert absent not in sparse
    assert scored["vector_score"] == 0.4
    assert scored["full_text_score"] == 0.2
    assert scored["rrf_score"] == 0.03
    assert scored["reranker_score"] == 0.9
    assert scored["rerank_order"] == 1
    assert scored["document_id"] == "earlier-doc"
    assert scored["chunk_index"] == 3
    assert scored["similarity"] == 0.9
    for absent in ("vector_score", "full_text_score", "rrf_score", "reranker_score", "rerank_order"):
        assert absent not in plain
    assert plain["score_type"] == "vector"
    assert plain["similarity"] == 0.5


def _manifest_dataset(tmp_path: Path) -> EvalDataset:
    questions = {
        "name": "resolved",
        "chunk_settings": {
            "chunking_strategy": "fixed",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        },
        "queries": [
            {
                "query": "How long is the retention period?",
                "doc_ids": ["retention-policy", "handbook"],
                "relevant_chunks": [["retention-policy", 0]],
            }
        ],
    }
    manifest = {
        "tenant_id": "eval-tenant",
        "chunk_settings": {
            "CHUNK_SIZE": 1000,
            "CHUNK_OVERLAP": 200,
            "CHUNKING_STRATEGY": "fixed",
        },
        "documents": [
            {
                "logical_key": "retention-policy",
                "file_name": "retention.txt",
                "document_id": "run-doc-retention",
                "status": "completed",
            },
            {
                "logical_key": "handbook",
                "file_name": "handbook.txt",
                "document_id": "run-doc-handbook",
                "status": "completed",
            },
        ],
    }
    question_path = tmp_path / "queries.json"
    manifest_path = tmp_path / "manifest.json"
    question_path.write_text(json.dumps(questions), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_dataset(question_path, manifest_path)


@pytest.mark.asyncio
async def test_export_keeps_logical_key_and_runtime_document_id(tmp_path):
    dataset = _manifest_dataset(tmp_path)
    resolved = dataset.queries[0]
    assert resolved.doc_ids == ["run-doc-retention", "run-doc-handbook"]
    assert resolved.logical_doc_ids == ["retention-policy", "handbook"]

    retrieval = _retrieval_result(
        [
            _chunk("run-doc-handbook", 1, score=0.2),
            _chunk("run-doc-retention", 0, score=0.8),
            _chunk("not-in-manifest", 4, score=0.3),
        ],
        original_query="How long is the retention period?",
        transformed_queries=["How long is the retention period?"],
        primary_query="How long is the retention period?",
        timing_ms={"transform": 1, "embed": 1, "search": 1, "rerank": 0, "context": 1, "total": 4},
    )

    async def fake_retrieve(*args, **kwargs):
        del args, kwargs
        return retrieval

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    export_path = tmp_path / "resolved.json"

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    candidates = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["per_query_metrics"][0]["candidates"]
    assert [(row["document_id"], row.get("logical_key")) for row in candidates] == [
        ("run-doc-handbook", "handbook"),
        ("run-doc-retention", "retention-policy"),
        ("not-in-manifest", None),
    ]
    assert "logical_key" not in candidates[2]

    plain = load_dataset(FIXTURES_DIR / "basic_queries.json")
    plain_retrieval = _retrieval_result(
        [_chunk("fixture-doc-01", 0)],
        original_query="plain",
        transformed_queries=["plain"],
        primary_query="plain",
        timing_ms={"total": 1},
    )

    async def fake_plain(*args, **kwargs):
        del args, kwargs
        return plain_retrieval

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_plain)):
        plain_result = await run_eval(plain, [arm], tenant_id="tenant-eval-test")

    assert "logical_key" not in plain_result.arms[0].query_results[0].candidates[0]


@pytest.mark.asyncio
async def test_export_snapshot_records_config_persona_chunks_and_transform(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE", 777)
    monkeypatch.setattr(config, "CHUNK_OVERLAP", 42)
    monkeypatch.setattr(config, "CHUNKING_STRATEGY", "semantic")
    monkeypatch.setattr(config, "PROMPT_PERSONA", "concise")
    monkeypatch.setattr(config, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "text-embedding-test")
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "stepback")

    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    retrieval = _retrieval_result(
        [_chunk("fixture-doc-01", 0)],
        original_query="plain",
        transformed_queries=["plain"],
        primary_query="plain",
        timing_ms={"total": 1},
    )

    async def fake_retrieve(*args, **kwargs):
        del args, kwargs
        return retrieval

    arm = EffectiveRetrievalConfig(
        label="rewrite-arm",
        hybrid_retrieval_enabled=True,
        enable_reranking=False,
        match_count=4,
        query_transformation_enabled=True,
        query_transformation_strategy="rewrite",
    )
    export_path = tmp_path / "snapshot.json"

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    snapshot = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["config_snapshot"]
    effective = snapshot["effective_config"]
    environment = snapshot["resolved_environment"]

    assert effective["label"] == "rewrite-arm"
    assert effective["hybrid_retrieval_enabled"] is True
    assert effective["match_count"] == 4
    assert effective["query_transformation_enabled"] is True
    assert effective["query_transformation_strategy"] == "rewrite"
    assert effective["resolved"]["query_transformation_enabled"] == {
        "value": True,
        "source": "request",
    }
    assert effective["resolved"]["query_transformation_strategy"] == {
        "value": "rewrite",
        "source": "request",
    }

    assert environment["chunk_size"] == 777
    assert environment["chunk_overlap"] == 42
    assert environment["chunking_strategy"] == "semantic"
    assert environment["prompt_persona"] == "concise"
    assert environment["embedding_provider"] == "openai"
    assert environment["embedding_model"] == "text-embedding-test"
    assert environment["query_transformation_enabled"] is False
    assert environment["query_transformation_strategy"] == "stepback"


@pytest.mark.asyncio
async def test_retrieval_only_export_does_not_invent_an_llm_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "guessed-provider")
    monkeypatch.setattr(config, "LLM_MODEL", "guessed-model")
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    retrieval = _retrieval_result(
        [_chunk("fixture-doc-01", 0)],
        original_query="plain",
        transformed_queries=["plain"],
        primary_query="plain",
        timing_ms={"total": 1},
    )

    async def fake_retrieve(*args, **kwargs):
        del args, kwargs
        return retrieval

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )
    export_path = tmp_path / "retrieval-only.json"

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test", export_path=export_path)

    environment = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["config_snapshot"][
        "resolved_environment"
    ]
    assert environment["llm_provider"] is None
    assert environment["llm_model"] is None
    assert environment["embedding_model"] != "guessed-model"


def test_export_includes_llm_identity_only_when_answer_generation_is_enabled(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "guessed-provider")
    monkeypatch.setattr(config, "LLM_MODEL", "guessed-model")

    ignored = ResolvedEnvironmentSnapshot.capture(
        answer_generation_enabled=False,
        llm_provider="anthropic",
        llm_model="claude-from-generate-answer",
    )
    assert ignored.llm_provider is None
    assert ignored.llm_model is None

    supplied = ResolvedEnvironmentSnapshot.capture(
        answer_generation_enabled=True,
        llm_provider="anthropic",
        llm_model="claude-from-generate-answer",
    )
    omitted = ResolvedEnvironmentSnapshot.capture(answer_generation_enabled=True)
    assert omitted.llm_provider is None
    assert omitted.llm_model is None

    result = EvalRunResult(
        run_id="run",
        timestamp="t",
        tool_version="v",
        dataset_name="d",
        dataset_hash="h",
        arms=[
            ArmResult(
                config=EffectiveRetrievalConfig(
                    label="generated",
                    hybrid_retrieval_enabled=False,
                    enable_reranking=False,
                ),
                resolved_env=supplied,
            )
        ],
    )
    environment = result.to_export_dict()["arms"][0]["config_snapshot"]["resolved_environment"]
    assert environment["llm_provider"] == "anthropic"
    assert environment["llm_model"] == "claude-from-generate-answer"
    assert environment["llm_model"] != config.LLM_MODEL


# ---------------------------------------------------------------------------
# No answer-generation call anywhere in the eval path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eval_never_calls_answer_generation():
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")

    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        return [_chunk(doc_id, 0)]

    arm = EffectiveRetrievalConfig(
        label="current-config", hybrid_retrieval_enabled=False, enable_reranking=False
    )

    with patch("services.chat_service.find_similar_chunks", AsyncMock(side_effect=fake_find_similar_chunks)), \
         patch("services.chat_service.get_embeddings", AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts])), \
         patch("services.answer_service.generate_answer", AsyncMock(side_effect=AssertionError("must not be called"))) as gen, \
         patch("services.answer_service.generate_answer_stream", AsyncMock(side_effect=AssertionError("must not be called"))) as gen_stream:
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test")

    gen.assert_not_called()
    gen_stream.assert_not_called()


# ---------------------------------------------------------------------------
# Config override restore-on-finally (no leaked global state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_overrides_restored_after_run():
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")

    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        return [_chunk(doc_id, 0)]

    original_hybrid = config.HYBRID_RETRIEVAL_ENABLED
    original_rerank = config.ENABLE_RERANKING

    arm = EffectiveRetrievalConfig(
        label="flipped",
        hybrid_retrieval_enabled=not original_hybrid,
        enable_reranking=not original_rerank,
    )

    with patch("services.chat_service.find_similar_chunks", AsyncMock(side_effect=fake_find_similar_chunks)), \
         patch("services.chat_service.get_embeddings", AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts])):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test")

    assert config.HYBRID_RETRIEVAL_ENABLED == original_hybrid
    assert config.ENABLE_RERANKING == original_rerank


def _empty_eval_result() -> EvalRunResult:
    return EvalRunResult(
        run_id="run",
        timestamp="t",
        tool_version="v",
        dataset_name="d",
        dataset_hash="h",
        arms=[],
    )


async def _load_eval_arm(tmp_path, raw: dict):
    arm_file = tmp_path / "arm.json"
    arm_file.write_text(json.dumps(raw))
    captured: dict = {}

    async def fake_run(dataset, arms, **kwargs):
        del dataset, kwargs
        captured["arms"] = arms
        return _empty_eval_result()

    with (
        patch("services.eval_fixtures.load_dataset", return_value=EvalDataset(name="d", queries=[])),
        patch("services.eval_service.run_eval", new=fake_run),
    ):
        await cmd_eval(str(tmp_path / "dataset.json"), "dev", [5], [str(arm_file)], 5, None, False)
    return captured["arms"][0]


@pytest.mark.asyncio
async def test_eval_arm_new_keys_do_not_require_legacy_names(tmp_path):
    arm = await _load_eval_arm(
        tmp_path,
        {"label": "new-keys", "hybrid_enabled": True, "reranking_enabled": False},
    )
    assert arm.label == "new-keys"
    assert arm.hybrid_retrieval_enabled is True
    assert arm.enable_reranking is False


@pytest.mark.asyncio
async def test_eval_arm_legacy_keys_still_load(tmp_path):
    arm = await _load_eval_arm(
        tmp_path,
        {"hybrid_retrieval_enabled": False, "enable_reranking": True},
    )
    assert arm.hybrid_retrieval_enabled is False
    assert arm.enable_reranking is True


@pytest.mark.asyncio
async def test_eval_arm_new_keys_win_when_both_names_are_present(tmp_path):
    arm = await _load_eval_arm(
        tmp_path,
        {
            "hybrid_enabled": True,
            "hybrid_retrieval_enabled": False,
            "reranking_enabled": False,
            "enable_reranking": True,
        },
    )
    assert arm.hybrid_retrieval_enabled is True
    assert arm.enable_reranking is False


@pytest.mark.asyncio
async def test_retrieve_for_documents_forwards_use_embedding_cache_to_embedding_layer():
    """Eval cache bypass must reach embedding_service through the chat wrapper.

    Patching ``chat_service.get_embeddings`` would hide a wrapper TypeError.
    """
    from services.chat_service import retrieve_for_documents
    from services.query_service import QueryTransformResult
    from services.retrieval_config import RetrievalProcessDefaults, resolve_retrieval_config

    captured: dict = {}

    async def fake_embed(texts, *, tenant_id=None, use_cache=None):
        captured["use_cache"] = use_cache
        captured["tenant_id"] = tenant_id
        captured["texts"] = list(texts)
        return [[0.1, 0.2] for _ in texts]

    effective = resolve_retrieval_config({}, RetrievalProcessDefaults.from_process())
    transform = QueryTransformResult(queries=["cache bypass query"], original_query="cache bypass query")

    with (
        patch("services.embedding_service.get_embeddings", new=fake_embed),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
    ):
        await retrieve_for_documents(
            "cache bypass query",
            ["doc-1"],
            "tenant-eval-test",
            effective,
            use_embedding_cache=False,
            transform_result=transform,
        )

    assert captured["use_cache"] is False
    assert captured["tenant_id"] == "tenant-eval-test"
    assert captured["texts"] == ["cache bypass query"]


@pytest.mark.asyncio
async def test_eval_bypasses_embedding_cache_by_default():
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    captured: list[bool | None] = []

    async def fake_embed(texts, *, tenant_id=None, use_cache=None):
        captured.append(use_cache)
        return [[0.1, 0.2] for _ in texts]

    arm = EffectiveRetrievalConfig(
        label="current-config",
        hybrid_retrieval_enabled=False,
        enable_reranking=False,
    )
    assert arm.allow_embedding_cache is False

    with (
        patch("services.embedding_service.get_embeddings", new=fake_embed),
        patch(
            "services.chat_service.find_similar_chunks",
            new=AsyncMock(return_value=[_chunk("doc-1", 0)]),
        ),
    ):
        await run_eval(dataset, [arm], tenant_id="tenant-eval-test")

    assert captured
    assert all(flag is False for flag in captured)


# ---------------------------------------------------------------------------
# Fixture metadata_filter — narrowed with chat's validator + document filter
# ---------------------------------------------------------------------------


def _filter_dataset(tmp_path, rows: list[dict]) -> EvalDataset:
    path = tmp_path / "filtered.json"
    path.write_text(json.dumps({"name": "filtered", "queries": rows}), encoding="utf-8")
    return load_dataset(path)


def _retrieval_patches():
    async def fake_find_similar_chunks(*, doc_id, query_embedding, match_count, tenant_id, query_text=None, session_id=None, hybrid_enabled=None):
        return [_chunk(doc_id, 0)]

    find_similar = AsyncMock(side_effect=fake_find_similar_chunks)
    return find_similar, (
        patch("services.chat_service.find_similar_chunks", find_similar),
        patch(
            "services.chat_service.get_embeddings",
            AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts]),
        ),
    )


def _searched_doc_ids(find_similar: AsyncMock) -> set[str]:
    return {call.kwargs["doc_id"] for call in find_similar.await_args_list}


_ARM = EffectiveRetrievalConfig(label="filtered", hybrid_retrieval_enabled=False, enable_reranking=False)


@pytest.mark.asyncio
async def test_metadata_filter_narrows_documents_before_retrieval(tmp_path):
    dataset = _filter_dataset(tmp_path, [
        {
            "query": "legal docs only",
            "doc_ids": ["doc-legal", "doc-hr"],
            "relevant_chunks": [["doc-legal", 0]],
            "metadata_filter": {"department": "legal"},
        },
    ])
    filter_docs = AsyncMock(return_value=["doc-legal"])
    find_similar, (p1, p2) = _retrieval_patches()

    with p1, p2, patch("services.eval_service.filter_document_ids_by_metadata", filter_docs):
        result = await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test")

    filter_docs.assert_awaited_once_with(
        tenant_id="tenant-eval-test",
        doc_ids=["doc-legal", "doc-hr"],
        metadata_filter={"department": "legal"},
    )
    assert _searched_doc_ids(find_similar) == {"doc-legal"}
    qr = result.arms[0].query_results[0]
    assert {c["document_id"] for c in qr.candidates} == {"doc-legal"}
    assert qr.metadata_filter == {"department": "legal"}
    assert qr.filter_excluded_all_documents is False
    assert qr.metrics["mrr"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_metadata_filter_in_list_and_anded_keys_go_to_chat_helper(tmp_path):
    metadata_filter = {"department": {"in": ["legal", "hr"]}, "year": 2024}
    dataset = _filter_dataset(tmp_path, [
        {
            "query": "legal or hr in 2024",
            "doc_ids": ["doc-1", "doc-2", "doc-3"],
            "relevant_doc_ids": ["doc-3"],
            "metadata_filter": metadata_filter,
        },
    ])
    filter_docs = AsyncMock(return_value=["doc-1", "doc-3"])
    find_similar, (p1, p2) = _retrieval_patches()

    with p1, p2, patch("services.eval_service.filter_document_ids_by_metadata", filter_docs):
        result = await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test")

    # The eval passes the validated v1 filter through unchanged; containment
    # semantics live only in the shared helper.
    filter_docs.assert_awaited_once_with(
        tenant_id="tenant-eval-test",
        doc_ids=["doc-1", "doc-2", "doc-3"],
        metadata_filter=metadata_filter,
    )
    assert _searched_doc_ids(find_similar) == {"doc-1", "doc-3"}
    assert result.arms[0].query_results[0].metadata_filter == metadata_filter


@pytest.mark.asyncio
async def test_metadata_filter_excluding_everything_searches_nothing(tmp_path):
    dataset = _filter_dataset(tmp_path, [
        {
            "query": "nothing matches",
            "doc_ids": ["doc-1", "doc-2"],
            "relevant_doc_ids": ["doc-1"],
            "metadata_filter": {"department": "finance"},
        },
    ])
    filter_docs = AsyncMock(return_value=[])
    find_similar, (p1, p2) = _retrieval_patches()
    export_path = tmp_path / "run.json"

    with p1, p2, patch("services.eval_service.filter_document_ids_by_metadata", filter_docs), \
         patch("services.eval_service.retrieve_for_documents", AsyncMock()) as retrieve:
        result = await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test", export_path=export_path)

    retrieve.assert_not_awaited()
    find_similar.assert_not_awaited()
    qr = result.arms[0].query_results[0]
    assert qr.candidates == []
    assert qr.context_preview == ""
    assert qr.filter_excluded_all_documents is True
    assert all(value == 0.0 for value in qr.metrics.values())

    per_query = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["per_query_metrics"][0]
    assert per_query["metadata_filter"] == {"department": "finance"}
    assert per_query["filter_excluded_all_documents"] is True
    assert per_query["candidates"] == []
    assert per_query["original_query"] is None
    assert per_query["transformed_queries"] is None
    assert per_query["effective_retrieval_query"] is None
    assert per_query["timing_ms"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_filter", [{}, {"department": None}, {"department": {"gt": 1}}, ["legal"]])
async def test_malformed_metadata_filter_fails_the_run(tmp_path, bad_filter):
    dataset = _filter_dataset(tmp_path, [
        {"query": "fine", "doc_ids": ["doc-1"], "relevant_doc_ids": ["doc-1"]},
        {
            "query": "broken filter",
            "doc_ids": ["doc-1"],
            "relevant_doc_ids": ["doc-1"],
            "metadata_filter": bad_filter,
        },
    ])
    filter_docs = AsyncMock()
    find_similar, (p1, p2) = _retrieval_patches()

    with p1, p2, patch("services.eval_service.filter_document_ids_by_metadata", filter_docs), \
         pytest.raises(InvalidMetadataFilterError, match="broken filter"):
        await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test")

    filter_docs.assert_not_awaited()
    find_similar.assert_not_awaited()


@pytest.mark.asyncio
async def test_rows_without_metadata_filter_are_unchanged(tmp_path):
    dataset = load_dataset(FIXTURES_DIR / "basic_queries.json")
    filter_docs = AsyncMock()
    find_similar, (p1, p2) = _retrieval_patches()
    export_path = tmp_path / "run.json"

    with p1, p2, patch("services.eval_service.filter_document_ids_by_metadata", filter_docs):
        result = await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test", export_path=export_path)

    filter_docs.assert_not_awaited()
    assert _searched_doc_ids(find_similar) == {doc_id for q in dataset.queries for doc_id in q.doc_ids}
    for qr in result.arms[0].query_results:
        assert qr.metadata_filter is None
        assert qr.filter_excluded_all_documents is False
    per_query = json.loads(export_path.read_text(encoding="utf-8"))["arms"][0]["per_query_metrics"]
    assert all(row["metadata_filter"] is None for row in per_query)
