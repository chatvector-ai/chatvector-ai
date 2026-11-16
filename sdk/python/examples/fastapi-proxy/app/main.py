"""FastAPI server-side proxy for ChatVector."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from chatvector import AsyncChatVectorClient
from chatvector.exceptions import (
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
)
from chatvector.models import DocumentStatus, RetrievalScope
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def required_environment_variable(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set in the server environment")
    return value


chatvector: AsyncChatVectorClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global chatvector
    chatvector = AsyncChatVectorClient(
        base_url=required_environment_variable("CHATVECTOR_BASE_URL"),
        api_key=required_environment_variable("CHATVECTOR_API_KEY"),
    )
    try:
        yield
    finally:
        if chatvector is not None:
            await chatvector.aclose()
            chatvector = None


app = FastAPI(title="ChatVector FastAPI proxy example", lifespan=lifespan)


def get_chatvector_client() -> AsyncChatVectorClient:
    if chatvector is None:
        raise RuntimeError("ChatVector client is not initialized")
    return chatvector


async def require_application_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "code": "application_auth_required",
                "message": "Authenticate with the application before using this route",
            },
        )
    return x_user_id.strip()


async def run_until_disconnect(request: Request, coroutine):
    """Run async work and cancel it when the downstream client disconnects."""
    task = asyncio.create_task(coroutine)

    async def watch_disconnect() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(0.25)
        task.cancel()

    watcher = asyncio.create_task(watch_disconnect())
    try:
        return await task
    except asyncio.CancelledError as exc:
        raise HTTPException(
            status_code=499,
            detail={
                "code": "request_cancelled",
                "message": "Request cancelled",
            },
        ) from exc
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


async def wait_for_ready_with_disconnect(
    request: Request,
    client: AsyncChatVectorClient,
    document_id: str,
    *,
    timeout: int = 60,
    interval: int = 2,
) -> DocumentStatus:
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0.")
    if interval <= 0:
        raise ValueError("interval must be greater than 0.")

    deadline = time.monotonic() + timeout
    last_response: DocumentStatus | None = None

    while True:
        if await request.is_disconnected():
            raise asyncio.CancelledError()

        last_response = await client.get_status(document_id)
        status = last_response.status

        if status == "completed":
            return last_response

        if status == "failed":
            message = f"Document '{document_id}' processing failed."
            error_payload = last_response.error
            if isinstance(error_payload, dict):
                error_message = error_payload.get("message")
                if isinstance(error_message, str) and error_message:
                    message = f"{message} {error_message}"
            raise ChatVectorAPIError(message, details=last_response.to_dict())

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ChatVectorTimeoutError(
                f"Timed out after {timeout} second(s) while waiting for document "
                f"'{document_id}' to be ready.",
                status_code=408,
                details=last_response.to_dict() if last_response else None,
            )

        await asyncio.sleep(min(interval, remaining))


async def upload_bytes(client: AsyncChatVectorClient, filename: str, data: bytes):
    suffix = os.path.splitext(filename)[1]
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(data)
            temp_path = handle.name
        return await client.upload_document(temp_path)
    finally:
        if temp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/documents", status_code=201)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    _user_id: Annotated[str, Depends(require_application_user_id)],
    client: Annotated[AsyncChatVectorClient, Depends(get_chatvector_client)],
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"code": "file_required", "message": "Multipart field 'file' is required"},
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=400,
            detail={"code": "file_required", "message": "Multipart field 'file' is required"},
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": "Uploaded file exceeds the example limit"},
        )

    async def work() -> dict[str, object]:
        uploaded = await upload_bytes(client, file.filename, data)
        ready = await wait_for_ready_with_disconnect(
            request,
            client,
            uploaded.document_id,
            timeout=60,
            interval=2,
        )
        return {
            "document": {
                "id": uploaded.document_id,
                "status": ready.status,
                "created_at": ready.created_at,
                "updated_at": ready.updated_at,
            }
        }

    return await run_until_disconnect(request, work())


@app.get("/api/documents/{document_id}")
async def get_document_status(
    request: Request,
    document_id: str,
    _user_id: Annotated[str, Depends(require_application_user_id)],
    client: Annotated[AsyncChatVectorClient, Depends(get_chatvector_client)],
):
    async def work() -> dict[str, object]:
        document = await client.get_status(document_id)
        return {
            "document": {
                "id": document.document_id,
                "status": document.status,
                "chunks": document.chunks,
                "created_at": document.created_at,
                "updated_at": document.updated_at,
                "queue_position": document.queue_position,
            }
        }

    return await run_until_disconnect(request, work())


class ChatRequestBody(BaseModel):
    question: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    session_id: str | None = None
    match_count: int | None = Field(default=None, ge=1)
    scope: Literal["session", "tenant"] | None = None


@app.post("/api/chat")
async def chat(
    request: Request,
    body: ChatRequestBody,
    _user_id: Annotated[str, Depends(require_application_user_id)],
    client: Annotated[AsyncChatVectorClient, Depends(get_chatvector_client)],
):
    async def work() -> dict[str, object]:
        session_id = body.session_id.strip() if body.session_id else None
        if not session_id:
            session = await client.create_session()
            session_id = session.id

        scope: RetrievalScope | None = body.scope
        response = await client.chat(
            question=body.question.strip(),
            doc_id=body.doc_id.strip(),
            session_id=session_id,
            match_count=body.match_count or 5,
            scope=scope,
        )
        return {
            "session_id": session_id,
            "response": {
                "status": response.status,
                "answer": response.answer,
                "sources": [source.to_dict() for source in response.sources],
                "error": response.error,
                "latency_ms": response.latency_ms,
                "model": response.model,
            },
        }

    return await run_until_disconnect(request, work())


def _retry_after_ms(error: ChatVectorRateLimitError) -> int | None:
    if error.response is None:
        return None
    retry_after = error.response.headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return int(float(retry_after) * 1000)
    except ValueError:
        return None


@app.exception_handler(ChatVectorRateLimitError)
async def handle_rate_limit(_request: Request, error: ChatVectorRateLimitError):
    retry_after_ms = _retry_after_ms(error)
    headers: dict[str, str] = {}
    if retry_after_ms is not None:
        headers["Retry-After"] = str(max(1, retry_after_ms // 1000))
    return JSONResponse(
        status_code=429,
        headers=headers,
        content={
            "error": {
                "code": "chatvector_rate_limited",
                "message": "The document service is rate limited; try again later",
                "retry_after_ms": retry_after_ms,
            }
        },
    )


@app.exception_handler(ChatVectorAPIError)
async def handle_chatvector_error(_request: Request, error: ChatVectorAPIError):
    status_code = 502
    message = "The document service request failed"

    if isinstance(error, ChatVectorTimeoutError):
        status_code = 504
        message = "The document service timed out"
    elif isinstance(error, ChatVectorAuthError):
        status_code = 502
        message = "The document service request failed"

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": "chatvector_error",
                "message": message,
            }
        },
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(_request: Request, error: HTTPException):
    if isinstance(error.detail, dict) and "code" in error.detail:
        return JSONResponse(status_code=error.status_code, content={"error": error.detail})
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Invalid request",
            }
        },
    )
