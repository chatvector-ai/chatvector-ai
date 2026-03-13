"""
System Status Endpoint
Provides real-time system metrics and health checks
"""

import logging
import psutil
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.db.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

# Track application start time
APP_START_TIME = datetime.now()

# Version info - update this when releasing new versions
VERSION = "v0.1.0"


def format_uptime(start_time: datetime) -> str:
    """
    Format uptime as 'Xd Yh Zm'
    
    Args:
        start_time: Application start timestamp
        
    Returns:
        Formatted uptime string
    """
    uptime = datetime.now() - start_time
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    return f"{days}d {hours}h {minutes}m"


def check_database_connectivity(db: Session) -> tuple[bool, str]:
    """
    Check if database connection is active
    
    Args:
        db: Database session
        
    Returns:
        Tuple of (is_connected, status_message)
    """
    try:
        # Simple connectivity check
        db.execute(text("SELECT 1"))
        return True, "Connected"
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        return False, "Disconnected"


def get_document_count(db: Session) -> int:
    """
    Get total number of indexed documents
    
    Args:
        db: Database session
        
    Returns:
        Document count
    """
    try:
        # Adjust table name based on actual schema
        result = db.execute(text("SELECT COUNT(*) FROM documents"))
        count = result.scalar()
        return count if count else 0
    except Exception as e:
        logger.error(f"Failed to get document count: {e}")
        return 0


def get_memory_usage() -> float:
    """
    Get current process memory usage percentage
    
    Returns:
        Memory usage percentage (0-100)
    """
    try:
        process = psutil.Process()
        memory_percent = process.memory_percent()
        return round(memory_percent, 1)
    except Exception as e:
        logger.error(f"Failed to get memory usage: {e}")
        return 0.0


def format_number(num: int) -> str:
    """
    Format number with thousand separators
    
    Args:
        num: Number to format
        
    Returns:
        Formatted number string (e.g., "1,234")
    """
    return f"{num:,}"


def generate_status_ascii(
    db_connected: bool,
    db_status: str,
    uptime: str,
    documents_count: int,
    memory_percent: float
) -> str:
    """
    Generate ASCII art status display
    
    Args:
        db_connected: Database connectivity status
        db_status: Database status message
        uptime: Formatted uptime string
        documents_count: Number of indexed documents
        memory_percent: Memory usage percentage
        
    Returns:
        Formatted ASCII status display
    """
    # Status indicators
    db_indicator = "🟢" if db_connected else "🔴"
    api_indicator = "🟢"  # API is online if this endpoint responds
    
    # Memory usage bar (10 blocks)
    memory_bars = int(memory_percent / 10)
    memory_bar = "█" * memory_bars + "░" * (10 - memory_bars)
    
    # Placeholder indicators for features not yet implemented
    embeddings_indicator = "🟡"
    llm_indicator = "🟡"
    
    status_text = f"""
  {api_indicator} API Server: ONLINE                              
  {db_indicator} Database: {db_status}                             
  {embeddings_indicator} Embeddings: Pending Implementation                         
  {llm_indicator} LLM Service: Pending Implementation                       
                                                     
  💾 Memory Usage:   [{memory_bar}] {memory_percent}%                
  📁 Documents Indexed: {format_number(documents_count)}                          
  💬 Total Queries: Pending Implementation                          
                                                     
  ⏱ Uptime: {uptime}                              
  🏷 Version: {VERSION}        
"""
    return status_text


@router.get("/status")
def get_status(request: Request, db: Session = Depends(get_db)):
    """
    System status endpoint with live metrics
    
    Returns ASCII art display for browsers, JSON for API clients
    
    Args:
        request: FastAPI request object
        db: Database session (injected)
        
    Returns:
        HTMLResponse for browsers, dict for API clients
    """
    logger.info("Status endpoint accessed")
    
    # Gather real-time metrics
    db_connected, db_status = check_database_connectivity(db)
    uptime = format_uptime(APP_START_TIME)
    documents_count = get_document_count(db)
    memory_percent = get_memory_usage()
    
    # Check if request is from browser
    accept = request.headers.get("accept", "").lower()
    user_agent = request.headers.get("user-agent", "").lower()
    is_browser = (
        "text/html" in accept or
        any(token in user_agent for token in ("mozilla", "chrome", "safari", "firefox", "edge"))
    )
    
    if is_browser:
        # Return ASCII art for browser viewing
        ascii_status = generate_status_ascii(
            db_connected, db_status, uptime, documents_count, memory_percent
        )
        return HTMLResponse(
            content=f"<pre style=\"font-family: monospace; background: #000; color: #0f0; padding: 20px;\">{ascii_status}</pre>"
        )
    
    # Return JSON for API clients
    return {
        "status": "online",
        "version": VERSION,
        "uptime": uptime,
        "metrics": {
            "api_server": {
                "status": "online",
                "indicator": "green"
            },
            "database": {
                "status": db_status.lower(),
                "connected": db_connected,
                "indicator": "green" if db_connected else "red"
            },
            "embeddings": {
                "status": "pending_implementation",
                "indicator": "yellow"
            },
            "llm_service": {
                "status": "pending_implementation",
                "indicator": "yellow"
            },
            "documents_indexed": documents_count,
            "memory_usage_percent": memory_percent,
            "total_queries": "pending_implementation"
        },
        "timestamp": datetime.now().isoformat()
    }
