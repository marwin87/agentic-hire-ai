"""Tests for RequestTimingMiddleware and create_error_response."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import Request

from src.api.middleware import RequestTimingMiddleware, create_error_response


def test_create_error_response_status_code() -> None:
    response = create_error_response(400, "validation_error", "Bad input", "BAD_INPUT")
    assert response.status_code == 400


def test_create_error_response_body_structure() -> None:
    response = create_error_response(404, "not_found", "Resource missing", "NOT_FOUND")
    data = json.loads(response.body)
    assert data["error"] == "not_found"
    assert data["detail"] == "Resource missing"
    assert data["code"] == "NOT_FOUND"


def test_create_error_response_500() -> None:
    response = create_error_response(
        500, "internal_error", "Unexpected error", "INTERNAL"
    )
    assert response.status_code == 500
    data = json.loads(response.body)
    assert data["error"] == "internal_error"


@pytest.mark.asyncio
async def test_request_timing_middleware_passes_through() -> None:
    middleware = RequestTimingMiddleware(app=MagicMock())

    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/health"

    mock_response = MagicMock()
    call_next = AsyncMock(return_value=mock_response)

    result = await middleware(mock_request, call_next)

    call_next.assert_called_once_with(mock_request)
    assert result is mock_response


@pytest.mark.asyncio
async def test_request_timing_middleware_returns_response() -> None:
    middleware = RequestTimingMiddleware(app=MagicMock())

    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.url.path = "/api/login"

    expected = MagicMock(status_code=200)
    call_next = AsyncMock(return_value=expected)

    result = await middleware(mock_request, call_next)
    assert result.status_code == 200
