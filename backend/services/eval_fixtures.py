"""Query fixture dataset schema + loader for the eval tool.

Ground truth for each query is expressed as ``relevant_doc_ids`` and/or
``relevant_chunks`` (``[document_id, chunk_index]`` pairs) — at least one
of the two must be present per query.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalQuery:
    query: str
    doc_ids: list[str] = field(default_factory=list)
    relevant_doc_ids: list[str] = field(default_factory=list)
    relevant_chunks: list[tuple[str, int]] = field(default_factory=list)
    metadata_filter: dict | None = None  # v1 chat filter; narrows doc_ids before retrieval
    simulate_session: bool = False
    session_history: list[dict] = field(default_factory=list)

    def relevant_keys(self) -> set[str | tuple[str, int]]:
        keys: set[str | tuple[str, int]] = set(self.relevant_doc_ids)
        keys.update(self.relevant_chunks)
        return keys


@dataclass
class EvalDataset:
    name: str
    queries: list[EvalQuery]
    source_path: Path | None = None


def load_dataset(path: str | Path) -> EvalDataset:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    queries: list[EvalQuery] = []
    for row in raw["queries"]:
        relevant_doc_ids = list(row.get("relevant_doc_ids", []))
        relevant_chunks: list[tuple[str, int]] = [
            (pair[0], pair[1]) for pair in row.get("relevant_chunks", [])
        ]
        if not relevant_doc_ids and not relevant_chunks:
            raise ValueError(
                f"Query {row.get('query')!r} in {path} has neither "
                "relevant_doc_ids nor relevant_chunks"
            )
        doc_ids = list(row.get("doc_ids") or relevant_doc_ids or [pair[0] for pair in relevant_chunks])
        queries.append(
            EvalQuery(
                query=row["query"],
                doc_ids=doc_ids,
                relevant_doc_ids=relevant_doc_ids,
                relevant_chunks=relevant_chunks,
                metadata_filter=row.get("metadata_filter"),
                simulate_session=bool(row.get("simulate_session", False)),
                session_history=list(row.get("session_history") or []),
            )
        )

    return EvalDataset(name=raw.get("name", path.stem), queries=queries, source_path=path)


def dataset_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
