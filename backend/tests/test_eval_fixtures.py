"""Dataset loader: relevance rows, no-evidence rows, manifests, and fixtures."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cli import cmd_eval
from services.eval_fixtures import (
    EvalDatasetError,
    ExpectedCitation,
    ExpectedFact,
    ExpectedRefusal,
    load_dataset,
)

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
    assert basic.queries[0].expected_facts == []
    assert basic.queries[0].expected_refusal is None
    assert basic.queries[0].expected_citation is None
    assert basic.queries[0].must_not_claim == []
    assert basic.queries[0].has_answer_labels() is False
    assert basic.queries[0].logical_doc_ids == []
    assert all(query.relevant_chunks for query in basic.queries)
    assert diverging.queries[0].relevant_chunks == [("fixture-doc-11", 9)]


_CHUNK_SETTINGS = {
    "chunking_strategy": "fixed",
    "chunk_size": 1000,
    "chunk_overlap": 200,
}


def _manifest(documents: list[dict], **chunk_overrides) -> dict:
    recorded = {
        "CHUNK_SIZE": 1000,
        "CHUNK_OVERLAP": 200,
        "CHUNKING_STRATEGY": "fixed",
    }
    recorded.update(chunk_overrides)
    return {
        "tenant_id": "eval-tenant",
        "chunk_settings": recorded,
        "documents": documents,
    }


def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_answer_labels_load_on_relevance_and_no_evidence_rows(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "How long is the retention period?",
                "relevant_chunks": [["policy", 1]],
                "expected_facts": [
                    "seven years",
                    {"text": "30 days", "alternates": ["thirty days"]},
                ],
                "expected_citation": {"document": "policy", "chunk_index": 1, "page": 4},
                "must_not_claim": ["indefinite retention"],
            },
            {
                "query": "What is the chair's home address?",
                "expected_result": "refusal",
                "expected_refusal": {
                    "phrases": ["not in the documents", "I cannot answer that"],
                    "forbidden": ["12 Oak Street"],
                },
            },
        ],
    )

    loaded = load_dataset(path)

    scored = loaded.queries[0]
    assert scored.expected_facts == [
        ExpectedFact("seven years"),
        ExpectedFact("30 days", ("thirty days",)),
    ]
    assert scored.expected_citation == ExpectedCitation("policy", chunk_index=1, page=4)
    assert scored.must_not_claim == ["indefinite retention"]
    assert scored.has_answer_labels() is True
    assert scored.relevant_chunks == [("policy", 1)]

    refusal = loaded.queries[1]
    assert refusal.relevant_chunks == []
    assert refusal.relevant_doc_ids == []
    assert refusal.expected_result == "refusal"
    assert refusal.expected_refusal == ExpectedRefusal(
        ("not in the documents", "I cannot answer that"),
        ("12 Oak Street",),
    )
    assert refusal.has_answer_labels() is True


def test_citation_keeps_logical_key_and_resolved_document_id(tmp_path):
    questions = _write_dataset(
        tmp_path,
        [
            {
                "query": "How long is the retention period?",
                "doc_ids": ["retention-policy"],
                "relevant_chunks": [["retention-policy", 2]],
                "expected_citation": {"document": "retention-policy", "chunk_index": 2},
            },
            {
                "query": "Which runtime id was already written?",
                "doc_ids": ["retention-policy"],
                "relevant_doc_ids": ["retention-policy"],
                "expected_citation": {"document": "run-doc-retention"},
            },
        ],
        chunk_settings=_CHUNK_SETTINGS,
    )
    manifest = _write_manifest(
        tmp_path,
        _manifest(
            [
                {
                    "logical_key": "retention-policy",
                    "file_name": "retention.txt",
                    "document_id": "run-doc-retention",
                    "metadata": {},
                    "status": "completed",
                }
            ]
        ),
    )

    logical, runtime = load_dataset(questions, manifest).queries

    assert logical.expected_citation == ExpectedCitation(
        "retention-policy",
        chunk_index=2,
        resolved_document_id="run-doc-retention",
    )
    assert runtime.expected_citation == ExpectedCitation("run-doc-retention")
    assert runtime.relevant_doc_ids == ["run-doc-retention"]


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"query": "fact", "relevant_doc_ids": ["policy"], "expected_facts": []}, "expected_facts"),
        (
            {"query": "fact", "relevant_doc_ids": ["policy"], "expected_facts": [{"alternates": ["x"]}]},
            "expected_facts",
        ),
        (
            {
                "query": "fact",
                "relevant_doc_ids": ["policy"],
                "expected_facts": [{"text": "seven years", "paraphrase": "7 years"}],
            },
            "expected_facts",
        ),
        (
            {"query": "refuse", "expected_result": "refusal", "expected_refusal": {"forbidden": ["secret"]}},
            "expected_refusal",
        ),
        (
            {"query": "cite", "relevant_doc_ids": ["policy"], "expected_citation": {"chunk_index": 1}},
            "expected_citation",
        ),
        (
            {
                "query": "cite",
                "relevant_doc_ids": ["policy"],
                "expected_citation": {"document": "policy", "chunk_index": True},
            },
            "expected_citation",
        ),
        ({"query": "claim", "relevant_doc_ids": ["policy"], "must_not_claim": [""]}, "must_not_claim"),
    ],
)
def test_invalid_answer_labels_fail(tmp_path, row, match):
    path = _write_dataset(tmp_path, [row])

    with pytest.raises(EvalDatasetError, match=match):
        load_dataset(path)


def test_unknown_expected_result_fails(tmp_path):
    path = _write_dataset(
        tmp_path,
        [{"query": "What is the stipend?", "expected_result": "maybe"}],
    )

    with pytest.raises(EvalDatasetError, match="expected_result"):
        load_dataset(path)


def test_manifest_resolves_logical_key_and_keeps_it(tmp_path):
    questions = _write_dataset(
        tmp_path,
        [
            {
                "query": "How long is the retention period?",
                "doc_ids": ["retention-policy"],
                "relevant_doc_ids": ["retention-policy"],
                "relevant_chunks": [["retention-policy", 2]],
            }
        ],
        chunk_settings={**_CHUNK_SETTINGS, "chunking_strategy": "Fixed"},
    )
    manifest = _write_manifest(
        tmp_path,
        _manifest(
            [
                {
                    "logical_key": "retention-policy",
                    "file_name": "retention.txt",
                    "document_id": "run-doc-retention",
                    "metadata": {"department": "legal"},
                    "status": "completed",
                }
            ]
        ),
    )

    query = load_dataset(questions, manifest).queries[0]

    assert query.doc_ids == ["run-doc-retention"]
    assert query.logical_doc_ids == ["retention-policy"]
    assert query.relevant_doc_ids == ["run-doc-retention"]
    assert query.logical_relevant_doc_ids == ["retention-policy"]
    assert query.relevant_chunks == [("run-doc-retention", 2)]
    assert query.logical_relevant_chunks == [("retention-policy", 2)]


def test_tenant_scope_searches_manifest_documents_and_records_filter(tmp_path):
    questions = _write_dataset(
        tmp_path,
        [
            {
                "query": "Which policy governs after-hours badge access?",
                "scope": "tenant",
                "relevant_chunks": [["security-access", 0]],
                "metadata_filter": {"department": "security"},
            }
        ],
        chunk_settings=_CHUNK_SETTINGS,
    )
    manifest = _write_manifest(
        tmp_path,
        _manifest(
            [
                {
                    "logical_key": "security-access",
                    "file_name": "security.md",
                    "document_id": "run-doc-security",
                    "metadata": {"department": "security"},
                    "status": "completed",
                },
                {
                    "logical_key": "hr-pto",
                    "file_name": "pto.md",
                    "document_id": "run-doc-pto",
                    "metadata": {"department": "hr"},
                    "status": "completed",
                },
            ]
        ),
    )

    without_manifest = load_dataset(questions).queries[0]
    assert without_manifest.scope == "tenant"
    assert without_manifest.doc_ids == []
    assert without_manifest.metadata_filter == {"department": "security"}

    query = load_dataset(questions, manifest).queries[0]
    assert query.doc_ids == ["run-doc-security", "run-doc-pto"]
    assert query.logical_doc_ids == ["security-access", "hr-pto"]
    assert query.relevant_chunks == [("run-doc-security", 0)]
    assert query.logical_relevant_chunks == [("security-access", 0)]
    assert query.metadata_filter == {"department": "security"}


def test_tenant_scope_rejects_pasted_doc_ids(tmp_path):
    path = _write_dataset(
        tmp_path,
        [
            {
                "query": "Which policy governs badge access?",
                "scope": "tenant",
                "doc_ids": ["security-access"],
                "relevant_chunks": [["security-access", 0]],
            }
        ],
    )

    with pytest.raises(EvalDatasetError, match="also lists doc_ids"):
        load_dataset(path)


def test_unknown_logical_key_fails(tmp_path):
    questions = _write_dataset(
        tmp_path,
        [
            {
                "query": "Where is the bond code?",
                "relevant_chunks": [["missing-doc", 0]],
            }
        ],
        chunk_settings=_CHUNK_SETTINGS,
    )
    manifest = _write_manifest(
        tmp_path,
        _manifest(
            [
                {
                    "logical_key": "other-doc",
                    "file_name": "other.md",
                    "document_id": "run-doc-other",
                    "metadata": {},
                    "status": "completed",
                }
            ]
        ),
    )

    with pytest.raises(EvalDatasetError, match="missing-doc"):
        load_dataset(questions, manifest)


@pytest.mark.parametrize(
    ("question_overrides", "manifest_overrides", "match"),
    [
        ({"chunk_size": 1000}, {"CHUNK_SIZE": 500}, "chunk_size"),
        ({"chunk_overlap": 200}, {"CHUNK_OVERLAP": 0}, "chunk_overlap"),
        ({"chunking_strategy": "fixed"}, {"CHUNKING_STRATEGY": "semantic"}, "chunking_strategy"),
    ],
)
async def test_chunk_setting_mismatch_fails_before_metrics(
    tmp_path,
    question_overrides,
    manifest_overrides,
    match,
):
    questions = _write_dataset(
        tmp_path,
        [
            {
                "query": "How long is the retention period?",
                "relevant_chunks": [["retention-policy", 0]],
            }
        ],
        chunk_settings={**_CHUNK_SETTINGS, **question_overrides},
    )
    manifest = _write_manifest(
        tmp_path,
        _manifest(
            [
                {
                    "logical_key": "retention-policy",
                    "file_name": "retention.txt",
                    "document_id": "run-doc-retention",
                    "metadata": {},
                    "status": "completed",
                }
            ],
            **manifest_overrides,
        ),
    )

    with patch("services.eval_service.run_eval", new=AsyncMock()) as run_eval:
        with pytest.raises(EvalDatasetError, match=match):
            await cmd_eval(
                str(questions),
                "dev",
                [5],
                [],
                5,
                None,
                False,
                str(manifest),
            )

    run_eval.assert_not_called()
