"""Tests for job_search_tool retry logic and error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.search import JobSearchProvider, job_search_tool
from src.config.settings import config


def _make_response(status: int, json_data: object = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    if json_data is not None:
        mock.json.return_value = json_data
        mock.raise_for_status = MagicMock()
    return mock


def _setup_client_mock(post_side_effects: list) -> tuple[MagicMock, MagicMock]:
    """Return (mock_class, mock_instance) with post returning given side_effects."""
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(side_effect=post_side_effects)

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_class, mock_instance


@pytest.mark.asyncio
async def test_503_retries_and_returns_error_after_exhaustion() -> None:
    responses = [_make_response(503)] * config.oriosearch_max_retries
    mock_class, _ = _setup_client_mock(responses)

    with (
        patch("src.tools.search.httpx.AsyncClient", mock_class),
        patch("src.tools.search.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await job_search_tool.ainvoke({"query": "Python developer"})

    assert "unavailable" in result.lower() or "503" in result or "attempts" in result


@pytest.mark.asyncio
async def test_503_then_success_returns_results() -> None:
    success = _make_response(200, [{"title": "Python Dev", "url": "http://x.com"}])
    responses = [_make_response(503), _make_response(503), success]
    mock_class, _ = _setup_client_mock(responses)

    with (
        patch("src.tools.search.httpx.AsyncClient", mock_class),
        patch("src.tools.search.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await job_search_tool.ainvoke({"query": "Python developer"})

    assert "Python Dev" in result or "x.com" in result


@pytest.mark.asyncio
async def test_http_error_returns_error_message() -> None:
    import httpx

    mock_class = MagicMock()
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(side_effect=httpx.HTTPError("connection refused"))
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.tools.search.httpx.AsyncClient", mock_class):
        result = await job_search_tool.ainvoke({"query": "Python developer"})

    assert "error" in result.lower() or "connect" in result.lower()


@pytest.mark.asyncio
async def test_unexpected_exception_returns_error_message() -> None:
    mock_class = MagicMock()
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(side_effect=RuntimeError("unexpected"))
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.tools.search.httpx.AsyncClient", mock_class):
        result = await job_search_tool.ainvoke({"query": "Python developer"})

    assert "error" in result.lower() or "failed" in result.lower()


@pytest.mark.asyncio
async def test_successful_request_returns_results() -> None:
    data = [{"title": "Go Engineer", "url": "http://corp.com/1"}]
    responses = [_make_response(200, data)]
    mock_class, _ = _setup_client_mock(responses)

    with patch("src.tools.search.httpx.AsyncClient", mock_class):
        result = await job_search_tool.ainvoke({"query": "Go engineer"})

    assert "Go Engineer" in result or "corp.com" in result


def test_job_search_provider_stores_tool() -> None:
    provider = JobSearchProvider()
    assert provider.search_tool is job_search_tool
