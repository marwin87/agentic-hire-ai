"""FastAPI middleware utilities for request/response handling."""

import time
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger


class RequestTimingMiddleware:
    """Middleware to measure and log request execution time."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, request: Request, call_next: Callable[..., Any]) -> Any:
        """Process request and log execution time."""
        start_time = time.time()
        response = await call_next(request)
        elapsed = time.time() - start_time
        logger.info(
            f"Request completed: {request.method} {request.url.path} in {elapsed:.2f}s"
        )
        return response


def create_error_response(
    status_code: int, error_type: str, detail: str, code: str
) -> JSONResponse:
    """Create a structured error response.

    Args:
        status_code: HTTP status code
        error_type: Error category (e.g., 'validation_error')
        detail: Human-readable error message
        code: Machine-readable error code

    Returns:
        JSONResponse with structured error data
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": error_type, "detail": detail, "code": code},
    )
