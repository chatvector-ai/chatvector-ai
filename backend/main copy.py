from fastapi import FastAPI, UploadFile, File
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

from backend.routes.chat import chat_with_document
load_dotenv()  # Loads from .env file
import supabase
from supabase import create_client, Client  # <-- Make sure this is imported
import os
from services.embedding import get_embedding
from services.llm_service import generate_answer
import google.generativeai as genai
from routes.upload import router as upload_router, upload_file
from routes.chat import router as chat_router, chat_with_document
from core.database import supabase  # Import supabase client from database module

app = FastAPI()



@app.get("/")
def read_root():

load_dotenv()  # Loads from .env file

# supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)
app.include_router(supabase)

get_embedding()  # Ensure the embedding service is imported and available

app.include_router(upload_router) # Include the upload router 
app.include_router(chat_router) # Include the chat router

genai.configure(api_key=os.getenv("GEN_AI_KEY"))

generate_answer()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)