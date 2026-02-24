from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse

router = APIRouter()

def generate_mock_data():
    return {
        "status": "degraded",
        "components": {
            "api": "online",
            "database": "connected",
            "embeddings": "operational",
            "llm": "rate_limited"
        },
        "metrics": {
            "document_queue": 2,
            "memory_usage": 70,
            "documents_indexed": 127,
            "total_queries": 1543
        },
        "uptime": "3d 14h 22m",
        "version": "v0.1.0"
    }


def build_ascii_dashboard(data: dict) -> str:
    metrics = data["metrics"]

    queue_bar = "█" * 2 + "░" * (10 - 2)
    memory_bar = "█" * 7 + "░" * (10 - 7)

    return f"""
╔════════════════════════════════════════════════════╗
║              CHATVECTOR-AI SYSTEM STATUS           ║
╠════════════════════════════════════════════════════╣
║  🟢 API Server: ONLINE                              ║
║  🟢 Database: Connected                             ║
║  🟡 Embeddings: Operational                         ║
║  🔴 LLM Service: Rate Limited                       ║
║                                                     ║
║  📊 Document Queue: [{queue_bar}] {metrics['document_queue']}/5 pending       ║
║  💾 Memory Usage:   [{memory_bar}] {metrics['memory_usage']}%                ║
║  📁 Documents Indexed: {metrics['documents_indexed']}                          ║
║  💬 Total Queries:   {metrics['total_queries']}                          ║
║                                                     ║
║  ⏱ Uptime: {data['uptime']}                              ║
║  🏷 Version: {data['version']}                                  ║
╚════════════════════════════════════════════════════╝
"""


@router.get("/status")
async def system_status(request: Request):
    data = generate_mock_data()

    user_agent = request.headers.get("user-agent", "").lower()

    # Simple browser detection
    if "mozilla" in user_agent or "chrome" in user_agent:
        ascii_dashboard = build_ascii_dashboard(data)
        return PlainTextResponse(ascii_dashboard)

    return JSONResponse(content=data)