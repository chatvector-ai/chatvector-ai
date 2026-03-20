import logging
from dataclasses import dataclass

from fastapi import UploadFile
from langchain_text_splitters import RecursiveCharacterTextSplitter

import db
from core.config import config
from services.embedding_service import get_embeddings
from services.extraction_service import extract_text_from_file
from services.text_cleaning_service import clean_text

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_TYPES = {"application/pdf", "text/plain"}


@dataclass
class _FileMetadata:
    """Minimal duck-type shim used by extract_text_from_file for background jobs."""
    content_type: str
    filename: str


class UploadPipelineError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        stage: str,
        message: str,
        document_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.stage = stage
        self.message = message
        self.document_id = document_id


class IngestionPipeline:
    def __init__(self, splitter_cls=None):
        self._splitter_cls = splitter_cls or RecursiveCharacterTextSplitter

    def validate_file(self, file: UploadFile, file_bytes: bytes) -> None:
        stage = "validation"

        if file.content_type not in ALLOWED_UPLOAD_TYPES:
            raise UploadPipelineError(
                status_code=400,
                code="invalid_file_type",
                stage=stage,
                message="Only PDF and TXT files are supported.",
            )

        if not file_bytes:
            raise UploadPipelineError(
                status_code=400,
                code="empty_file",
                stage=stage,
                message="Uploaded file is empty.",
            )

        if len(file_bytes) > config.MAX_UPLOAD_SIZE_BYTES:
            raise UploadPipelineError(
                status_code=413,
                code="file_too_large",
                stage=stage,
                message=(
                    f"File exceeds maximum upload size of {config.MAX_UPLOAD_SIZE_MB} MB."
                ),
            )

    async def _update_status(
        self,
        doc_id: str,
        status: str,
        failed_stage: str | None = None,
        error_message: str | None = None,
        chunks_total: int | None = None,
        chunks_processed: int | None = None,
    ) -> None:
        await db.update_document_status(
            doc_id=doc_id,
            status=status,
            failed_stage=failed_stage,
            error_message=error_message,
            chunks_total=chunks_total,
            chunks_processed=chunks_processed,
        )

    async def _handle_error(self, doc_id: str, stage: str, message: str) -> None:
        safe_message = message[:500]
        try:
            await self._update_status(
                doc_id=doc_id,
                status="failed",
                failed_stage=stage,
                error_message=safe_message,
            )
        except Exception as status_error:
            logger.error(f"Failed to mark document {doc_id} as failed: {status_error}")

        try:
            await db.delete_document_chunks(doc_id)
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup chunks for document {doc_id}: {cleanup_error}")

    async def process_document(self, file: UploadFile) -> dict:
        logger.info(f"Starting upload for file: {file.filename} ({file.content_type})")

        doc_id: str | None = None
        stage = "validation"

        try:
            file_bytes = await file.read()
            self.validate_file(file, file_bytes)

            stage = "uploaded"
            doc_id = await db.create_document(file.filename)
            await self._update_status(doc_id=doc_id, status="uploaded")

            stage = "extracting"
            await self._update_status(doc_id=doc_id, status="extracting")
            file_text = await extract_text_from_file(file, file_bytes)
            file_text = clean_text(file_text)

            if not file_text:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_text_extracted",
                    stage=stage,
                    message="No extractable text was found in the uploaded document.",
                )

            stage = "chunking"
            await self._update_status(doc_id=doc_id, status="chunking")
            splitter = self._splitter_cls(chunk_size=1000, chunk_overlap=200)
            chunks = splitter.split_text(file_text)

            if not chunks:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_chunks_generated",
                    stage=stage,
                    message="No chunks were generated from extracted text.",
                )

            stage = "embedding"
            await self._update_status(
                doc_id=doc_id,
                status="embedding",
                chunks_total=len(chunks),
                chunks_processed=0,
            )
            embeddings = await get_embeddings(chunks)

            if len(embeddings) != len(chunks):
                raise UploadPipelineError(
                    status_code=500,
                    code="embedding_mismatch",
                    stage=stage,
                    message="Embedding generation returned an unexpected number of vectors.",
                )

            stage = "storing"
            await self._update_status(doc_id=doc_id, status="storing")
            chunk_ids = await db.store_chunks_with_embeddings(
                doc_id,
                list(zip(chunks, embeddings)),
            )

            await self._update_status(
                doc_id=doc_id,
                status="completed",
                failed_stage="",
                error_message="",
                chunks_total=len(chunks),
                chunks_processed=len(chunk_ids),
            )

            logger.info(
                f"Successfully uploaded {len(chunk_ids)} chunks for document {doc_id}"
            )

            return {
                "message": "Uploaded",
                "document_id": doc_id,
                "chunks": len(chunk_ids),
                "status": "completed",
                "status_endpoint": f"/documents/{doc_id}/status",
            }

        except UploadPipelineError as e:
            if doc_id and not e.document_id:
                e.document_id = doc_id

            if doc_id:
                await self._handle_error(doc_id=doc_id, stage=e.stage, message=e.message)

            logger.warning(
                f"Upload validation/pipeline failed at stage={e.stage}: {e.message}"
            )
            raise

        except Exception as e:
            if doc_id:
                await self._handle_error(doc_id=doc_id, stage=stage, message=str(e))

            logger.error(f"Upload failed at stage={stage} for file {file.filename}: {e}")
            raise UploadPipelineError(
                status_code=500,
                code="upload_failed",
                stage=stage,
                message="Upload failed. Please try again.",
                document_id=doc_id,
            )

    async def process_document_background(
        self,
        doc_id: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
    ) -> None:
        """
        Run the extraction→chunking→embedding→storing pipeline stages for a
        document that was already created and queued by the upload endpoint.

        Called exclusively by background workers; raises on unrecoverable error
        so the worker can apply retry / DLQ logic.
        """
        file_meta = _FileMetadata(content_type=content_type, filename=file_name)
        stage = "extracting"

        try:
            await self._update_status(doc_id=doc_id, status="extracting")
            file_text = await extract_text_from_file(file_meta, file_bytes)  # type: ignore[arg-type]
            file_text = clean_text(file_text)

            if not file_text:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_text_extracted",
                    stage=stage,
                    message="No extractable text was found in the uploaded document.",
                    document_id=doc_id,
                )

            stage = "chunking"
            await self._update_status(doc_id=doc_id, status="chunking")
            splitter = self._splitter_cls(chunk_size=1000, chunk_overlap=200)
            chunks = splitter.split_text(file_text)

            if not chunks:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_chunks_generated",
                    stage=stage,
                    message="No chunks were generated from extracted text.",
                    document_id=doc_id,
                )

            stage = "embedding"
            await self._update_status(
                doc_id=doc_id,
                status="embedding",
                chunks_total=len(chunks),
                chunks_processed=0,
            )
            embeddings = await get_embeddings(chunks)

            if len(embeddings) != len(chunks):
                raise UploadPipelineError(
                    status_code=500,
                    code="embedding_mismatch",
                    stage=stage,
                    message="Embedding generation returned an unexpected number of vectors.",
                    document_id=doc_id,
                )

            stage = "storing"
            await self._update_status(doc_id=doc_id, status="storing")
            chunk_ids = await db.store_chunks_with_embeddings(
                doc_id,
                list(zip(chunks, embeddings)),
            )

            await self._update_status(
                doc_id=doc_id,
                status="completed",
                failed_stage="",
                error_message="",
                chunks_total=len(chunks),
                chunks_processed=len(chunk_ids),
            )

            logger.info(
                f"Background processing complete: {len(chunk_ids)} chunks "
                f"stored for document {doc_id}"
            )

        except UploadPipelineError as e:
            await self._handle_error(doc_id=doc_id, stage=e.stage, message=e.message)
            logger.warning(
                f"Background pipeline failed at stage={e.stage} "
                f"for document {doc_id}: {e.message}"
            )
            raise

        except Exception as e:
            await self._handle_error(doc_id=doc_id, stage=stage, message=str(e))
            logger.error(
                f"Background pipeline unexpected error at stage={stage} "
                f"for document {doc_id}: {e}"
            )
            raise