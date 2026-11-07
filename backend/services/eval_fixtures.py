"""Query fixture dataset schema + loader for the eval tool.

Ground truth for each query is either relevance labels
(``relevant_doc_ids`` and/or ``relevant_chunks`` as
``[document_id, chunk_index]`` pairs) or a declaration that the correct
result is no supporting evidence or a refusal. A row needs one of those.

Answer labels are optional on that same row. ``expected_facts``,
``expected_refusal``, ``expected_citation``, and ``must_not_claim`` are
the only paraphrase and citation targets the answer arm scores. They do
not replace the relevance or no-evidence declaration.

Document ids in a question file may be logical keys. Pass the corpus
manifest to resolve those keys to the document ids for one run. The
resolved row keeps the logical key. A citation document is resolved the
same way when it is a logical key, and the label keeps both identities.
Manifest chunk settings must match the settings declared on the question
file; a mismatch fails before scoring.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

_NO_EVIDENCE_RESULTS = frozenset({"no_supporting_evidence", "refusal"})
_QUESTION_CHUNK_FIELDS = ("chunking_strategy", "chunk_size", "chunk_overlap")
_MANIFEST_CHUNK_FIELDS = (
    ("chunking_strategy", "CHUNKING_STRATEGY"),
    ("chunk_size", "CHUNK_SIZE"),
    ("chunk_overlap", "CHUNK_OVERLAP"),
)


class EvalDatasetError(ValueError):
    """The eval dataset cannot be loaded or scored."""


@dataclass(frozen=True)
class ExpectedFact:
    """One labeled fact. Alternates are the only allowed phrasings."""

    text: str
    alternates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedRefusal:
    """Refusal phrases and strings the answer must not contain."""

    phrases: tuple[str, ...]
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedCitation:
    """A packed-context target. ``document`` may be a logical key or a runtime id."""

    document: str
    chunk_index: int | None = None
    page: int | None = None
    resolved_document_id: str | None = None


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
    scope: str | None = None
    expected_facts: list[ExpectedFact] = field(default_factory=list)
    expected_refusal: ExpectedRefusal | None = None
    expected_citation: ExpectedCitation | None = None
    must_not_claim: list[str] = field(default_factory=list)
    # Populated only when a manifest resolves logical keys to document ids.
    logical_doc_ids: list[str] = field(default_factory=list)
    logical_relevant_doc_ids: list[str] = field(default_factory=list)
    logical_relevant_chunks: list[tuple[str, int]] = field(default_factory=list)

    def relevant_keys(self) -> set[str | tuple[str, int]]:
        keys: set[str | tuple[str, int]] = set(self.relevant_doc_ids)
        keys.update(self.relevant_chunks)
        return keys

    def has_answer_labels(self) -> bool:
        return bool(
            self.expected_facts
            or self.expected_refusal is not None
            or self.expected_citation is not None
            or self.must_not_claim
        )


@dataclass
class EvalDataset:
    name: str
    queries: list[EvalQuery]
    source_path: Path | None = None
    chunk_settings: dict | None = None


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


def _label_text(value: object, field_name: str, query: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid {field_name}")
    return value


def _label_text_list(value: object, field_name: str, query: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid {field_name}")
    return [_label_text(item, field_name, query, path) for item in value]


def _optional_label_index(value: object, field_name: str, query: str, path: Path) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid {field_name}")
    return value


def _expected_facts(row: dict, query: str, path: Path) -> list[ExpectedFact]:
    if "expected_facts" not in row or row["expected_facts"] is None:
        return []
    value = row["expected_facts"]
    if not isinstance(value, list) or not value:
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_facts")
    facts: list[ExpectedFact] = []
    for item in value:
        if isinstance(item, str):
            facts.append(ExpectedFact(text=_label_text(item, "expected_facts", query, path)))
            continue
        if not isinstance(item, dict):
            raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_facts")
        unknown = set(item) - {"text", "alternates"}
        if unknown or "text" not in item:
            names = ", ".join(sorted(unknown)) or "text"
            raise EvalDatasetError(
                f"Query {query!r} in {path} has invalid expected_facts fields: {names}"
            )
        alternates = item.get("alternates", [])
        if not isinstance(alternates, list) or any(
            not isinstance(alternate, str) or not alternate.strip() for alternate in alternates
        ):
            raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_facts")
        facts.append(
            ExpectedFact(
                text=_label_text(item["text"], "expected_facts", query, path),
                alternates=tuple(alternates),
            )
        )
    return facts


def _expected_refusal(row: dict, query: str, path: Path) -> ExpectedRefusal | None:
    if "expected_refusal" not in row or row["expected_refusal"] is None:
        return None
    value = row["expected_refusal"]
    if not isinstance(value, dict):
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_refusal")
    unknown = set(value) - {"phrases", "forbidden"}
    if unknown or "phrases" not in value:
        names = ", ".join(sorted(unknown)) or "phrases"
        raise EvalDatasetError(
            f"Query {query!r} in {path} has invalid expected_refusal fields: {names}"
        )
    forbidden = value.get("forbidden", [])
    if not isinstance(forbidden, list) or any(
        not isinstance(item, str) or not item.strip() for item in forbidden
    ):
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_refusal")
    return ExpectedRefusal(
        phrases=tuple(_label_text_list(value["phrases"], "expected_refusal", query, path)),
        forbidden=tuple(forbidden),
    )


def _expected_citation(row: dict, query: str, path: Path) -> ExpectedCitation | None:
    if "expected_citation" not in row or row["expected_citation"] is None:
        return None
    value = row["expected_citation"]
    if not isinstance(value, dict):
        raise EvalDatasetError(f"Query {query!r} in {path} has invalid expected_citation")
    unknown = set(value) - {"document", "chunk_index", "page"}
    if unknown or "document" not in value:
        names = ", ".join(sorted(unknown)) or "document"
        raise EvalDatasetError(
            f"Query {query!r} in {path} has invalid expected_citation fields: {names}"
        )
    return ExpectedCitation(
        document=_label_text(value["document"], "expected_citation", query, path),
        chunk_index=_optional_label_index(value.get("chunk_index"), "expected_citation", query, path),
        page=_optional_label_index(value.get("page"), "expected_citation", query, path),
    )


def _must_not_claim(row: dict, query: str, path: Path) -> list[str]:
    if "must_not_claim" not in row or row["must_not_claim"] is None:
        return []
    return _label_text_list(row["must_not_claim"], "must_not_claim", query, path)


def _scope(row: dict, query: str, path: Path) -> str | None:
    if "scope" not in row or row["scope"] is None:
        return None
    value = row["scope"]
    if not isinstance(value, str) or value.strip().lower() != "tenant":
        raise EvalDatasetError(
            f"Query {query!r} in {path} has scope {value!r}; the supported scope is \"tenant\""
        )
    return "tenant"


def _require_int(value: object, name: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvalDatasetError(f"Dataset {path} {name} must be an integer")
    return value


def _question_chunk_settings(raw: dict, path: Path) -> dict | None:
    if "chunk_settings" not in raw or raw["chunk_settings"] is None:
        return None
    settings = raw["chunk_settings"]
    if not isinstance(settings, dict):
        raise EvalDatasetError(f"Dataset {path} chunk_settings must be a JSON object")
    unknown = set(settings) - set(_QUESTION_CHUNK_FIELDS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise EvalDatasetError(f"Dataset {path} has unknown chunk_settings fields: {names}")
    missing = set(_QUESTION_CHUNK_FIELDS) - set(settings)
    if missing:
        names = ", ".join(sorted(missing))
        raise EvalDatasetError(f"Dataset {path} chunk_settings is missing {names}")
    strategy = settings["chunking_strategy"]
    if not isinstance(strategy, str) or not strategy.strip():
        raise EvalDatasetError(f"Dataset {path} chunking_strategy must be a non-empty string")
    return {
        "chunking_strategy": strategy.strip(),
        "chunk_size": _require_int(settings["chunk_size"], "chunk_size", path),
        "chunk_overlap": _require_int(settings["chunk_overlap"], "chunk_overlap", path),
    }


def _read_manifest(path: Path) -> dict:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvalDatasetError(f"Could not read corpus manifest {path}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EvalDatasetError(f"Could not read corpus manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvalDatasetError(f"Corpus manifest {path} must be a JSON object")
    return raw


def _assert_chunk_settings_match(
    question: dict,
    manifest: dict,
    question_path: Path,
    manifest_path: Path,
) -> None:
    recorded = manifest.get("chunk_settings")
    if not isinstance(recorded, dict):
        raise EvalDatasetError(f"Corpus manifest {manifest_path} is missing chunk_settings")

    mismatches: list[str] = []
    for question_key, manifest_key in _MANIFEST_CHUNK_FIELDS:
        left = question[question_key]
        right = recorded.get(manifest_key)
        if question_key == "chunking_strategy":
            if not isinstance(right, str) or left.strip().lower() != right.strip().lower():
                mismatches.append(f"chunking_strategy question {left}, manifest {right}")
        elif left != right:
            mismatches.append(f"{question_key} question {left}, manifest {right}")
    if mismatches:
        detail = "; ".join(mismatches)
        raise EvalDatasetError(
            "Eval chunk settings do not match the corpus manifest "
            f"({question_path} vs {manifest_path}): {detail}"
        )


def _manifest_documents(manifest: dict, path: Path) -> list[dict]:
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise EvalDatasetError(f"Corpus manifest {path} must list documents")
    seen: set[str] = set()
    rows: list[dict] = []
    for index, row in enumerate(documents):
        if not isinstance(row, dict):
            raise EvalDatasetError(f"Manifest document {index} in {path} must be a JSON object")
        logical_key = row.get("logical_key")
        document_id = row.get("document_id")
        if not isinstance(logical_key, str) or not logical_key:
            raise EvalDatasetError(f"Manifest document {index} in {path} is missing logical_key")
        if not isinstance(document_id, str) or not document_id:
            raise EvalDatasetError(f"Manifest document {index} in {path} is missing document_id")
        if logical_key in seen:
            raise EvalDatasetError(f"Corpus manifest {path} repeats logical_key {logical_key!r}")
        seen.add(logical_key)
        rows.append(row)
    return rows


def _resolve_key(key: str, mapping: dict[str, str], query: str, path: Path) -> str:
    try:
        return mapping[key]
    except KeyError:
        raise EvalDatasetError(
            f"Query {query!r} in {path} uses logical key {key!r} that is not in the corpus manifest"
        ) from None


def _apply_manifest(dataset: EvalDataset, documents: list[dict], path: Path) -> None:
    mapping = {row["logical_key"]: row["document_id"] for row in documents}
    tenant_keys = [row["logical_key"] for row in documents]
    tenant_ids = [row["document_id"] for row in documents]
    for query in dataset.queries:
        if query.scope == "tenant":
            query.logical_doc_ids = list(tenant_keys)
            query.doc_ids = list(tenant_ids)
        else:
            query.logical_doc_ids = list(query.doc_ids)
            query.doc_ids = [_resolve_key(key, mapping, query.query, path) for key in query.doc_ids]
        query.logical_relevant_doc_ids = list(query.relevant_doc_ids)
        query.relevant_doc_ids = [
            _resolve_key(key, mapping, query.query, path) for key in query.relevant_doc_ids
        ]
        query.logical_relevant_chunks = list(query.relevant_chunks)
        query.relevant_chunks = [
            (_resolve_key(key, mapping, query.query, path), index)
            for key, index in query.relevant_chunks
        ]
        citation = query.expected_citation
        if citation is not None and citation.document in mapping:
            query.expected_citation = replace(
                citation,
                resolved_document_id=mapping[citation.document],
            )


def load_dataset(path: str | Path, manifest_path: str | Path | None = None) -> EvalDataset:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("queries"), list):
        raise EvalDatasetError(f"Dataset {path} must be a JSON object with a queries list")

    chunk_settings = _question_chunk_settings(raw, path)
    manifest: dict | None = None
    manifest_file: Path | None = None
    if manifest_path is not None:
        manifest_file = Path(manifest_path)
        manifest = _read_manifest(manifest_file)
        if chunk_settings is None:
            raise EvalDatasetError(
                f"Dataset {path} does not declare chunk_settings, "
                f"so it cannot be scored against {manifest_file}"
            )
        _assert_chunk_settings_match(chunk_settings, manifest, path, manifest_file)

    queries: list[EvalQuery] = []
    for row in raw["queries"]:
        query = _require_query(row, path)
        relevant_doc_ids = _string_list(row.get("relevant_doc_ids"), "relevant_doc_ids", query, path)
        relevant_chunks = _chunk_list(row.get("relevant_chunks"), query, path)
        expected_result = _expected_result(row, query, path)
        scope = _scope(row, query, path)
        expected_facts = _expected_facts(row, query, path)
        expected_refusal = _expected_refusal(row, query, path)
        expected_citation = _expected_citation(row, query, path)
        must_not_claim = _must_not_claim(row, query, path)
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
        if scope == "tenant" and row.get("doc_ids"):
            raise EvalDatasetError(
                f"Query {query!r} in {path} sets scope to tenant and also lists doc_ids"
            )
        doc_ids: list[str] = []
        if scope != "tenant":
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
                scope=scope,
                expected_facts=expected_facts,
                expected_refusal=expected_refusal,
                expected_citation=expected_citation,
                must_not_claim=must_not_claim,
            )
        )

    dataset = EvalDataset(
        name=raw.get("name", path.stem),
        queries=queries,
        source_path=path,
        chunk_settings=chunk_settings,
    )
    if manifest is not None and manifest_file is not None:
        _apply_manifest(dataset, _manifest_documents(manifest, manifest_file), path)
    return dataset


def dataset_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
