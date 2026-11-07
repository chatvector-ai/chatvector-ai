"""Isolated evaluation corpus loader.

The load runs production extraction, chunking, embedding, and storage.
It does not call the public upload route or the atomic test ingest helper.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

import db
from cli import main
from core.config import config
from services.eval_corpus import EvalCorpusError, load_eval_corpus
from services.extraction_service import extract_text_with_metadata as real_extract
from services.ingestion_pipeline import IngestionPipeline
from services.queue_base import reset_process_embedding_rate_limiter
from services.tenant_registry import clear_tenant_registry

BACKEND = Path(__file__).resolve().parents[1]
_EMBEDDING = [0.01, 0.02, 0.03]


class _MemoryDb:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict] = {}
        self.order: list[tuple[str, str]] = []
        self.chunks: dict[str, list] = {}
        self.deleted: list[tuple[str, str]] = []
        self.store_calls: list[tuple[str, str, list]] = []

    def seed(self, filename: str, tenant_id: str, metadata: dict | None = None) -> str:
        doc_id = str(uuid.uuid4())
        self.docs[(tenant_id, doc_id)] = {
            "id": doc_id,
            "file_name": filename,
            "tenant_id": tenant_id,
            "status": "completed",
            "metadata": dict(metadata or {}),
            "error": None,
        }
        self.order.append((tenant_id, doc_id))
        return doc_id

    async def create_document(self, filename: str, tenant_id: str, metadata: dict | None = None) -> str:
        return self.seed(filename, tenant_id, metadata)

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        tenant_id: str,
        *,
        error: dict | None = None,
        chunks: dict | None = None,
        job_metadata_patch: dict | None = None,
    ) -> None:
        document = self.docs[(tenant_id, doc_id)]
        document["status"] = status
        if error is not None:
            document["error"] = error

    async def store_chunks_with_embeddings(self, doc_id: str, chunk_records: list, tenant_id: str) -> list[str]:
        if (tenant_id, doc_id) not in self.docs:
            raise ValueError(f"missing document {doc_id}")
        self.chunks[doc_id] = list(chunk_records)
        self.store_calls.append((tenant_id, doc_id, list(chunk_records)))
        return [str(uuid.uuid4()) for _ in chunk_records]

    async def delete_document(self, doc_id: str, tenant_id: str) -> None:
        self.deleted.append((tenant_id, doc_id))
        self.docs.pop((tenant_id, doc_id), None)
        self.chunks.pop(doc_id, None)
        self.order = [item for item in self.order if item != (tenant_id, doc_id)]

    async def delete_document_chunks(self, doc_id: str, tenant_id: str) -> None:
        self.chunks.pop(doc_id, None)

    async def list_tenant_documents(self, tenant_id: str) -> list[str]:
        return [doc_id for tenant, doc_id in self.order if tenant == tenant_id]

    async def get_document_status(self, doc_id: str, tenant_id: str) -> dict | None:
        document = self.docs.get((tenant_id, doc_id))
        if document is None:
            return None
        return {
            "status": document["status"],
            "metadata": document["metadata"],
            "file_name": document["file_name"],
            "error": document["error"],
        }

    async def filter_document_ids_by_metadata(
        self,
        tenant_id: str,
        doc_ids: list[str],
        metadata_filter: dict,
    ) -> list[str]:
        matched: list[str] = []
        for doc_id in doc_ids:
            document = self.docs.get((tenant_id, doc_id))
            if document is None:
                continue
            metadata = document["metadata"]
            if all(metadata.get(key) == value for key, value in metadata_filter.items()):
                matched.append(doc_id)
        return matched


class _CorpusHarness:
    def __init__(self, memory: _MemoryDb) -> None:
        self.memory = memory
        self.extract_calls: list[tuple[str, str, bytes | None]] = []
        self.chunk_calls: list[tuple[str, str]] = []
        self.embed_batches: list[list[str]] = []
        self.upload_calls: list[object] = []


def _process_settings() -> dict:
    return {
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
        "chunking_strategy": config.CHUNKING_STRATEGY,
    }


def _write_corpus(tmp_path: Path, documents: list[tuple], settings: dict | None = None):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    rows = []
    for logical_key, file_name, payload, metadata in documents:
        target = corpus_dir / file_name
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        else:
            target.write_text(payload, encoding="utf-8")
        row = {"logical_key": logical_key, "file_name": file_name}
        if metadata is not None:
            row["metadata"] = metadata
        rows.append(row)
    declaration = tmp_path / "corpus.json"
    chosen = settings or _process_settings()
    declaration.write_text(
        json.dumps(
            {
                "chunk_size": chosen["chunk_size"],
                "chunk_overlap": chosen["chunk_overlap"],
                "chunking_strategy": chosen["chunking_strategy"],
                "documents": rows,
            }
        ),
        encoding="utf-8",
    )
    return corpus_dir, declaration


def _sample_documents() -> list[tuple]:
    return [
        (
            "retention",
            "retention.txt",
            "The retention policy covers contracts for seven years.\n",
            {"department": "legal", "year": 2024},
        ),
        (
            "guide",
            "guide.txt",
            "The employee guide explains holiday leave.\n",
            {"department": "hr", "reviewed": False},
        ),
    ]


@pytest.fixture
def corpus_db(monkeypatch) -> _CorpusHarness:
    memory = _MemoryDb()
    harness = _CorpusHarness(memory)
    monkeypatch.setattr(config, "WEBHOOK_ENABLED", False)
    monkeypatch.setattr(config, "QUEUE_EMBEDDING_RPS", 1000.0)
    reset_process_embedding_rate_limiter()
    clear_tenant_registry()

    for name in (
        "create_document",
        "update_document_status",
        "store_chunks_with_embeddings",
        "delete_document",
        "delete_document_chunks",
        "list_tenant_documents",
        "get_document_status",
        "filter_document_ids_by_metadata",
    ):
        monkeypatch.setattr(f"db.{name}", getattr(memory, name))

    async def forbid_atomic(*_args, **_kwargs):
        raise AssertionError("atomic ingest helper must not run the corpus load")

    async def forbid_upload(*args, **kwargs):
        harness.upload_calls.append((args, kwargs))
        raise AssertionError("public upload route must not run the corpus load")

    async def fake_embeddings(texts, tenant_id=None, use_cache=None):
        harness.embed_batches.append(list(texts))
        return [_EMBEDDING[:] for _ in texts]

    async def spy_extract(file, contents=None):
        harness.extract_calls.append((file.filename, file.content_type, contents))
        return await real_extract(file, contents)

    original_chunk = IngestionPipeline._chunk_document_text

    def spy_chunk(self, text, *, file_name, content_type):
        harness.chunk_calls.append((file_name, text))
        return original_chunk(self, text, file_name=file_name, content_type=content_type)

    monkeypatch.setattr("db.create_document_with_chunks_atomic", forbid_atomic)
    monkeypatch.setattr("services.ingestion_service.ingest_document_atomic", forbid_atomic)
    monkeypatch.setattr("routes.upload.upload", forbid_upload)
    monkeypatch.setattr("services.ingestion_pipeline.get_embeddings", fake_embeddings)
    monkeypatch.setattr("services.ingestion_pipeline.extract_text_with_metadata", spy_extract)
    monkeypatch.setattr(IngestionPipeline, "_chunk_document_text", spy_chunk)

    yield harness

    clear_tenant_registry()
    reset_process_embedding_rate_limiter()


def _mismatch_case(field: str) -> tuple[dict, str]:
    settings = _process_settings()
    override = dict(settings)
    if field == "chunk_size":
        override["chunk_size"] = settings["chunk_size"] + 17
        fragment = (
            f"CHUNK_SIZE corpus {override['chunk_size']}, process {settings['chunk_size']}"
        )
    elif field == "chunk_overlap":
        override["chunk_overlap"] = settings["chunk_overlap"] + 17
        fragment = (
            "CHUNK_OVERLAP corpus "
            f"{override['chunk_overlap']}, process {settings['chunk_overlap']}"
        )
    else:
        override["chunking_strategy"] = (
            "fixed" if settings["chunking_strategy"] == "semantic" else "semantic"
        )
        fragment = (
            "CHUNKING_STRATEGY corpus "
            f"{override['chunking_strategy']}, process {settings['chunking_strategy']}"
        )
    return override, fragment


@pytest.mark.asyncio
async def test_two_file_corpus_maps_logical_keys_through_production_stages(tmp_path, corpus_db):
    tenant = "eval-corpus"
    corpus_dir, declaration = _write_corpus(tmp_path, _sample_documents())
    names_before = sorted(path.name for path in corpus_dir.iterdir())
    manifest_path = tmp_path / "manifest.json"
    other_id = corpus_db.memory.seed(
        "contract.docx",
        "other-tenant",
        {"department": "legal"},
    )

    loaded = await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)

    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk == loaded
    assert loaded["tenant_id"] == tenant
    assert loaded["chunk_settings"] == {
        "CHUNK_SIZE": config.CHUNK_SIZE,
        "CHUNK_OVERLAP": config.CHUNK_OVERLAP,
        "CHUNKING_STRATEGY": config.CHUNKING_STRATEGY,
    }
    by_key = {row["logical_key"]: row for row in loaded["documents"]}
    assert [row["logical_key"] for row in loaded["documents"]] == ["retention", "guide"]
    assert by_key["retention"]["file_name"] == "retention.txt"
    assert by_key["retention"]["metadata"] == {"department": "legal", "year": 2024}
    assert by_key["guide"]["metadata"] == {"department": "hr", "reviewed": False}
    for row in loaded["documents"]:
        assert row["status"] == "completed"
        uuid.UUID(row["document_id"])
        assert row["document_id"] != row["logical_key"]

    listed = await db.list_tenant_documents(tenant)
    assert listed == [row["document_id"] for row in loaded["documents"]]
    for doc_id in listed:
        payload = await db.get_document_status(doc_id, tenant)
        assert payload["status"] == "completed"

    legal = await db.filter_document_ids_by_metadata(
        tenant, listed, {"department": "legal"}
    )
    assert legal == [by_key["retention"]["document_id"]]
    unreviewed = await db.filter_document_ids_by_metadata(
        tenant, listed, {"reviewed": False}
    )
    assert unreviewed == [by_key["guide"]["document_id"]]
    assert await db.filter_document_ids_by_metadata(
        tenant, [other_id], {"department": "legal"}
    ) == []

    assert sorted(path.name for path in corpus_dir.iterdir()) == names_before
    assert corpus_db.upload_calls == []
    assert len(corpus_db.extract_calls) == 2
    extracted = {name: contents for name, content_type, contents in corpus_db.extract_calls}
    assert extracted["retention.txt"].startswith(b"The retention policy")
    assert extracted["guide.txt"].startswith(b"The employee guide")
    assert {content_type for _name, content_type, _contents in corpus_db.extract_calls} == {
        "text/plain"
    }
    chunked = {name: text for name, text in corpus_db.chunk_calls}
    assert "retention policy" in chunked["retention.txt"]
    assert "holiday leave" in chunked["guide.txt"]
    stored_texts = [
        record.chunk_text
        for _tenant, _doc_id, records in corpus_db.memory.store_calls
        for record in records
    ]
    assert stored_texts
    assert [text for batch in corpus_db.embed_batches for text in batch] == stored_texts
    assert all(
        record.embedding == _EMBEDDING
        for _tenant, _doc_id, records in corpus_db.memory.store_calls
        for record in records
    )
    assert "retention" in " ".join(stored_texts)
    assert ("other-tenant", other_id) in corpus_db.memory.docs
    assert all(deleted_tenant == tenant for deleted_tenant, _doc_id in corpus_db.memory.deleted)


@pytest.mark.asyncio
async def test_second_load_replaces_only_the_named_tenant(tmp_path, corpus_db):
    tenant = "eval-corpus"
    corpus_dir, declaration = _write_corpus(tmp_path, _sample_documents())
    manifest_path = tmp_path / "manifest.json"
    other_id = corpus_db.memory.seed("contract.docx", "other-tenant", {"department": "legal"})

    first = await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)
    first_ids = [row["document_id"] for row in first["documents"]]

    second = await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)
    second_ids = [row["document_id"] for row in second["documents"]]

    assert [row["logical_key"] for row in second["documents"]] == ["retention", "guide"]
    assert set(second_ids).isdisjoint(first_ids)
    listed = await db.list_tenant_documents(tenant)
    assert listed == second_ids
    for doc_id in first_ids:
        assert (tenant, doc_id) not in corpus_db.memory.docs
    assert ("other-tenant", other_id) in corpus_db.memory.docs
    assert await db.list_tenant_documents("other-tenant") == [other_id]
    assert all(deleted_tenant == tenant for deleted_tenant, _doc_id in corpus_db.memory.deleted)
    assert set(first_ids).issubset(
        {doc_id for deleted_tenant, doc_id in corpus_db.memory.deleted if deleted_tenant == tenant}
    )
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [row["document_id"] for row in on_disk["documents"]] == second_ids
    assert all(row["status"] == "completed" for row in on_disk["documents"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["chunk_size", "chunk_overlap", "chunking_strategy"])
async def test_chunk_setting_mismatch_names_both_sides_and_writes_no_manifest(
    field, tmp_path, corpus_db
):
    tenant = "eval-corpus"
    override, fragment = _mismatch_case(field)
    corpus_dir, declaration = _write_corpus(tmp_path, _sample_documents(), override)
    manifest_path = tmp_path / "manifest.json"
    sentinel = b'{"documents":[{"status":"completed"}]}\n'
    manifest_path.write_bytes(sentinel)
    seeded = corpus_db.memory.seed("leftover.txt", tenant)

    with pytest.raises(EvalCorpusError) as excinfo:
        await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)

    assert fragment in str(excinfo.value)
    assert manifest_path.read_bytes() == sentinel
    assert corpus_db.memory.deleted == []
    assert corpus_db.memory.store_calls == []
    assert (tenant, seeded) in corpus_db.memory.docs
    assert corpus_db.extract_calls == []


def test_command_exits_nonzero_on_chunk_mismatch(tmp_path, corpus_db, monkeypatch, capsys):
    override, fragment = _mismatch_case("chunk_size")
    corpus_dir, declaration = _write_corpus(tmp_path, _sample_documents(), override)
    manifest_path = tmp_path / "manifest.json"
    sentinel = b'{"status":"completed"}\n'
    manifest_path.write_bytes(sentinel)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.cli",
            "load-eval-corpus",
            "--corpus-dir",
            str(corpus_dir),
            "--declaration",
            str(declaration),
            "--tenant-id",
            "eval-corpus",
            "--manifest",
            str(manifest_path),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert fragment in capsys.readouterr().err
    assert manifest_path.read_bytes() == sentinel


@pytest.mark.asyncio
async def test_extractor_rejection_does_not_publish_a_completed_manifest(tmp_path, corpus_db):
    tenant = "eval-corpus"
    documents = [
        (
            "retention",
            "retention.txt",
            "The retention policy covers contracts for seven years.\n",
            {"department": "legal"},
        ),
        ("broken", "broken.html", b"<p>broken\x00</p>", None),
    ]
    corpus_dir, declaration = _write_corpus(tmp_path, documents)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": [{"logical_key": "broken", "status": "completed"}]}),
        encoding="utf-8",
    )
    seeded = corpus_db.memory.seed("leftover.txt", tenant)

    with pytest.raises(EvalCorpusError, match="broken.html") as excinfo:
        await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)

    assert "completed" not in str(excinfo.value)
    assert not manifest_path.exists()
    assert not manifest_path.with_name(manifest_path.name + ".tmp").exists()
    broken = [
        document
        for document in corpus_db.memory.docs.values()
        if document["file_name"] == "broken.html"
    ]
    assert len(broken) == 1
    assert broken[0]["status"] == "failed"
    assert any(name == "broken.html" for name, _ctype, _contents in corpus_db.extract_calls)
    assert (tenant, seeded) not in corpus_db.memory.docs
    assert corpus_db.upload_calls == []


def test_command_exits_nonzero_when_extractor_rejects_a_file(
    tmp_path, corpus_db, monkeypatch, capsys
):
    documents = [
        ("broken", "broken.html", b"<p>broken\x00</p>", None),
    ]
    corpus_dir, declaration = _write_corpus(tmp_path, documents)
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.cli",
            "load-eval-corpus",
            "--corpus-dir",
            str(corpus_dir),
            "--declaration",
            str(declaration),
            "--tenant-id",
            "eval-corpus",
            "--manifest",
            str(manifest_path),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "broken.html" in captured.err
    assert "Loaded" not in captured.out
    assert not manifest_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        ("missing", "missing"),
        ("empty", "empty"),
        ("duplicate", "Duplicate logical_key"),
        ("nested", "metadata"),
        ("traversal", "single file"),
    ],
)
async def test_invalid_corpus_does_not_change_the_tenant_or_manifest(
    mutate, match, tmp_path, corpus_db
):
    tenant = "eval-corpus"
    settings = _process_settings()
    if mutate == "duplicate":
        documents = [
            ("retention", "retention.txt", "The retention policy covers contracts.\n", None),
            ("retention", "guide.txt", "The employee guide explains holiday leave.\n", None),
        ]
    elif mutate == "nested":
        documents = [
            ("retention", "retention.txt", "The retention policy covers contracts.\n", {"tags": ["a"]}),
        ]
    elif mutate == "traversal":
        documents = [
            ("retention", "retention.txt", "The retention policy covers contracts.\n", None),
        ]
    else:
        documents = [
            ("retention", "retention.txt", "The retention policy covers contracts.\n", None),
        ]
    corpus_dir, declaration = _write_corpus(tmp_path, documents, settings)
    if mutate == "missing":
        (corpus_dir / "retention.txt").unlink()
    elif mutate == "empty":
        (corpus_dir / "retention.txt").write_bytes(b"")
    elif mutate == "traversal":
        declaration.write_text(
            json.dumps(
                {
                    **settings,
                    "documents": [
                        {"logical_key": "secret", "file_name": "../secret.txt"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "secret.txt").write_text("do not read", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    sentinel = b'{"documents":[{"status":"completed"}]}\n'
    manifest_path.write_bytes(sentinel)
    seeded = corpus_db.memory.seed("leftover.txt", tenant)

    with pytest.raises(EvalCorpusError, match=match):
        await load_eval_corpus(corpus_dir, declaration, tenant, manifest_path)

    assert manifest_path.read_bytes() == sentinel
    assert corpus_db.memory.deleted == []
    assert corpus_db.memory.store_calls == []
    assert (tenant, seeded) in corpus_db.memory.docs


def test_upload_rate_limit_default_is_unchanged():
    config_source = (BACKEND / "core" / "config.py").read_text(encoding="utf-8")
    upload_source = (BACKEND / "routes" / "upload.py").read_text(encoding="utf-8")
    assert 'os.getenv("RATE_LIMIT_UPLOAD", "20/hour")' in config_source
    assert "@limiter.limit(config.RATE_LIMIT_UPLOAD)" in upload_source


def test_loader_does_not_add_a_public_upload_route():
    source = (BACKEND / "services" / "eval_corpus.py").read_text(encoding="utf-8")
    assert "APIRouter" not in source
    assert "routes.upload" not in source
    assert "ingest_document_atomic" not in source
    assert "create_document_with_chunks_atomic" not in source


def test_eval_subcommand_help_still_lists_dataset_and_tenant(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["backend.cli", "eval", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "--dataset" in output
    assert "--tenant-id" in output
