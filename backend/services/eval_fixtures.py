"""Query fixture dataset schema + loader for the eval tool.

Ground truth for each query is either relevance labels
(``relevant_doc_ids`` and/or ``relevant_chunks`` as
``[document_id, chunk_index]`` pairs) or a declaration that the correct
result is no supporting evidence or a refusal. A row needs one of those.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

_NO_EVIDENCE_RESULTS = frozenset({"no_supporting_evidence", "refusal"})


class EvalDatasetError(ValueError):
    """The eval dataset cannot be loaded."""


@dataclass
class EvalQuery:
    query: str
    doc_ids: list[str] = field(default_factory=list)
    relevant_doc_ids: list[str] = field(default_factory=list)
    relevant_chunks: list[tuple[str, int]] = field(default_factory=list)
    metadata_filter: dict | None = None  # v1 chat filter; narrows doc_ids before retrieval
    simulate_session: bool = False
    session_history: list[dict] = field(default_factory=list)
    expected_result: str | None = None

    def relevant_keys(self) -> set[str | tuple[str, int]]:
        keys: set[str | tuple[str, int]] = set(self.relevant_doc_ids)
        keys.update(self.relevant_chunks)
        return keys


@dataclass
class EvalDataset:
    name: str
    queries: list[EvalQuery]
    source_path: Path | None = None


def _require_query(row: object, path: Path) -> str:
    if not isinstance(row, dict):
        raise EvalDatasetError(f"Query row in {path} must be a JSON object")
    query = row.get("query")
    if not isinstance(query, str) or not query:
        raise EvalDatasetError(f"Query row in {path} is missing a query string")
    return query


def _string_list(value: object, field_name: str, query: str, path: Path) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid {field_name}")
    return list(value)


def _chunk_list(value: object, query: str, path: Path) -> list[tuple[str, int]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid relevant_chunks")
    chunks: list[tuple[str, int]] = []
    for pair in value:
        if (
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0]
            or isinstance(pair[1], bool)
            or not isinstance(pair[1], int)
            or pair[1] < 0
        ):
            raise EvalDatasetError(f"Query {query!r} in {path} has invalid relevant_chunks")
        chunks.append((pair[0], pair[1]))
    return chunks


def _expected_result(row: dict, query: str, path: Path) -> str | None:
    if "expected_result" not in row or row["expected_result"] is None:
        return None
    value = row["expected_result"]
    if value not in _NO_EVIDENCE_RESULTS:
        raise EvalDatasetError(
            f"Query {query!r} in {path} has expected_result {value!r}; "
            'use "no_supporting_evidence" or "refusal"'
        )
    return value


def load_dataset(path: str | Path) -> EvalDataset:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("queries"), list):
        raise EvalDatasetError(f"Dataset {path} must be a JSON object with a queries list")

    queries: list[EvalQuery] = []
    for row in raw["queries"]:
        query = _require_query(row, path)
        relevant_doc_ids = _string_list(row.get("relevant_doc_ids"), "relevant_doc_ids", query, path)
        relevant_chunks = _chunk_list(row.get("relevant_chunks"), query, path)
        expected_result = _expected_result(row, query, path)
        has_relevance = bool(relevant_doc_ids or relevant_chunks)
        if expected_result and has_relevance:
            raise EvalDatasetError(
                f"Query {query!r} in {path} declares {expected_result} and also has relevance labels"
            )
        if not expected_result and not has_relevance:
            raise EvalDatasetError(
                f"Query {query!r} in {path} has neither relevance labels "
                "nor a no-evidence or refusal declaration"
            )
        doc_ids = _string_list(row.get("doc_ids"), "doc_ids", query, path)
        if not doc_ids:
            doc_ids = list(relevant_doc_ids or [pair[0] for pair in relevant_chunks])
        queries.append(
            EvalQuery(
                query=query,
                doc_ids=doc_ids,
                relevant_doc_ids=relevant_doc_ids,
                relevant_chunks=relevant_chunks,
                metadata_filter=row.get("metadata_filter"),
                simulate_session=bool(row.get("simulate_session", False)),
                session_history=list(row.get("session_history") or []),
                expected_result=expected_result,
            )
        )

    return EvalDataset(name=raw.get("name", path.stem), queries=queries, source_path=path)


def dataset_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
