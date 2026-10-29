"""Dataset loader: relevance rows, no-evidence rows, and checked-in fixtures."""

import json
from pathlib import Path

import pytest

from services.eval_fixtures import EvalDatasetError, load_dataset

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eval"


def _write_dataset(tmp_path: Path, queries: list[dict], **extra) -> Path:
    payload = {"name": "fixture", "queries": queries, **extra}
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_basic_and_diverging_fixtures_still_load():
    basic = load_dataset(FIXTURES_DIR / "basic_queries.json")
    diverging = load_dataset(FIXTURES_DIR / "diverging_queries.json")

    assert basic.queries[0].doc_ids == ["fixture-doc-01"]
    assert basic.queries[0].relevant_chunks == [("fixture-doc-01", 2)]
    assert basic.queries[0].expected_result is None
    assert all(query.relevant_chunks for query in basic.queries)
    assert diverging.queries[0].relevant_chunks == [("fixture-doc-11", 9)]


def test_relevance_row_accepts_chunks_documents_or_both(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "chunk only",
                "relevant_chunks": [["policy", 1]],
            },
            {
                "query": "document only",
                "relevant_doc_ids": ["handbook"],
            },
            {
                "query": "both",
                "relevant_doc_ids": ["policy"],
                "relevant_chunks": [["policy", 0], ["handbook", 2]],
            },
        ],
    )

    loaded = load_dataset(path)

    assert loaded.queries[0].relevant_chunks == [("policy", 1)]
    assert loaded.queries[0].doc_ids == ["policy"]
    assert loaded.queries[1].relevant_doc_ids == ["handbook"]
    assert loaded.queries[1].doc_ids == ["handbook"]
    assert loaded.queries[2].relevant_doc_ids == ["policy"]
    assert loaded.queries[2].relevant_chunks == [("policy", 0), ("handbook", 2)]


def test_no_evidence_and_refusal_rows_load_without_relevant_chunks(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "What is the sabbatical stipend?",
                "expected_result": "no_supporting_evidence",
            },
            {
                "query": "What is the CEO home address?",
                "expected_result": "refusal",
            },
        ],
    )

    loaded = load_dataset(path)

    assert loaded.queries[0].expected_result == "no_supporting_evidence"
    assert loaded.queries[0].relevant_chunks == []
    assert loaded.queries[0].relevant_doc_ids == []
    assert loaded.queries[0].doc_ids == []
    assert loaded.queries[1].expected_result == "refusal"
    assert loaded.queries[1].relevant_keys() == set()


def test_row_with_neither_relevance_nor_declaration_fails(tmp_path):
    path = _write_dataset(tmp_path, [{"query": "Where is the warehouse?"}])

    with pytest.raises(EvalDatasetError, match="neither relevance labels"):
        load_dataset(path)


def test_declaration_combined_with_relevance_labels_fails(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "What is the stipend?",
                "expected_result": "no_supporting_evidence",
                "relevant_chunks": [["benefits", 0]],
            }
        ],
    )

    with pytest.raises(EvalDatasetError, match="also has relevance labels"):
        load_dataset(path)


def test_unknown_expected_result_fails(tmp_path):
    path = _write_dataset(
        tmp_path,
        [{"query": "What is the stipend?", "expected_result": "maybe"}],
    )

    with pytest.raises(EvalDatasetError, match="expected_result"):
        load_dataset(path)
