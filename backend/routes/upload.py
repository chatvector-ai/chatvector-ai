import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from langchain_text_splitters import RecursiveCharacterTextSplitter

import db
from core.config import config
from services.embedding_service import get_embeddings
from services.extraction_service import extract_text_from_file

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_UPLOAD_TYPES = {"application/pdf", "text/plain"}


class UploadPipelineError(Exception):
    def __init__(self, status_code: int, code: str, stage: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.stage = stage
        self.message = message


def _http_error(
    status_code: int,
    code: str,
    stage: str,
    message: str,
    document_id: str | None = None,
) -> HTTPException:
    detail = {
        "code": code,
        "stage": stage,
        "message": message,
    }
    if document_id:
        detail["document_id"] = document_id
    return HTTPException(status_code=status_code, detail=detail)


async def _mark_failed_upload(doc_id: str, stage: str, message: str) -> None:
    """Best-effort status update + chunk cleanup for failed uploads."""
    safe_message = message[:500]
    try:
        await db.update_document_status(
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


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    logger.info(f"Starting upload for file: {file.filename} ({file.content_type})")

    doc_id: str | None = None
    stage = "validation"

    try:
        if file.content_type not in ALLOWED_UPLOAD_TYPES:
            raise UploadPipelineError(
                status_code=400,
                code="invalid_file_type",
                stage=stage,
                message="Only PDF and TXT files are supported.",
            )

        file_bytes = await file.read()

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

        # Create document only after pre-validation passes
        stage = "uploaded"
        doc_id = await db.create_document(file.filename)
        await db.update_document_status(doc_id=doc_id, status="uploaded")

        stage = "extracting"
        await db.update_document_status(doc_id=doc_id, status="extracting")
        file_text = await extract_text_from_file(file, file_bytes)

        if not file_text.strip():
            raise UploadPipelineError(
                status_code=422,
                code="no_text_extracted",
                stage=stage,
                message="No extractable text was found in the uploaded document.",
            )

        stage = "chunking"
        await db.update_document_status(doc_id=doc_id, status="chunking")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_text(file_text)

        if not chunks:
            raise UploadPipelineError(
                status_code=422,
                code="no_chunks_generated",
                stage=stage,
                message="No chunks were generated from extracted text.",
            )

        stage = "embedding"
        await db.update_document_status(
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
        await db.update_document_status(doc_id=doc_id, status="storing")
        chunk_ids = await db.store_chunks_with_embeddings(doc_id, list(zip(chunks, embeddings)))

        await db.update_document_status(
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
        if doc_id:
            await _mark_failed_upload(doc_id=doc_id, stage=e.stage, message=e.message)
        logger.warning(f"Upload validation/pipeline failed at stage={e.stage}: {e.message}")
        raise _http_error(
            status_code=e.status_code,
            code=e.code,
            stage=e.stage,
            message=e.message,
            document_id=doc_id,
        )

    except Exception as e:
        if doc_id:
            await _mark_failed_upload(doc_id=doc_id, stage=stage, message=str(e))
        logger.error(f"Upload failed at stage={stage} for file {file.filename}: {e}")
        raise _http_error(
            status_code=500,
            code="upload_failed",
            stage=stage,
            message="Upload failed. Please try again.",
            document_id=doc_id,
        )
