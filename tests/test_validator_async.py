"""Tests for async JobValidator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.tools.job_validator import JobValidator, ExpirationCheck
from src.schema.state import JobOffer
from src.schema.validation import ValidationFailureReason


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


# --- validate_job_with_reason tests ---


@pytest.mark.asyncio
async def test_validate_job_with_reason_url_invalid(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """Bad URL returns URL_INVALID reason code."""
    sample_job.url = "not-a-url"
    result = await validator.validate_job_with_reason(sample_job)
    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.URL_INVALID
    assert "not-a-url" in result.reason_text


@pytest.mark.asyncio
async def test_validate_job_with_reason_na_url(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """N/A URL returns URL_INVALID."""
    sample_job.url = "N/A"
    result = await validator.validate_job_with_reason(sample_job)
    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.URL_INVALID


@pytest.mark.asyncio
async def test_validate_job_with_reason_http_error(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """HTTP 404 returns HTTP_ERROR reason code."""
    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.HTTP_ERROR
    assert "404" in result.reason_text


@pytest.mark.asyncio
async def test_validate_job_with_reason_http_500(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """HTTP 500 also returns HTTP_ERROR."""
    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.HTTP_ERROR


@pytest.mark.asyncio
async def test_validate_job_with_reason_expired(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """LLM says job is closed returns JOB_EXPIRED with LLM reason text."""
    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>This position has been filled.</body></html>"
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        validator.checker.ainvoke = AsyncMock(
            return_value=ExpirationCheck(
                is_active=False, reason="Position has been filled"
            )
        )

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.JOB_EXPIRED
    assert "filled" in result.reason_text.lower()


@pytest.mark.asyncio
async def test_validate_job_with_reason_valid(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """Active job returns is_valid=True with no reason code."""
    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Apply now!</body></html>"
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        validator.checker.ainvoke = AsyncMock(
            return_value=ExpirationCheck(is_active=True, reason="Job is active")
        )

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is True
    assert result.reason_code is None
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_validate_job_with_reason_http_timeout(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """HTTP timeout returns VALIDATION_TIMEOUT reason code."""
    import httpx

    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client_class.return_value = mock_client

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.VALIDATION_TIMEOUT


@pytest.mark.asyncio
async def test_validate_job_with_reason_network_error(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """HTTP network error (ConnectError) returns HTTP_ERROR."""
    import httpx

    with patch("src.tools.job_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.HTTPError("connection refused")
        mock_client_class.return_value = mock_client

        result = await validator.validate_job_with_reason(sample_job)

    assert result.is_valid is False
    assert result.reason_code == ValidationFailureReason.HTTP_ERROR


@pytest.mark.asyncio
async def test_is_job_valid_delegates_to_validate_with_reason(
    validator: JobValidator, sample_job: JobOffer
) -> None:
    """is_job_valid() is a backward-compat wrapper that returns the bool from validate_job_with_reason."""
    from src.schema.validation import JobValidationResult

    with patch.object(
        validator,
        "validate_job_with_reason",
        new=AsyncMock(return_value=JobValidationResult(is_valid=True, duration_ms=10)),
    ):
        result = await validator.is_job_valid(sample_job)
    assert result is True
