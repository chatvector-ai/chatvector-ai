"""Load a fixed evaluation corpus into one tenant.

The declaration names each file with a stable logical key. Runtime document
ids are assigned per run. On success the manifest maps each logical key to
that run's document id and records the chunk settings actually used. Later
evaluation artifacts that identify a document copy both identities from the
manifest. The runtime id alone is not the stable label.

Ingestion uses the production extract, chunk, embed, and store stages
in-process. Metadata is stored with ``create_document``, the same argument
the upload route uses, because ``process_document`` does not accept
metadata and would create a second row. The public upload route is not
called.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import db
from core.config import config
from db.tenant_scope import require_tenant_id
from services.document_metadata import parse_document_metadata
from services.docx_extraction import DOCX_CONTENT_TYPE, is_docx_filename
from services.extraction_service import is_html_filename, is_markdown_filename
from services.ingestion_pipeline import (
    IngestionPipeline,
    UploadPipelineError,
    _sanitize_filename,
)
from services.tenant_registry import invalidate_tenant_cache, register_tenant_document

logger = logging.getLogger(__name__)

_DECLARATION_FIELDS = frozenset(
    {"chunk_size", "chunk_overlap", "chunking_strategy", "documents"}
)
_DOCUMENT_FIELDS = frozenset({"logical_key", "file_name", "metadata"})


class EvalCorpusError(Exception):
    """The corpus was not loaded. A success manifest was not written."""


@dataclass(frozen=True)
class _CorpusFile:
    logical_key: str
    file_name: str
    metadata: dict


@dataclass(frozen=True)
class _CorpusDeclaration:
    chunk_size: int
    chunk_overlap: int
    chunking_strategy: str
    documents: tuple[_CorpusFile, ...]


@dataclass(frozen=True)
class _PreparedFile:
    logical_key: str
    file_name: str
    metadata: dict
    content_type: str
    file_bytes: bytes


class _UploadMeta:
    """Filename and content type for ``IngestionPipeline.validate_file``."""

    def __init__(self, filename: str, content_type: str) -> None:
        self.filename = filename
        self.content_type = content_type


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvalCorpusError(f"{name} must be an integer")
    return value


def _require_logical_key(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvalCorpusError("logical_key must be a non-empty string")
    if any(char.isspace() or char == "\x00" or char in "/\\" for char in value):
        raise EvalCorpusError(f"logical_key {value!r} is not a stable document key")
    return value


def _require_file_name(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvalCorpusError("file_name must be a non-empty string")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise EvalCorpusError(
            f"file_name {value!r} must name a single file inside the corpus directory"
        )
    if _sanitize_filename(value) != value:
        raise EvalCorpusError(f"file_name {value!r} is not a stable corpus file name")
    return value


def _validated_metadata(value: object, logical_key: str) -> dict:
    if not isinstance(value, dict):
        raise EvalCorpusError(f"metadata for {logical_key!r} must be a JSON object")
    try:
        return parse_document_metadata(json.dumps(value))
    except UploadPipelineError as exc:
        raise EvalCorpusError(
            f"metadata for {logical_key!r} is not valid document metadata: {exc.message}"
        ) from exc


def _load_declaration(path: Path) -> _CorpusDeclaration:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvalCorpusError(f"Could not read corpus declaration {path}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EvalCorpusError(f"Could not read corpus declaration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvalCorpusError("Corpus declaration must be a JSON object")

    unknown = set(raw) - _DECLARATION_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise EvalCorpusError(f"Unknown corpus declaration fields: {names}")
    missing = _DECLARATION_FIELDS - set(raw)
    if missing:
        names = ", ".join(sorted(missing))
        raise EvalCorpusError(f"Corpus declaration is missing {names}")

    documents = raw["documents"]
    if not isinstance(documents, list) or not documents:
        raise EvalCorpusError("Corpus declaration must list at least one document")

    files: list[_CorpusFile] = []
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    for index, row in enumerate(documents):
        if not isinstance(row, dict):
            raise EvalCorpusError(f"Document entry {index} must be a JSON object")
        extra = set(row) - _DOCUMENT_FIELDS
        if extra:
            names = ", ".join(sorted(extra))
            raise EvalCorpusError(f"Unknown fields on document entry {index}: {names}")
        if "logical_key" not in row or "file_name" not in row:
            raise EvalCorpusError(
                f"Document entry {index} needs logical_key and file_name"
            )
        logical_key = _require_logical_key(row["logical_key"])
        file_name = _require_file_name(row["file_name"])
        if logical_key in seen_keys:
            raise EvalCorpusError(f"Duplicate logical_key {logical_key!r}")
        if file_name in seen_names:
            raise EvalCorpusError(f"Duplicate file_name {file_name!r}")
        seen_keys.add(logical_key)
        seen_names.add(file_name)
        metadata = _validated_metadata(row.get("metadata", {}), logical_key)
        files.append(
            _CorpusFile(
                logical_key=logical_key,
                file_name=file_name,
                metadata=metadata,
            )
        )

    return _CorpusDeclaration(
        chunk_size=_require_int(raw["chunk_size"], "chunk_size"),
        chunk_overlap=_require_int(raw["chunk_overlap"], "chunk_overlap"),
        chunking_strategy=_require_strategy(raw["chunking_strategy"]),
        documents=tuple(files),
    )


def _require_strategy(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalCorpusError("chunking_strategy must be a non-empty string")
    return value.strip()


def _chunk_mismatch(declaration: _CorpusDeclaration) -> str | None:
    """Return an error naming both sides when the corpus does not match the process."""
    mismatches: list[str] = []
    if declaration.chunk_size != config.CHUNK_SIZE:
        mismatches.append(
            f"CHUNK_SIZE corpus {declaration.chunk_size}, process {config.CHUNK_SIZE}"
        )
    if declaration.chunk_overlap != config.CHUNK_OVERLAP:
        mismatches.append(
            "CHUNK_OVERLAP corpus "
            f"{declaration.chunk_overlap}, process {config.CHUNK_OVERLAP}"
        )
    declared = declaration.chunking_strategy.strip().lower()
    process = config.CHUNKING_STRATEGY.strip().lower()
    if declared != process:
        mismatches.append(
            "CHUNKING_STRATEGY corpus "
            f"{declaration.chunking_strategy}, process {config.CHUNKING_STRATEGY}"
        )
    if not mismatches:
        return None
    return "Corpus chunk settings do not match this process: " + "; ".join(mismatches)


def _content_type_for(file_name: str) -> str:
    if file_name.lower().endswith(".txt"):
        return "text/plain"
    if is_markdown_filename(file_name):
        return "text/markdown"
    if is_html_filename(file_name):
        return "text/html"
    if file_name.lower().endswith(".pdf"):
        return "application/pdf"
    if is_docx_filename(file_name):
        return DOCX_CONTENT_TYPE
    raise EvalCorpusError(
        f"Unsupported corpus file {file_name!r}. "
        "Use PDF, TXT, Markdown, HTML, or DOCX."
    )


def _resolve_corpus_file(corpus_dir: Path, file_name: str) -> Path:
    root = corpus_dir.resolve()
    if not root.is_dir():
        raise EvalCorpusError(f"Corpus directory {corpus_dir} is not a directory")
    candidate = (root / file_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise EvalCorpusError(f"Corpus file {file_name!r} is missing from {root}")
    return candidate


def _prepare_files(
    corpus_dir: Path,
    declaration: _CorpusDeclaration,
    pipeline: IngestionPipeline,
) -> list[_PreparedFile]:
    prepared: list[_PreparedFile] = []
    seen_paths: set[Path] = set()
    for item in declaration.documents:
        path = _resolve_corpus_file(corpus_dir, item.file_name)
        if path in seen_paths:
            raise EvalCorpusError(f"Duplicate corpus path for {item.file_name!r}")
        seen_paths.add(path)
        try:
            file_bytes = path.read_bytes()
        except OSError as exc:
            raise EvalCorpusError(f"Could not read corpus file {item.file_name!r}: {exc}") from exc
        content_type = _content_type_for(item.file_name)
        try:
            pipeline.validate_file(_UploadMeta(item.file_name, content_type), file_bytes)
        except UploadPipelineError as exc:
            raise EvalCorpusError(
                f"Corpus file {item.file_name!r} was rejected: {exc.message}"
            ) from exc
        prepared.append(
            _PreparedFile(
                logical_key=item.logical_key,
                file_name=item.file_name,
                metadata=item.metadata,
                content_type=content_type,
                file_bytes=file_bytes,
            )
        )
    return prepared


def _discard_existing_manifest(path: Path) -> None:
    if path.is_dir():
        raise EvalCorpusError(f"Manifest path {path} is a directory")
    if path.is_symlink() or path.exists():
        path.unlink()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def _clear_tenant_documents(tenant_id: str) -> None:
    for doc_id in await db.list_tenant_documents(tenant_id):
        await db.delete_document(doc_id, tenant_id=tenant_id)
    invalidate_tenant_cache(tenant_id)


async def _ingest_file(
    pipeline: IngestionPipeline,
    tenant_id: str,
    item: _PreparedFile,
) -> dict:
    doc_id = await db.create_document(
        item.file_name,
        tenant_id=tenant_id,
        metadata=item.metadata,
    )
    register_tenant_document(tenant_id, doc_id)
    try:
        await pipeline.process_document_background(
            doc_id=doc_id,
            file_name=item.file_name,
            content_type=item.content_type,
            file_bytes=item.file_bytes,
            tenant_id=tenant_id,
        )
    except EvalCorpusError:
        raise
    except Exception as exc:
        detail = getattr(exc, "message", None) or str(exc)
        logger.error("Eval corpus ingest failed for %s: %s", item.file_name, detail)
        raise EvalCorpusError(
            f"Failed to ingest {item.file_name} (logical key {item.logical_key}): {detail}"
        ) from exc

    status_payload = await db.get_document_status(doc_id, tenant_id=tenant_id)
    status = None if status_payload is None else status_payload.get("status")
    if status != "completed":
        raise EvalCorpusError(
            f"Failed to ingest {item.file_name} (logical key {item.logical_key}): "
            f"status is {status!r}, not 'completed'"
        )
    return {
        "logical_key": item.logical_key,
        "file_name": item.file_name,
        "document_id": doc_id,
        "metadata": item.metadata,
        "status": status,
    }


async def load_eval_corpus(
    corpus_dir: str | Path,
    declaration_path: str | Path,
    tenant_id: str,
    manifest_path: str | Path,
) -> dict:
    """Ingest ``corpus_dir`` into ``tenant_id`` and write a success manifest.

    Chunk settings are compared before any tenant document is removed. A
    failed file exits with ``EvalCorpusError`` and does not leave a manifest
    that marks that file completed.
    """
    try:
        tenant_id = require_tenant_id(tenant_id, method="load_eval_corpus")
    except ValueError as exc:
        raise EvalCorpusError(str(exc)) from exc

    corpus_dir = Path(corpus_dir)
    declaration_path = Path(declaration_path)
    manifest_path = Path(manifest_path)
    declaration = _load_declaration(declaration_path)
    mismatch = _chunk_mismatch(declaration)
    if mismatch:
        raise EvalCorpusError(mismatch)

    pipeline = IngestionPipeline()
    prepared = _prepare_files(corpus_dir, declaration, pipeline)

    _discard_existing_manifest(manifest_path)
    await _clear_tenant_documents(tenant_id)

    entries: list[dict] = []
    for item in prepared:
        entries.append(await _ingest_file(pipeline, tenant_id, item))

    listed = await db.list_tenant_documents(tenant_id)
    loaded_ids = [entry["document_id"] for entry in entries]
    if len(listed) != len(loaded_ids) or set(listed) != set(loaded_ids):
        raise EvalCorpusError(
            "Tenant document list does not match the corpus just loaded; "
            "no manifest was written"
        )

    manifest = {
        "tenant_id": tenant_id,
        "chunk_settings": {
            "CHUNK_SIZE": config.CHUNK_SIZE,
            "CHUNK_OVERLAP": config.CHUNK_OVERLAP,
            "CHUNKING_STRATEGY": config.CHUNKING_STRATEGY,
        },
        "documents": entries,
    }
    try:
        _write_manifest(manifest_path, manifest)
    except OSError as exc:
        raise EvalCorpusError(f"Could not write manifest {manifest_path}: {exc}") from exc
    return manifest
