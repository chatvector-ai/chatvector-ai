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
import time
import asyncio
import requests  
import json     

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "ChatVector AI Backend is Live!"}

load_dotenv()  # Loads from .env file

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


async def get_embedding(text: str) -> list:
    """Get embedding vector using Google's embedding model"""
    for attempt in range(3): # Retry up to 3 times on failure
        try: 
            result = genai.embed_content(
                model="models/embedding-001",  # Example embedding model
                content=text 
                # No task_type needed - works for both documents and queries
            )
            return result['embedding']
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg and attempt < 2:
                wait_time = (attempt + 1) * 10
                print(f"Rate limit exceeded, retrying... (attempt {attempt + 1})")
              
                await asyncio.sleep(wait_time)  # Exponential backoff
            else:
                print(f"Error getting embedding: {e}")
                return [0.0] * 768 # Return a zero vector on failure
        
    print("Failed to get embedding after retries")
    return [0.0] * 768 # Return a zero vector on failure

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    print(f" Received file: {file.filename}")
    
    # 1. Read file contents
    contents = await file.read()
    
    # 2. Extract text with pypdf or plain text
    if file.content_type == "application/pdf":
        file_text = "" # Initialize empty string to hold text andf avoid reference before assignment
        reader = PdfReader(io.BytesIO(contents))
        for page in reader.pages: 
            file_text += page.extract_text() + "\n"
            print(f" Extracted {len(file_text)} characters of text")
    elif file.content_type == "text/plain":
        # Try UTF-8 first, if that fails, try Turkish Windows encoding
        try:
            file_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            file_text = contents.decode("cp1254")  # Common for Turkish Windows files
            print(f" Extracted {len(file_text)} characters of text")
    else:
        return {"error": "Unsupported file type. Please upload a PDF or TXT file."}
            
    print(f"Extracted {len(file_text)} characters from TXT")   
    # 3. Chunk text with LangChain
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, # chunk size can be change as needed based on use case and model limits
        chunk_overlap=200 # overlap to maintain context between chunks 
    )
    chunks = text_splitter.split_text(file_text)
    
    print(f" Split into {len(chunks)} chunks")
    
    # 4. store document in db
    print("💾 Storing document in database...")
    document_data = {
        "file_name": file.filename
    }
    document_response = supabase.table("documents").insert(document_data).execute()
    document_id = document_response.data[0]["id"]
    print(f"   Document stored with ID: {document_id}")
    
    # 5. gen embeddings and store chunks
    print(" Generating embeddings and storing chunks...")
    stored_chunks = 0
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(2)  # To avoid rate limits
        embedding = await get_embedding(chunk)
        if not any(embedding): # Check for zero vector indicating an error
            print(f"  Skipping chunk {i+1} due to embedding error")
            continue
        
        chunk_data = {
            "document_id": document_id,
            "chunk_text": chunk,
            "embedding": embedding
        }
        supabase.table("document_chunks").insert(chunk_data).execute()
        stored_chunks += 1

        if embedding :
            print(f" stored chunk {i+1}/{len(chunks)}")
        else:
            print(f" failed to store chunk {i+1}/{len(chunks)}")
        
        # print preview of first 2 chunks
        if i < 2:
            print(f" preview chunk {i+1}: {len(embedding)} dimensions - {embedding[:3]}...")
    
    print(f"successfully stored {stored_chunks} chunks in database")
    
    return {
        "filename": file.filename,
        "text_length": len(file_text),
        "chunk_count": len(chunks),
        "document_id": document_id,
        "stored_chunks": stored_chunks,
        "message": "File successfully processed and stored in database!"
    }

@app.post("/chat")
async def chat_with_document(question: str, document_id: str):
    print(f"chat question: {question}")
    print(f"querying document: {document_id}")
    
    # 1. embed the question
    question_embedding = await get_embedding(question)
    print(f"🧠 Question embedded with {len(question_embedding)} dimensions")
    
    # 2. locate similar chunks using vector search
    print("searching for relevant chunks...")
    response = supabase.rpc(
        'match_chunks',
        {
            'query_embedding': question_embedding,
            'match_count': 5,
            'filter_document_id': document_id  # Changed from 'document_id'
        }
    ).execute()
    
    relevant_chunks = response.data
    print(f"found {len(relevant_chunks)} relevant chunks")
    
    # 3. biuld context from relevant chunks
    context = "\n\n".join([chunk['chunk_text'] for chunk in relevant_chunks])
    
    # 4. gen ai response
    print("generating AI response...")
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
