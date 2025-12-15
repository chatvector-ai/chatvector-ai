from fastapi import APIRouter, UploadFile, File
from backend.services.embedding_service import get_embedding
from backend.core.clients import supabase_client
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
import io
import asyncio

router = APIRouter()

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    contents = await file.read()

    # Extract text
    if file.content_type == "application/pdf":
        text = ""
        reader = PdfReader(io.BytesIO(contents))
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

    elif file.content_type == "text/plain":
        text = contents.decode("utf-8", errors="ignore")

    else:
        return {"error": "Unsupported file type"}

    # Split text
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text(text)

    # Create document
    doc = supabase_client.table("documents").insert({"file_name": file.filename}).execute()
    doc_id = doc.data[0]["id"]

    # Store chunks
    for i, chunk in enumerate(chunks):
        await asyncio.sleep(1)
        embedding = await get_embedding(chunk)
        supabase_client.table("document_chunks").insert({
            "document_id": doc_id,
            "chunk_text": chunk,
            "embedding": embedding
        }).execute()

    return {"message": "Uploaded", "document_id": doc_id, "chunks": len(chunks)}
