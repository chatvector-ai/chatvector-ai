import time
import psutil
import os
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()

START_TIME = time.time()


def get_database_status() -> str:
    return "connected"  # mock


def get_uptime() -> str:
    elapsed = int(time.time() - START_TIME)
    days = elapsed // 86400
    hours = (elapsed % 86400) // 3600
    minutes = (elapsed % 3600) // 60
    return f"{days}d {hours}h {minutes}m"


def get_document_count() -> int:
    return 0  # mock


def get_memory_usage() -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024 ** 3)
    total_gb = mem.total / (1024 ** 3)
    percent = mem.percent
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({percent}%)"


def get_version() -> str:
    return "v1.0.0"


@router.get("/status")
def get_status():
    return {
        "api_server": "ONLINE",
        "database": get_database_status(),
        "uptime": get_uptime(),
        "version": get_version(),
        "documents_indexed": f"{get_document_count():,}",
        "memory_usage": get_memory_usage(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }