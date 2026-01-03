from fastapi import APIRouter, UploadFile, File
from backend.services.embedding_service import get_embedding
from backend.services.extraction_service import extract_text_from_file
from backend.services.db_service import create_document, insert_chunk

from backend.core.clients import supabase_client
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
import io
import asyncio
from backend.core.logging_config import setup_logging
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

    # Step 3: Create document
    doc_id = await create_document(file.filename)

    # Step 4: Insert chunks
    for i, chunk in enumerate(chunks):
        embedding = await get_embedding(chunk)
        await insert_chunk(doc_id, chunk, embedding)
        logger.debug(
            f"Stored chunk {i + 1}/{len(chunks)} for document ID {doc_id}"
        )

    return {
        "message": "Uploaded",
        "document_id": doc_id,
        "chunks": len(chunks),
    }
    
