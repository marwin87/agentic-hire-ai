import pytest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.tools.scrape import scrape_webpage_tool, JOB_LINKS_PREFIX, JOB_POSTING_PREFIX


def _build_playwright_mock(
    *,
    json_ld: Any = None,
    job_links: list[str] | None = None,
    body_text: str = "Some job page text content",
    goto_raises: Exception | None = None,
) -> AsyncMock:
    """Build a mock async_playwright() context manager for scrape_webpage_tool tests."""
    mock_page = AsyncMock()

    if goto_raises is not None:
        mock_page.goto = AsyncMock(side_effect=goto_raises)
    else:
        mock_page.goto = AsyncMock(return_value=None)
        # evaluate is called twice: first for JSON-LD, then for job links
        mock_page.evaluate = AsyncMock(side_effect=[json_ld, job_links or []])
        mock_page.inner_text = AsyncMock(return_value=body_text)

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    mock_p = MagicMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


@pytest.mark.asyncio
async def test_json_ld_job_page() -> None:
    json_ld_data = {
        "@type": "JobPosting",
        "title": "Senior Python Developer",
        "hiringOrganization": {"name": "Acme Corp"},
        "description": "Build scalable systems.",
        "datePosted": "2026-05-01",
    }
    mock_ctx = _build_playwright_mock(json_ld=json_ld_data)

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke(
            {"url": "https://example.com/job/123"}
        )

    assert "Title: Senior Python Developer" in result
    assert "Company: Acme Corp" in result
    assert "Description:" in result


@pytest.mark.asyncio
async def test_listing_page_returns_job_links() -> None:
    links = [
        "https://portal.com/job/python-dev-1",
        "https://portal.com/job/python-dev-2",
        "https://portal.com/job/python-dev-3",
    ]
    mock_ctx = _build_playwright_mock(json_ld=None, job_links=links)

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke({"url": "https://portal.com/jobs"})

    assert result.startswith("JOB_LINKS:\n")
    for link in links:
        assert link in result


@pytest.mark.asyncio
async def test_text_fallback() -> None:
    # No JSON-LD, fewer than 3 job links → plain text returned
    mock_ctx = _build_playwright_mock(
        json_ld=None,
        job_links=["https://portal.com/job/only-one"],
        body_text="We are hiring a backend engineer with Python experience.",
    )

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke({"url": "https://example.com/about"})

    assert not result.startswith("JOB_LINKS:")
    assert not result.startswith("Error:")
    assert "Python" in result


@pytest.mark.asyncio
async def test_timeout_error() -> None:
    mock_ctx = _build_playwright_mock(goto_raises=PlaywrightTimeoutError("timed out"))

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke({"url": "https://slow.example.com"})

    assert result.startswith("Error:")
    assert "timed out" in result.lower() or "timeout" in result.lower()


@pytest.mark.asyncio
async def test_unexpected_exception() -> None:
    mock_ctx = _build_playwright_mock(goto_raises=RuntimeError("connection refused"))

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke(
            {"url": "https://unreachable.example.com"}
        )

    assert result.startswith("Error:")
    assert "RuntimeError" in result


# ===== Protocol Constants Tests =====


def test_job_links_prefix_constant_matches_scraper_output() -> None:
    """JOB_LINKS_PREFIX must match the prefix scrape_webpage_tool actually emits."""
    assert JOB_LINKS_PREFIX == "JOB_LINKS:"


def test_job_posting_prefix_constant_matches_scraper_output() -> None:
    """JOB_POSTING_PREFIX must match the prefix _format_job_posting actually emits."""
    assert JOB_POSTING_PREFIX == "Title:"


@pytest.mark.asyncio
async def test_listing_page_output_starts_with_job_links_prefix() -> None:
    """scrape_webpage_tool returns JOB_LINKS_PREFIX when a listing page is detected."""
    mock_ctx = _build_playwright_mock(
        json_ld=None,
        job_links=[
            "https://example.com/job/1",
            "https://example.com/job/2",
            "https://example.com/job/3",
        ],
    )

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke({"url": "https://example.com/jobs"})

    assert result.startswith(JOB_LINKS_PREFIX)


@pytest.mark.asyncio
async def test_json_ld_page_output_starts_with_job_posting_prefix() -> None:
    """scrape_webpage_tool returns JOB_POSTING_PREFIX when JSON-LD job data is found."""
    json_ld = {
        "@type": "JobPosting",
        "title": "Python Engineer",
        "hiringOrganization": {"name": "Acme Corp"},
        "description": "Build great things with Python.",
    }
    mock_ctx = _build_playwright_mock(json_ld=json_ld)

    with patch("src.tools.scrape.async_playwright", return_value=mock_ctx):
        result = await scrape_webpage_tool.ainvoke({"url": "https://acme.com/job/1"})

    assert result.startswith(JOB_POSTING_PREFIX)
