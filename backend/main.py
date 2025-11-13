from fastapi import FastAPI, UploadFile, File
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
load_dotenv()  # Loads from .env file
import supabase
from supabase import create_client, Client  # <-- Make sure this is imported
import os
import io
import requests  # <-- ADD THIS
import json      # <-- ADD THIS

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "DocTalk AI Backend is Live!"}

load_dotenv()  # Loads from .env file

# Ollama configuration - ADD THIS
OLLAMA_URL = "http://localhost:11434"

# supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

@app.get("/test-db")
def test_db():
    try:
        response = supabase.table('documents').select("*").limit(1).execute()
        return {"status": "Database connected!", "data": response.data}
    except Exception as e:
        return {"error": str(e)}


# embedding func
def get_embedding(text: str) -> list:
    """Get embedding vector from Ollama"""
    payload = {
        "model": "nomic-embed-text", 
        "prompt": text
    }
    response = requests.post(f"{OLLAMA_URL}/api/embeddings", json=payload)
    response.raise_for_status()
    return response.json()["embedding"]

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    print(f"📥 Received file: {file.filename}")
    
    # 1. Read PDF
    contents = await file.read()
    
    # 2. Extract text with pypdf
    pdf_text = ""
    reader = PdfReader(io.BytesIO(contents))
    for page in reader.pages:
        pdf_text += page.extract_text() + "\n"
    
    print(f"📄 Extracted {len(pdf_text)} characters of text")
    
    # 3. Chunk text with LangChain
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_text(pdf_text)
    
    print(f"✂️ Split into {len(chunks)} chunks")
    
    # 4. Store document in Supabase
    print("💾 Storing document in database...")
    document_data = {
        "file_name": file.filename
    }
    document_response = supabase.table("documents").insert(document_data).execute()
    document_id = document_response.data[0]["id"]
    print(f"   Document stored with ID: {document_id}")
    
    # 5. Generate embeddings and store chunks
    print("🧠 Generating embeddings and storing chunks...")
    stored_chunks = 0
    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        
        chunk_data = {
            "document_id": document_id,
            "chunk_text": chunk,
            "embedding": embedding
        }
        supabase.table("document_chunks").insert(chunk_data).execute()
        stored_chunks += 1
        
        # Print progress for first few chunks
        if i < 2:
            print(f"   Chunk {i+1}: {len(embedding)} dimensions - {embedding[:3]}...")
    
    print(f"💾 Successfully stored {stored_chunks} chunks in database")
    
    return {
        "filename": file.filename,
        "text_length": len(pdf_text),
        "chunk_count": len(chunks),
        "document_id": document_id,
        "stored_chunks": stored_chunks,
        "message": "PDF successfully processed and stored in database!"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)