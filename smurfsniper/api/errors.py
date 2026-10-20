"""Typed errors raised by every API client.

Callers never see httpx exceptions; the transport maps them onto these.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(
        self,
        service: str,
        message: str,
        *,
        status: int | None = None,
        url: str | None = None,
    ):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.status = status
        self.url = url


class NotFound(ApiError):
    """404, or a semantically empty response where a single item is required."""


class AuthError(ApiError):
    """401/403 (for example an invalid Aligulac key)."""


class RateLimited(ApiError):
    """429 after retries were exhausted."""

    def __init__(self, *args, retry_after: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class Unavailable(ApiError):
    """Connection error, timeout, or 5xx after retries."""


class BadResponse(ApiError):
    """JSON decode or model validation failure."""
