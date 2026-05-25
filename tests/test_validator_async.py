"""Tests for async JobValidator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.tools.job_validator import JobValidator
from src.schema.state import JobOffer


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM for testing."""
    mock = MagicMock()
    # Mock with_structured_output to return self for chaining
    mock.with_structured_output = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def validator(mock_llm: MagicMock) -> JobValidator:
    """Create a JobValidator with mocked LLM."""
    return JobValidator(llm=mock_llm)


@pytest.fixture
def sample_job() -> JobOffer:
    """Create a sample job for testing."""
    return JobOffer(
        id="123",
        title="Python Developer",
        company="Tech Corp",
        salary_range="N/A",
        description="Build Python applications",
        url="http://example.com/jobs/123",
    )


@pytest.mark.asyncio
async def test_validator_is_job_valid_is_async(validator: JobValidator) -> None:
    """Verify JobValidator.is_job_valid is async."""
    import inspect

    assert inspect.iscoroutinefunction(validator.is_job_valid)


@pytest.mark.asyncio
async def test_validator_rejects_invalid_url(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """Test validator rejects jobs with invalid URLs."""
    sample_job.url = "not-a-url"
    result = await validator.is_job_valid(sample_job)
    assert result is False


@pytest.mark.asyncio
async def test_validator_rejects_none_url(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """Test validator rejects jobs with None URL."""
    sample_job.url = None  # type: ignore
    result = await validator.is_job_valid(sample_job)
    assert result is False


@pytest.mark.asyncio
async def test_validator_with_http_error(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """Test validator handles HTTP errors gracefully."""
    import httpx

    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Simulate HTTP 404 error
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        mock_client_class.return_value = mock_client

        result = await validator.is_job_valid(sample_job)
        assert result is False
