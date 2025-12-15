from fastapi import APIRouter
from backend.core.clients import supabase_client

router = APIRouter()

@router.get("/test-db")
def test_db():
    """Test database connection"""
    try:
        response = supabase_client.table('documents').select("*").limit(1).execute()
        return {"status": "Database connected!", "data": response.data}
    except Exception as e:
        return {"error": str(e)}