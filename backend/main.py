from fastapi import FastAPI, UploadFile, File
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
load_dotenv()  # Loads from .env file
import supabase
from supabase import create_client, Client  # <-- Make sure this is imported
import google.generativeai as genai
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


def get_embedding(text: str) -> list:
    """Get embedding vector using Google's embedding model"""
    try:
        result = genai.embed_content(
            model="models/embedding-001",
            content=text
            # No task_type needed - works for both documents and queries
        )
        return result['embedding']
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return [0.0] * 768

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

@app.post("/chat")
async def chat_with_document(question: str, document_id: str):
    print(f"💬 Chat question: {question}")
    print(f"📄 Querying document: {document_id}")
    
    # 1. Embed the question
    question_embedding = get_embedding(question)
    print(f"🧠 Question embedded with {len(question_embedding)} dimensions")
    
    # 2. Find similar chunks using vector search
    print("🔍 Searching for relevant chunks...")
    response = supabase.rpc(
        'match_chunks',
        {
            'query_embedding': question_embedding,
            'match_count': 5,
            'filter_document_id': document_id  # Changed from 'document_id'
        }
    ).execute()
    
    relevant_chunks = response.data
    print(f"📚 Found {len(relevant_chunks)} relevant chunks")
    
    # 3. Build context from relevant chunks
    context = "\n\n".join([chunk['chunk_text'] for chunk in relevant_chunks])
    
    # 4. Generate AI response
    print("🤖 Generating AI response...")
    answer = generate_answer(question, context)
    if len(answer) > 0:
        print(f" Answer received: {answer}")
    else:
        print(f" Error: couldn't get answer")



    return {
        "question": question,
        "document_id": document_id,
        "relevant_chunks_count": len(relevant_chunks),
        "answer": answer
    }

genai.configure(api_key=os.getenv("GEN_AI_KEY"))

def generate_answer(question: str, context: str) -> str:
    """Generate answer using Google Gemini with RAG optimization"""
    
    # More specific prompt for better RAG performance
    prompt = f"""You are a helpful AI assistant. Answer the question based ONLY on the provided context.

CONTEXT:
{context}

QUESTION: {question}

INSTRUCTIONS:
- Answer using only the information from the context above
- If the context doesn't contain the answer, say "I don't have enough information to answer this question"
- Keep your response concise and relevant to the question
- Do not make up information or use external knowledge

ANSWER:"""
    
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        
        # Handle empty responses gracefully
        if response.text:
            return response.text
        else:
            return "No response generated from the AI model."
            
    except Exception as e:
        # Log the error and return a user-friendly message
        print(f"Gemini API error: {e}")
        return f"Error generating response: {str(e)}"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)