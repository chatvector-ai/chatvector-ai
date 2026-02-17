from fastapi import APIRouter, UploadFile, File, HTTPException
from services.extraction_service import extract_text_from_file
from services.ingestion_service import ingest_document_atomic
from services.embedding_service import get_embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    logger.info(f"Starting upload for file: {file.filename} ({file.content_type})")

    try:
        # Step 1: Extract text
        file_text = await extract_text_from_file(file)

        # Step 2: Split into chunks
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_text(file_text)

        # Step 3: Generate embeddings
        embeddings = await get_embeddings(chunks)

        # Step 4: Delegate to ingestion service (handles validation + atomic persistence)
        doc_id, inserted_chunk_ids = await ingest_document_atomic(
            file_name=file.filename,
            chunks=chunks,
            embeddings=embeddings,
        )

        logger.info(f"Successfully uploaded {len(inserted_chunk_ids)} chunks for document {doc_id}")

        return {
            "message": "Uploaded",
            "document_id": doc_id,
            "chunks": len(inserted_chunk_ids),
        }
    
    except ValueError as e:
        logger.warning(f"Upload validation failed for file {file.filename}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed for file {file.filename}: {e}")
        raise HTTPException(status_code=500, detail="Upload failed. Please try again.")


    
