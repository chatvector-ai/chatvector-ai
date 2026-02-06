from fastapi import APIRouter, UploadFile, File
from services.extraction_service import extract_text_from_file
from services.db_service import create_document
from services.ingestion_service import ingest_chunks
from services.embedding_service import get_embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    logger.info(f"Starting upload for file: {file.filename} ({file.content_type})")
    # Step 1: Extract text from the file
    file_text = await extract_text_from_file(file)
    # Step 2: Split text into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text(file_text)
    # Step 3: Generate Embeddings
    embeddings = await get_embeddings(chunks)
    # Step 4: Create document
    doc_id = await create_document(file.filename)
    # Step 5: Insert chunks
    inserted_chunk_ids = await ingest_chunks(chunks, embeddings, doc_id)
    logger.info(f"Successfully uploaded {len(inserted_chunk_ids)} chunks for document {doc_id}")
    return {
        "message": "Uploaded",
        "document_id": doc_id,
        "chunks": len(inserted_chunk_ids),
    }


    
