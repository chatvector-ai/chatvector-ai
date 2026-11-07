"""Answer-arm scoring. The generator is always a mock; no test calls a provider."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cli import cmd_eval, main
from core.config import config
from db.base import ChunkMatch
from services.chat_service import RetrievalResult
from services.eval_config import EffectiveRetrievalConfig
from services.eval_fixtures import EvalDataset, EvalQuery, ExpectedCitation, ExpectedFact, load_dataset
from services.eval_service import run_eval
from services.query_service import QueryTransformResult
from services.retrieval_config import RetrievalProcessDefaults, resolve_retrieval_config

_ARM = EffectiveRetrievalConfig(
    label="answers",
    hybrid_retrieval_enabled=False,
    enable_reranking=False,
)
_RANK_METRICS = ("mrr", "recall@5", "recall@10", "ndcg@5", "ndcg@10", "packed_presence")


def _write_dataset(tmp_path: Path, queries: list[dict]) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps({"name": "answers", "queries": queries}), encoding="utf-8")
    return path


def _chunk(
    doc_id: str,
    chunk_index: int,
    *,
    text: str = "chunk",
    page_number: int | None = None,
) -> ChunkMatch:
    return ChunkMatch(
        id=f"{doc_id}:{chunk_index}",
        chunk_text=text,
        document_id=doc_id,
        chunk_index=chunk_index,
        similarity=0.5,
        file_name=f"{doc_id}.txt",
        page_number=page_number,
    )


def _retrieval(
    context: str,
    *,
    chunks: list[ChunkMatch] | None = None,
    packed: list[ChunkMatch] | None = None,
    retrieved: list[ChunkMatch] | None = None,
) -> RetrievalResult:
    selected = list(chunks or [])
    return RetrievalResult(
        chunks=selected,
        queries=["embedded"],
        primary_query="embedded",
        context=context,
        timing_ms={"total": 1},
        transform_result=QueryTransformResult(queries=["embedded"], original_query="asked"),
        effective_config=resolve_retrieval_config({}, RetrievalProcessDefaults.from_process()),
        retrieved_chunks=list(retrieved if retrieved is not None else selected),
        packed_chunks=list(packed if packed is not None else selected),
    )


async def _run(dataset, retrievals: dict, generate, *, answers: bool, export_path=None):
    async def fake_retrieve(query, doc_ids, tenant_id, request_config, **kwargs):
        del doc_ids, tenant_id, request_config, kwargs
        return retrievals[query]

    with patch("services.eval_service.retrieve_for_documents", AsyncMock(side_effect=fake_retrieve)):
        return await run_eval(
            dataset,
            [_ARM],
            tenant_id="tenant-eval-test",
            export_path=export_path,
            answer_generation=answers,
            generate_answer=generate,
        )


def _rows(export_path: Path) -> tuple[dict, dict]:
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    arm = payload["arms"][0]
    rows = {row["query"]: row for row in arm["per_query_metrics"]}
    return rows, arm["config_snapshot"]["resolved_environment"]


@pytest.mark.asyncio
async def test_default_run_does_not_call_generate_answer_when_labels_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "guessed-provider")
    monkeypatch.setattr(config, "LLM_MODEL", "guessed-model")
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "How long is retention?",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
            }
        ],
    )
    dataset = load_dataset(path)
    export_path = tmp_path / "retrieval-only.json"

    async def generate(question, context):
        raise AssertionError("generate_answer must not be called")

    result = await _run(
        dataset,
        {"How long is retention?": _retrieval("seven years")},
        generate,
        answers=False,
        export_path=export_path,
    )

    row = result.arms[0].query_results[0]
    assert "completeness" not in row.metrics
    assert "mrr" in row.metrics
    assert row.answer is None
    exported, environment = _rows(export_path)
    assert "answer" not in exported["How long is retention?"]
    assert environment["llm_provider"] is None
    assert environment["llm_model"] is None


@pytest.mark.asyncio
async def test_completeness_counts_fact_text_and_alternates_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock-provider")
    monkeypatch.setattr(config, "LLM_MODEL", "not-the-return-value")
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "contains fact",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
            },
            {
                "query": "half the facts",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years", "board approval"],
            },
            {
                "query": "contains alternate",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": [{"text": "seven years", "alternates": ["7 years"]}],
            },
            {
                "query": "contains neither",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
            },
            {
                "query": "retrieval only",
                "relevant_chunks": [["policy", 0]],
            },
        ],
    )
    dataset = load_dataset(path)
    calls: list[tuple[str, str]] = []

    async def generate(question, context):
        calls.append((question, context))
        answers = {
            "contains fact": "SEVEN YEARS is the period.",
            "half the facts": "SEVEN YEARS is the period.",
            "contains alternate": "Use 7 years here.",
            "contains neither": "No number is stated.",
        }
        return answers[question], 4, "mock-eval-model"

    contexts = {query.query: f"packed context for {query.query}" for query in dataset.queries}
    export_path = tmp_path / "answers.json"
    result = await _run(
        dataset,
        {query: _retrieval(context) for query, context in contexts.items()},
        generate,
        answers=True,
        export_path=export_path,
    )

    by_query = {row.query: row for row in result.arms[0].query_results}
    assert by_query["contains fact"].metrics["completeness"] == pytest.approx(1.0)
    assert by_query["half the facts"].metrics["completeness"] == pytest.approx(0.5)
    assert by_query["contains alternate"].metrics["completeness"] == pytest.approx(1.0)
    assert by_query["contains neither"].metrics["completeness"] == pytest.approx(0.0)
    assert "completeness" not in by_query["retrieval only"].metrics
    assert result.arms[0].aggregate_metrics["completeness"] == pytest.approx((1.0 + 0.5 + 1.0 + 0.0) / 4)
    assert [question for question, _context in calls] == [
        "contains fact",
        "half the facts",
        "contains alternate",
        "contains neither",
    ]
    assert calls[0] == ("contains fact", "packed context for contains fact")
    assert by_query["contains fact"].context_preview == "packed context for contains fact"
    assert by_query["contains fact"].answer == "SEVEN YEARS is the period."
    assert by_query["retrieval only"].answer is None

    exported, environment = _rows(export_path)
    assert exported["contains fact"]["answer"] == "SEVEN YEARS is the period."
    assert exported["contains fact"]["context_preview"] == "packed context for contains fact"
    assert exported["retrieval only"]["answer"] is None
    assert environment["llm_model"] == "mock-eval-model"
    assert environment["llm_model"] != config.LLM_MODEL
    assert environment["llm_provider"] == "mock-provider"
    assert environment["prompt_persona"] == config.PROMPT_PERSONA


@pytest.mark.asyncio
async def test_refusal_passes_only_when_a_phrase_is_present_and_forbidden_is_absent(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "one phrase",
                "expected_result": "refusal",
                "expected_refusal": {
                    "phrases": ["not in the documents", "cannot answer"],
                    "forbidden": ["12 Oak Street"],
                },
            },
            {
                "query": "missing phrase",
                "expected_result": "no_supporting_evidence",
                "expected_refusal": {
                    "phrases": ["not in the documents"],
                    "forbidden": ["12 Oak Street"],
                },
            },
            {
                "query": "forbidden present",
                "expected_result": "refusal",
                "expected_refusal": {
                    "phrases": ["not in the documents"],
                    "forbidden": ["12 Oak Street"],
                },
            },
        ],
    )
    dataset = load_dataset(path)

    async def generate(question, context):
        del context
        answers = {
            "one phrase": "This is NOT IN THE DOCUMENTS.",
            "missing phrase": "The address is unknown.",
            "forbidden present": "Not in the documents: 12 Oak Street",
        }
        return answers[question], 1, "mock-eval-model"

    result = await _run(
        dataset,
        {query.query: _retrieval("no home address") for query in dataset.queries},
        generate,
        answers=True,
    )
    scores = {row.query: row.metrics["refusal_correctness"] for row in result.arms[0].query_results}
    assert scores == {"one phrase": 1.0, "missing phrase": 0.0, "forbidden present": 0.0}
    assert result.arms[0].aggregate_metrics["refusal_correctness"] == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_no_evidence_row_skips_rank_metrics_and_retrieval_only_is_not_generated(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "What is the stipend?",
                "expected_result": "no_supporting_evidence",
                "expected_refusal": {"phrases": ["not in the corpus"], "forbidden": []},
            },
            {
                "query": "Where is the policy?",
                "relevant_chunks": [["policy", 0]],
            },
        ],
    )
    dataset = load_dataset(path)
    assert dataset.queries[0].relevant_chunks == []
    assert dataset.queries[0].relevant_doc_ids == []
    calls: list[str] = []

    async def generate(question, context):
        del context
        calls.append(question)
        return "That is not in the corpus.", 1, "mock-eval-model"

    packed = _chunk("policy", 0)
    result = await _run(
        dataset,
        {
            "What is the stipend?": _retrieval("empty of stipends", packed=[packed]),
            "Where is the policy?": _retrieval("policy text", chunks=[packed], packed=[packed]),
        },
        generate,
        answers=True,
    )
    refusal, retrieval = result.arms[0].query_results
    assert calls == ["What is the stipend?"]
    assert refusal.metrics == {"refusal_correctness": 1.0}
    assert all(name not in refusal.metrics for name in _RANK_METRICS)
    assert retrieval.answer is None
    assert retrieval.metrics["mrr"] == pytest.approx(1.0)
    assert "refusal_correctness" not in retrieval.metrics
    assert result.arms[0].aggregate_metrics["mrr"] == pytest.approx(1.0)

    async def forbidden(question, context):
        raise AssertionError("generate_answer must not be called")

    quiet = await _run(
        dataset,
        {
            "What is the stipend?": _retrieval(""),
            "Where is the policy?": _retrieval("policy text", chunks=[packed], packed=[packed]),
        },
        forbidden,
        answers=False,
    )
    assert quiet.arms[0].query_results[0].metrics == {}
    assert "mrr" in quiet.arms[0].query_results[1].metrics


@pytest.mark.asyncio
async def test_citation_support_requires_the_packed_chunk(tmp_path):
    target = _chunk("run-doc-retention", 2, text="retention-policy chunk 2", page_number=4)
    other = _chunk("run-doc-retention", 0, text="other chunk", page_number=1)
    dropped = _retrieval(
        "the context still mentions retention-policy chunk 2",
        chunks=[target, other],
        retrieved=[target, other],
        packed=[other],
    )
    included = _retrieval(
        "unrelated packed text",
        chunks=[other],
        retrieved=[other],
        packed=[target],
    )
    page_hit = _retrieval("page text", packed=[target])
    page_miss = _retrieval("page text", packed=[other])
    dataset = EvalDataset(
        name="citations",
        queries=[
            EvalQuery(
                query="dropped",
                doc_ids=["run-doc-retention"],
                logical_doc_ids=["retention-policy"],
                relevant_chunks=[("run-doc-retention", 2)],
                logical_relevant_chunks=[("retention-policy", 2)],
                expected_citation=ExpectedCitation("retention-policy", chunk_index=2),
            ),
            EvalQuery(
                query="included by logical key",
                doc_ids=["run-doc-retention"],
                logical_doc_ids=["retention-policy"],
                relevant_chunks=[("run-doc-retention", 2)],
                logical_relevant_chunks=[("retention-policy", 2)],
                expected_citation=ExpectedCitation("retention-policy", chunk_index=2),
            ),
            EvalQuery(
                query="included by runtime id",
                doc_ids=["run-doc-retention"],
                relevant_chunks=[("run-doc-retention", 2)],
                expected_citation=ExpectedCitation("run-doc-retention", chunk_index=2),
            ),
            EvalQuery(
                query="included by resolved id",
                doc_ids=["run-doc-retention"],
                relevant_doc_ids=["run-doc-retention"],
                expected_citation=ExpectedCitation(
                    "retention-policy",
                    chunk_index=2,
                    resolved_document_id="run-doc-retention",
                ),
            ),
            EvalQuery(
                query="page matches",
                doc_ids=["run-doc-retention"],
                relevant_doc_ids=["run-doc-retention"],
                expected_citation=ExpectedCitation("run-doc-retention", page=4),
            ),
            EvalQuery(
                query="page misses",
                doc_ids=["run-doc-retention"],
                relevant_doc_ids=["run-doc-retention"],
                expected_citation=ExpectedCitation("run-doc-retention", page=9),
            ),
        ],
    )

    async def generate(question, context):
        del question, context
        return "unused answer", 1, "mock-eval-model"

    result = await _run(
        dataset,
        {
            "dropped": dropped,
            "included by logical key": included,
            "included by runtime id": included,
            "included by resolved id": included,
            "page matches": page_hit,
            "page misses": page_miss,
        },
        generate,
        answers=True,
    )
    scores = {row.query: row.metrics["citation_support"] for row in result.arms[0].query_results}
    assert scores == {
        "dropped": 0.0,
        "included by logical key": 1.0,
        "included by runtime id": 1.0,
        "included by resolved id": 1.0,
        "page matches": 1.0,
        "page misses": 0.0,
    }
    dropped_row = result.arms[0].query_results[0]
    assert dropped_row.evidence[0]["document_id"] == "run-doc-retention"
    assert dropped_row.evidence[0]["logical_key"] == "retention-policy"
    assert dropped_row.evidence[0]["packed"] is False
    assert "retention-policy chunk 2" in dropped_row.context_preview


@pytest.mark.asyncio
async def test_groundedness_uses_saved_context_and_must_not_claim(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "forbidden claim",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
                "must_not_claim": ["sabbatical stipend"],
            },
            {
                "query": "fact missing from context",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
            },
            {
                "query": "alternate grounded",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": [{"text": "seven years", "alternates": ["7 years"]}],
            },
            {
                "query": "fact absent from answer",
                "relevant_chunks": [["policy", 0]],
                "expected_facts": ["seven years"],
            },
            {
                "query": "citation only",
                "relevant_chunks": [["policy", 0]],
                "expected_citation": {"document": "policy", "chunk_index": 0},
            },
        ],
    )
    dataset = load_dataset(path)
    packed = _chunk("policy", 0, text="seven years lives only on the chunk")

    async def generate(question, context):
        del context
        answers = {
            "forbidden claim": "SEVEN YEARS plus a Sabbatical Stipend.",
            "fact missing from context": "The period is seven years.",
            "alternate grounded": "about 7 years",
            "fact absent from answer": "I do not know.",
            "citation only": "See the policy.",
        }
        return answers[question], 1, "mock-eval-model"

    result = await _run(
        dataset,
        {
            "forbidden claim": _retrieval("seven years is written here", packed=[packed]),
            "fact missing from context": _retrieval("no dates here", packed=[packed]),
            "alternate grounded": _retrieval("retained for seven years", packed=[packed]),
            "fact absent from answer": _retrieval("", packed=[packed]),
            "citation only": _retrieval("no citation prose", packed=[packed]),
        },
        generate,
        answers=True,
    )
    by_query = {row.query: row for row in result.arms[0].query_results}
    assert by_query["forbidden claim"].metrics["groundedness"] == pytest.approx(0.0)
    assert by_query["forbidden claim"].metrics["completeness"] == pytest.approx(1.0)
    assert by_query["fact missing from context"].metrics["groundedness"] == pytest.approx(0.0)
    assert by_query["alternate grounded"].metrics["groundedness"] == pytest.approx(1.0)
    assert by_query["fact absent from answer"].metrics["groundedness"] == pytest.approx(1.0)
    assert by_query["fact absent from answer"].metrics["completeness"] == pytest.approx(0.0)
    assert "groundedness" not in by_query["citation only"].metrics
    assert by_query["citation only"].metrics["citation_support"] == pytest.approx(1.0)
    labeled = [
        by_query["forbidden claim"].metrics["groundedness"],
        by_query["fact missing from context"].metrics["groundedness"],
        by_query["alternate grounded"].metrics["groundedness"],
        by_query["fact absent from answer"].metrics["groundedness"],
    ]
    assert result.arms[0].aggregate_metrics["groundedness"] == pytest.approx(sum(labeled) / len(labeled))


@pytest.mark.asyncio
async def test_answer_generation_requires_the_injected_callable():
    dataset = EvalDataset(
        name="missing-generator",
        queries=[EvalQuery(query="q", relevant_doc_ids=["policy"], expected_facts=[ExpectedFact("fact")])],
    )

    with pytest.raises(ValueError, match="generate_answer"):
        await run_eval(dataset, [_ARM], tenant_id="tenant-eval-test", answer_generation=True)


def test_answers_flag_defaults_off(monkeypatch):
    captured: dict = {}

    async def fake_cmd(*args, answer_generation=False, **kwargs):
        del args, kwargs
        captured["answer_generation"] = answer_generation

    monkeypatch.setattr("cli.cmd_eval", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        ["backend.cli", "eval", "--dataset", "queries.json", "--tenant-id", "tenant"],
    )
    main()
    assert captured["answer_generation"] is False


def test_answers_flag_is_passed_through(monkeypatch):
    captured: dict = {}

    async def fake_cmd(*args, answer_generation=False, **kwargs):
        del args, kwargs
        captured["answer_generation"] = answer_generation

    monkeypatch.setattr("cli.cmd_eval", fake_cmd)
    monkeypatch.setattr(
        sys,
        "argv",
        ["backend.cli", "eval", "--dataset", "queries.json", "--tenant-id", "tenant", "--answers"],
    )
    main()
    assert captured["answer_generation"] is True


@pytest.mark.asyncio
async def test_cmd_eval_answer_flag_injects_generate_answer_without_calling_it(tmp_path, monkeypatch):
    path = _write_dataset(
        tmp_path,
        [{"query": "How long is retention?", "relevant_chunks": [["policy", 0]], "expected_facts": ["seven years"]}],
    )
    captured: dict = {}

    async def fake_run(dataset, arms, **kwargs):
        del dataset, arms
        captured["answer_generation"] = kwargs["answer_generation"]
        captured["generate_answer"] = kwargs["generate_answer"]
        from services.eval_service import EvalRunResult

        return EvalRunResult(
            run_id="run",
            timestamp="t",
            tool_version="v",
            dataset_name="d",
            dataset_hash="h",
            arms=[],
        )

    async def fake_generate(question, context):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("services.eval_service.run_eval", fake_run)
    monkeypatch.setattr("services.answer_service.generate_answer", fake_generate)

    await cmd_eval(str(path), "tenant", [5], [], 5, None, False, None, answer_generation=False)
    assert captured["answer_generation"] is False
    assert captured["generate_answer"] is None

    await cmd_eval(str(path), "tenant", [5], [], 5, None, False, None, answer_generation=True)
    assert captured["answer_generation"] is True
    assert captured["generate_answer"] is fake_generate
