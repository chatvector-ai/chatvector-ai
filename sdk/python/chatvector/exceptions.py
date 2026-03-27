"""Custom exception hierarchy for the ChatVector SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


class ChatVectorAPIError(Exception):
    """Base exception raised for ChatVector API and transport errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Any | None = None,
        response: "httpx.Response | None" = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details
        self.response = response

    def __str__(self) -> str:
        """Return a compact, readable description of the error."""
        if self.status_code is None:
            return self.message
        return f"[{self.status_code}] {self.message}"


class ChatVectorAuthError(ChatVectorAPIError):
    """Raised when the API rejects authentication or authorization."""


class ChatVectorRateLimitError(ChatVectorAPIError):
    """Raised when the API signals that the client is being rate limited."""


class ChatVectorTimeoutError(ChatVectorAPIError):
    """Raised when a request or polling operation exceeds the allowed time."""
