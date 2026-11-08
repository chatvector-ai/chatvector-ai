"""Checked-in Brinewick corpus: loader declaration, question labels, and cases."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cli import cmd_eval
from services.eval_corpus import _content_type_for, _load_declaration
from services.eval_fixtures import EvalDatasetError, ExpectedFact, load_dataset
from services.eval_service import _completeness
from services.eval_metrics import recall_at_k
from services.extraction_service import (
    build_document_extractor,
    prepare_extracted_document_for_chunking,
)
from services.ingestion_pipeline import FixedChunkingStrategy, IngestionPipeline

ROOT = Path(__file__).resolve().parents[1] / "eval" / "brinewick"
CORPUS_DIR = ROOT / "corpus"
DECLARED_CHUNKING = {
    "chunking_strategy": "fixed",
    "chunk_size": 1000,
    "chunk_overlap": 200,
}
REQUIRED_CASES = frozenset(
    {
        "overlapping_policies",
        "stale_version",
        "similar_names",
        "department_hr",
        "department_finance",
        "department_security",
        "department_product",
        "department_engineering",
        "department_support",
        "department_contracts",
        "department_incidents",
        "department_pricing",
        "customer_terms",
        "exact_identifier",
        "code",
        "policy_number",
        "acronym",
        "exact_phrase",
        "paraphrase",
        "metadata_department",
        "metadata_currency",
        "metadata_customer",
        "conflicting_facts",
        "absent_fact",
        "multi_document",
        "long_document",
        "near_duplicate",
        "chunk_boundary",
    }
)
LEXICAL_CASES = frozenset(
    {"exact_identifier", "code", "policy_number", "acronym", "exact_phrase"}
)
DEPARTMENTS = frozenset(
    {
        "hr",
        "finance",
        "security",
        "product",
        "engineering",
        "support",
        "contracts",
        "incidents",
        "pricing",
    }
)
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _production_chunks(file_name: str, payload: bytes) -> list[str]:
    """Chunk the way ingest does, at the settings the question file declares."""
    content_type = _content_type_for(file_name)
    document = build_document_extractor(content_type, filename=file_name).extract(
        payload, filename=file_name
    )
    text, boundaries = prepare_extracted_document_for_chunking(
        document.text,
        document.page_boundaries,
        content_type=content_type,
    )
    chunks = FixedChunkingStrategy(
        chunk_size=DECLARED_CHUNKING["chunk_size"],
        chunk_overlap=DECLARED_CHUNKING["chunk_overlap"],
    ).chunk_text(text)
    return [chunk.page_content for chunk in chunks]


def _matches(metadata: dict, metadata_filter: dict) -> bool:
    return all(metadata.get(key) == value for key, value in metadata_filter.items())


@pytest.fixture(scope="module")
def brinewick():
    declaration = _load_declaration(ROOT / "corpus.json")
    questions = _read_json(ROOT / "questions.json")
    index = _read_json(ROOT / "index.json")
    files = {}
    chunks = {}
    for item in declaration.documents:
        payload = (CORPUS_DIR / item.file_name).read_bytes()
        files[item.logical_key] = payload
        chunks[item.logical_key] = _production_chunks(item.file_name, payload)
    return SimpleNamespace(
        declaration=declaration,
        questions=questions,
        index=index,
        files=files,
        chunks=chunks,
        dataset=load_dataset(ROOT / "questions.json"),
    )


def _text(brinewick, logical_key: str) -> str:
    return brinewick.files[logical_key].decode("utf-8")


def _row(brinewick, query_id: str) -> dict:
    for row in brinewick.questions["queries"]:
        if row["id"] == query_id:
            return row
    raise AssertionError(f"missing question {query_id}")


def _evidence_locations(brinewick, evidence: list[dict]) -> tuple[list[str], list[list]]:
    doc_ids: list[str] = []
    chunks: list[list] = []
    for item in evidence:
        key = item["document"]
        needle = item["contains"]
        if key not in doc_ids:
            doc_ids.append(key)
        found = [
            index
            for index, chunk in enumerate(brinewick.chunks[key])
            if needle in chunk
        ]
        assert found, f"{needle!r} is not in any chunk of {key}"
        for index in found:
            pair = [key, index]
            if pair not in chunks:
                chunks.append(pair)
    return doc_ids, chunks


def test_loader_accepts_the_checked_in_declaration(brinewick):
    declaration = brinewick.declaration
    assert declaration.chunk_size == 1000
    assert declaration.chunk_overlap == 200
    assert declaration.chunking_strategy == "fixed"
    assert brinewick.questions["chunk_settings"] == DECLARED_CHUNKING

    names = [item.file_name for item in declaration.documents]
    assert sorted(path.name for path in CORPUS_DIR.iterdir()) == sorted(names)
    pipeline = IngestionPipeline()
    for item in declaration.documents:
        payload = brinewick.files[item.logical_key]
        assert payload
        pipeline.validate_file(
            SimpleNamespace(
                filename=item.file_name,
                content_type=_content_type_for(item.file_name),
            ),
            payload,
        )
        for value in item.metadata.values():
            assert isinstance(value, (str, int, float, bool))


def test_question_file_loads_with_relevance_and_no_evidence_rows(brinewick):
    rows = brinewick.questions["queries"]
    loaded = brinewick.dataset.queries
    assert [query.query for query in loaded] == [row["query"] for row in rows]
    assert brinewick.dataset.chunk_settings == DECLARED_CHUNKING

    keys = {item.logical_key for item in brinewick.declaration.documents}
    relevance_rows = [
        row for row in rows if row.get("relevant_chunks") or row.get("relevant_doc_ids")
    ]
    no_evidence = [row for row in rows if row.get("expected_result") == "no_supporting_evidence"]
    refusals = [row for row in rows if row.get("expected_result") == "refusal"]
    assert relevance_rows and no_evidence and refusals

    for row, query in zip(rows, loaded):
        assert "doc_ids" not in row
        assert row["scope"] == "tenant"
        assert isinstance(row["metadata_filter"], dict) and row["metadata_filter"]
        referenced = set(row.get("relevant_doc_ids", []))
        referenced.update(pair[0] for pair in row.get("relevant_chunks", []))
        assert referenced <= keys
        if row.get("expected_result"):
            assert "relevant_chunks" not in row
            assert "relevant_doc_ids" not in row
            assert query.expected_result == row["expected_result"]
            assert query.relevant_chunks == []
            assert query.relevant_doc_ids == []
            assert query.relevant_keys() == set()
            assert query.expected_refusal is not None
            assert query.has_answer_labels() is True
        else:
            assert query.expected_result is None
            assert query.expected_facts
            assert query.expected_citation is not None
            assert query.has_answer_labels() is True


def test_every_listed_case_has_a_document_or_question(brinewick):
    cases = brinewick.index["cases"]
    assert REQUIRED_CASES <= set(cases)
    query_ids = [row["id"] for row in brinewick.questions["queries"]]
    keys = {item.logical_key for item in brinewick.declaration.documents}
    covered: set[str] = set()
    for case in REQUIRED_CASES:
        bucket = cases[case]
        assert bucket["documents"] or bucket["questions"]
        assert set(bucket["documents"]) <= keys
        assert set(bucket["questions"]) <= set(query_ids)
        tagged = [row["id"] for row in brinewick.questions["queries"] if case in row["cases"]]
        assert bucket["questions"] == tagged
        covered.update(bucket["documents"])
    assert covered == keys

    departments = {item.metadata.get("department") for item in brinewick.declaration.documents}
    assert DEPARTMENTS <= departments
    currencies = {item.metadata.get("currency") for item in brinewick.declaration.documents}
    assert {"USD", "EUR"} <= currencies
    customers = {
        item.metadata["customer"]
        for item in brinewick.declaration.documents
        if "customer" in item.metadata
    }
    assert {"keel-and-co", "keel-cooperative", "marrow-shipping"} <= customers


def test_labels_match_the_chunks_that_contain_each_fact(brinewick):
    catalog = brinewick.index["questions"]
    for row in brinewick.questions["queries"]:
        spec = catalog[row["id"]]
        evidence = spec["evidence"]
        if row.get("expected_result"):
            assert evidence == []
            continue
        doc_ids, chunks = _evidence_locations(brinewick, evidence)
        assert row["relevant_chunks"] == chunks
        assert {pair[0] for pair in chunks} == set(doc_ids)
        assert "relevant_doc_ids" not in row
        loaded = next(query for query in brinewick.dataset.queries if query.query == row["query"])
        ranked = list(loaded.relevant_chunks)
        assert recall_at_k(ranked, loaded.relevant_keys(), len(ranked)) == 1.0
        for item in evidence:
            assert item["contains"] in _text(brinewick, item["document"])
            owners = [
                key
                for key, payload in brinewick.files.items()
                if item["contains"].encode("utf-8") in payload
            ]
            assert owners == [item["document"]]


def test_lexical_questions_quote_a_labeled_term(brinewick):
    seen = set()
    for row in brinewick.questions["queries"]:
        overlap = LEXICAL_CASES.intersection(row["cases"])
        if not overlap:
            continue
        seen.update(overlap)
        term = brinewick.index["questions"][row["id"]]["lexical_term"]
        assert isinstance(term, str) and term
        assert term in row["query"]
        assert row["relevant_chunks"]
        labeled = "\n".join(
            brinewick.chunks[key][index] for key, index in row["relevant_chunks"]
        )
        assert term in labeled
    assert seen == LEXICAL_CASES


def test_paraphrase_question_does_not_repeat_the_labeled_sentence(brinewick):
    paraphrases = [
        row for row in brinewick.questions["queries"] if "paraphrase" in row["cases"]
    ]
    assert paraphrases
    for row in paraphrases:
        evidence = brinewick.index["questions"][row["id"]]["evidence"]
        assert evidence
        for item in evidence:
            assert item["contains"].casefold() not in row["query"].casefold()


def test_scope_filters_select_the_labeled_documents(brinewick):
    metadata = {
        item.logical_key: item.metadata for item in brinewick.declaration.documents
    }
    saw_department = saw_currency = saw_customer = False
    for row in brinewick.questions["queries"]:
        metadata_filter = row["metadata_filter"]
        saw_department = saw_department or "department" in metadata_filter
        saw_currency = saw_currency or "currency" in metadata_filter
        saw_customer = saw_customer or "customer" in metadata_filter
        labeled = list(row.get("relevant_doc_ids", []))
        labeled.extend(pair[0] for pair in row.get("relevant_chunks", []))
        for key in labeled:
            assert _matches(metadata[key], metadata_filter)
        if set(metadata_filter) - {"org"}:
            assert any(
                not _matches(values, metadata_filter) for values in metadata.values()
            )
    assert saw_department and saw_currency and saw_customer


def test_absent_questions_name_facts_the_corpus_does_not_contain(brinewick):
    blob = "\n".join(payload.decode("utf-8") for payload in brinewick.files.values())
    absent_rows = [row for row in brinewick.questions["queries"] if row.get("expected_result")]
    assert {row["expected_result"] for row in absent_rows} == {
        "no_supporting_evidence",
        "refusal",
    }
    for row in absent_rows:
        terms = brinewick.index["questions"][row["id"]]["absent_terms"]
        assert terms
        for term in terms:
            assert term.casefold() not in blob.casefold()


def test_overlap_version_conflict_names_and_near_duplicate_are_in_the_files(brinewick):
    shared_leave = "Paid time away from the vessel is recorded on the Saltmere crew ledger."
    assert shared_leave in _text(brinewick, "hr-pto-policy")
    assert shared_leave in _text(brinewick, "hr-pto-policy-2022")
    assert shared_leave in _text(brinewick, "hr-parental-leave")
    assert "18 paid days off" in _text(brinewick, "hr-pto-policy")
    assert "15 paid days off" in _text(brinewick, "hr-pto-policy-2022")
    assert "18 paid days off" not in _text(brinewick, "hr-pto-policy-2022")

    assert "The dinner reimbursement limit is 75 USD per person" in _text(
        brinewick, "finance-expense-policy"
    )
    assert "The dinner reimbursement limit is 40 USD per person" in _text(
        brinewick, "finance-travel-policy"
    )

    escort = "A visitor without a Brinewick badge may remain unescorted for"
    assert escort in _text(brinewick, "security-access-control")
    assert escort in _text(brinewick, "security-badge-draft")
    assert "ten minutes" in _text(brinewick, "security-access-control")
    assert "fifteen minutes" in _text(brinewick, "security-badge-draft")
    assert "SEC-AC-221" not in _text(brinewick, "security-badge-draft")

    for key in ("product-harbor-pass", "product-harbor-pass-plus", "product-lantern-pass"):
        assert "Harbor Pass" in _text(brinewick, key)
    assert "HP-100" in _text(brinewick, "product-harbor-pass")
    assert "HPP-200" in _text(brinewick, "product-harbor-pass-plus")
    assert "LP-330" in _text(brinewick, "product-lantern-pass")

    assert "Keel and Co" in _text(brinewick, "customer-keel-and-co")
    assert "Keel and Co" in _text(brinewick, "customer-keel-cooperative")
    assert "04:00 to 06:00" in _text(brinewick, "customer-keel-and-co")
    assert "18:00 to 20:00" in _text(brinewick, "customer-keel-cooperative")


def test_long_document_and_chunk_boundary_use_the_declared_chunker(brinewick):
    runbook = brinewick.chunks["engineering-runbook"]
    assert len(runbook) >= 3
    passphrase = [
        index for index, chunk in enumerate(runbook) if "saltmere cutover window" in chunk
    ]
    assert passphrase
    assert all(index > 0 for index in passphrase)
    assert _row(brinewick, "q-runbook-phrase")["relevant_chunks"] == [
        ["engineering-runbook", index] for index in passphrase
    ]

    watch = brinewick.chunks["ops-watch-log"]
    code = [index for index, chunk in enumerate(watch) if "QK-BOUNDARY-441" in chunk]
    phrase = [index for index, chunk in enumerate(watch) if "north lantern steady" in chunk]
    assert code and phrase
    assert set(code).isdisjoint(phrase)
    assert min(phrase) == max(code) + 1
    labeled = _row(brinewick, "q-chunk-boundary")["relevant_chunks"]
    assert labeled == [["ops-watch-log", index] for index in sorted(set(code) | set(phrase))]
    citation = _row(brinewick, "q-chunk-boundary")["expected_citation"]
    assert citation["chunk_index"] == phrase[0]
    assert "north lantern steady" in watch[phrase[0]]
    assert "north lantern steady" not in watch[code[0]]


def test_release_and_stale_document_facts_answer_the_question(brinewick):
    release = _row(brinewick, "q-release")
    release_fact = release["expected_facts"][0]
    release_text = _text(brinewick, "engineering-release")
    assert release_fact == "Saltmere yard cutover"
    assert release_fact in release_text
    assert "gangway sensors" in release_text
    assert _completeness([ExpectedFact(release_fact)], "It marks the Saltmere yard cutover.") == 1
    assert _completeness([ExpectedFact(release_fact)], "It marks the gangway sensors.") == 0

    stale = _row(brinewick, "q-stale-pto-document")
    stale_fact = stale["expected_facts"][0]
    assert stale["query"].startswith("Which document")
    assert stale_fact == "Captain paid time off (2022)"
    assert stale_fact in _text(brinewick, "hr-pto-policy-2022")
    assert stale_fact not in _text(brinewick, "hr-pto-policy")
    assert "15 paid days off" not in stale_fact
    assert _completeness([ExpectedFact(stale_fact)], "Captain paid time off (2022).") == 1
    assert _completeness([ExpectedFact(stale_fact)], "15 paid days off.") == 0
    assert stale["must_not_claim"] == ["18 paid days off"]

    synthesis = _row(brinewick, "q-leave-synthesis")
    assert "18 paid days off" in synthesis["expected_facts"]


def test_manifest_resolves_logical_keys_and_searches_the_tenant(brinewick, tmp_path):
    documents = [
        {
            "logical_key": item.logical_key,
            "file_name": item.file_name,
            "document_id": f"run-{item.logical_key}",
            "metadata": item.metadata,
            "status": "completed",
        }
        for item in brinewick.declaration.documents
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "tenant_id": "eval-brinewick",
                "chunk_settings": {
                    "CHUNK_SIZE": 1000,
                    "CHUNK_OVERLAP": 200,
                    "CHUNKING_STRATEGY": "fixed",
                },
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_dataset(ROOT / "questions.json", manifest)
    by_query = {query.query: query for query in loaded.queries}
    current = by_query[_row(brinewick, "q-policy-number-pto")["query"]]
    assert current.relevant_chunks == [("run-hr-pto-policy", 0)]
    assert current.logical_relevant_chunks == [("hr-pto-policy", 0)]
    assert current.doc_ids[0] == "run-hr-pto-policy"
    assert current.logical_doc_ids[0] == "hr-pto-policy"

    synthesis = by_query[_row(brinewick, "q-leave-synthesis")["query"]]
    assert synthesis.relevant_chunks == [
        ("run-hr-parental-leave", 0),
        ("run-hr-pto-policy", 0),
    ]
    assert synthesis.logical_relevant_chunks == [
        ("hr-parental-leave", 0),
        ("hr-pto-policy", 0),
    ]
    assert synthesis.relevant_doc_ids == []

    stale = by_query[_row(brinewick, "q-stale-pto-document")["query"]]
    assert stale.relevant_chunks == [("run-hr-pto-policy-2022", 0)]
    assert stale.logical_relevant_chunks == [("hr-pto-policy-2022", 0)]
    assert stale.relevant_doc_ids == []

    absent = by_query[_row(brinewick, "q-absent-sabbatical")["query"]]
    assert absent.expected_result == "no_supporting_evidence"
    assert absent.relevant_chunks == []
    assert absent.doc_ids == [item["document_id"] for item in documents]
    assert absent.logical_doc_ids == [item["logical_key"] for item in documents]


async def test_checked_in_questions_fail_before_metrics_when_chunk_size_differs(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "chunk_settings": {
                    "CHUNK_SIZE": 500,
                    "CHUNK_OVERLAP": 200,
                    "CHUNKING_STRATEGY": "fixed",
                },
                "documents": [
                    {
                        "logical_key": "hr-pto-policy",
                        "document_id": "run-hr-pto-policy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with patch("services.eval_service.run_eval", new=AsyncMock()) as run_eval:
        with pytest.raises(EvalDatasetError, match="chunk_size"):
            await cmd_eval(
                str(ROOT / "questions.json"),
                "dev",
                [5],
                [],
                5,
                None,
                False,
                str(manifest),
            )
    run_eval.assert_not_called()


def test_checked_in_corpus_has_no_runtime_uuid():
    for path in [ROOT / "questions.json", ROOT / "corpus.json", ROOT / "index.json"]:
        assert UUID_RE.search(path.read_text(encoding="utf-8")) is None
    for path in CORPUS_DIR.iterdir():
        assert UUID_RE.search(path.read_text(encoding="utf-8")) is None
