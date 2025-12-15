from fastapi import APIRouter
from backend.services.embedding_service import get_embedding
from backend.services.answer_service import generate_answer
from backend.core.clients import supabase_client

router = APIRouter()

@router.post("/chat")
async def chat(question: str, document_id: str):
    embedding = await get_embedding(question)

    # vector search
    res = supabase_client.rpc("match_chunks", {
        "query_embedding": embedding,
        "match_count": 5,
        "filter_document_id": document_id
    }).execute()

    chunks = res.data
    context = "\n".join([c["chunk_text"] for c in chunks])

    answer = generate_answer(question, context)

    return {
        "question": question,
        "chunks": len(chunks),
        "answer": answer
    }
