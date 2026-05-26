"""Integration tests for POST /api/validate_jobs endpoint."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.dependencies import get_current_user
from src.api.main import app
from src.schema.state import JobOffer
from src.schema.validation import JobValidationResult, ValidationFailureReason

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = "test@example.com"
    return user


@pytest.fixture
def client(mock_user: MagicMock) -> TestClient:  # type: ignore[misc]
    """TestClient with auth bypassed via dependency override."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield TestClient(app)  # type: ignore[misc]
    app.dependency_overrides.clear()


def _job(**kwargs: object) -> dict:
    """Build a minimal valid job dict for the request body."""
    base: dict = {
        "id": "job-1",
        "title": "Python Dev",
        "company": "Corp",
        "url": "http://example.com/job",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# All jobs pass
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_all_pass(mock_factory_fn: MagicMock, client: TestClient) -> None:
    """All jobs pass validation → valid_jobs populated, rejected_jobs empty."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(is_valid=True, duration_ms=100)
    )

    response = client.post(
        "/api/validate_jobs",
        json={"jobs": [_job(id="1"), _job(id="2")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["valid_jobs"]) == 2
    assert len(data["rejected_jobs"]) == 0


# ---------------------------------------------------------------------------
# All jobs fail
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_all_fail(mock_factory_fn: MagicMock, client: TestClient) -> None:
    """All jobs fail → valid_jobs empty, rejected_jobs has structured reasons."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(
            is_valid=False,
            reason_code=ValidationFailureReason.HTTP_ERROR,
            reason_text="HTTP 404 error accessing job page",
            duration_ms=200,
        )
    )

    response = client.post(
        "/api/validate_jobs",
        json={"jobs": [_job(id="1"), _job(id="2")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["valid_jobs"]) == 0
    assert len(data["rejected_jobs"]) == 2
    for rj in data["rejected_jobs"]:
        assert rj["reason_code"] == "HTTP_ERROR"
        assert rj["reason_text"] == "HTTP 404 error accessing job page"


# ---------------------------------------------------------------------------
# Mixed results
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_mixed(mock_factory_fn: MagicMock, client: TestClient) -> None:
    """job-1 passes, job-2 fails — both lists populated with correct entries."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory

    async def side_effect(job: JobOffer) -> JobValidationResult:
        if job.id == "job-1":
            return JobValidationResult(is_valid=True, duration_ms=50)
        return JobValidationResult(
            is_valid=False,
            reason_code=ValidationFailureReason.JOB_EXPIRED,
            reason_text="Position has been filled",
            duration_ms=300,
        )

    mock_factory.job_validator.validate_job_with_reason = side_effect

    response = client.post(
        "/api/validate_jobs",
        json={"jobs": [_job(id="job-1"), _job(id="job-2")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["valid_jobs"]) == 1
    assert data["valid_jobs"][0]["id"] == "job-1"
    assert len(data["rejected_jobs"]) == 1
    assert data["rejected_jobs"][0]["id"] == "job-2"
    assert data["rejected_jobs"][0]["reason_code"] == "JOB_EXPIRED"
    assert data["rejected_jobs"][0]["reason_text"] == "Position has been filled"
    assert data["rejected_jobs"][0]["validation_duration_ms"] == 300


# ---------------------------------------------------------------------------
# Timeout — partial results
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_timeout_partial_results(
    mock_factory_fn: MagicMock, client: TestClient
) -> None:
    """slow-job times out and is rejected; fast-job still validates successfully."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory

    async def side_effect(job: JobOffer) -> JobValidationResult:
        if job.id == "slow-job":
            await asyncio.sleep(10)  # cancelled immediately by wait_for
        return JobValidationResult(is_valid=True, duration_ms=10)

    mock_factory.job_validator.validate_job_with_reason = side_effect

    with patch("src.api.routes.validation._PER_JOB_TIMEOUT_S", 0.01):
        response = client.post(
            "/api/validate_jobs",
            json={
                "jobs": [
                    _job(id="slow-job", url="http://example.com/slow"),
                    _job(id="fast-job", url="http://example.com/fast"),
                ]
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["rejected_jobs"]) == 1
    assert data["rejected_jobs"][0]["id"] == "slow-job"
    assert data["rejected_jobs"][0]["reason_code"] == "VALIDATION_TIMEOUT"
    assert len(data["valid_jobs"]) == 1
    assert data["valid_jobs"][0]["id"] == "fast-job"


# ---------------------------------------------------------------------------
# Specific reason codes
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_url_invalid_reason_code(
    mock_factory_fn: MagicMock, client: TestClient
) -> None:
    """URL_INVALID reason code is preserved in rejected_jobs."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(
            is_valid=False,
            reason_code=ValidationFailureReason.URL_INVALID,
            reason_text="Invalid URL: 'not-a-url'",
            duration_ms=0,
        )
    )

    response = client.post(
        "/api/validate_jobs",
        json={"jobs": [_job(url="not-a-url")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rejected_jobs"][0]["reason_code"] == "URL_INVALID"


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_http_error_reason_code(
    mock_factory_fn: MagicMock, client: TestClient
) -> None:
    """HTTP_ERROR reason code and text are forwarded to rejected_jobs."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(
            is_valid=False,
            reason_code=ValidationFailureReason.HTTP_ERROR,
            reason_text="HTTP 403 error accessing job page",
            duration_ms=150,
        )
    )

    response = client.post(
        "/api/validate_jobs",
        json={"jobs": [_job()]},
    )

    assert response.status_code == 200
    data = response.json()
    rj = data["rejected_jobs"][0]
    assert rj["reason_code"] == "HTTP_ERROR"
    assert "403" in rj["reason_text"]
    assert rj["validation_duration_ms"] == 150


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_response_schema(
    mock_factory_fn: MagicMock, client: TestClient
) -> None:
    """Response always contains valid_jobs and rejected_jobs keys (ValidateJobsResponse shape)."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(is_valid=True, duration_ms=50)
    )

    response = client.post("/api/validate_jobs", json={"jobs": [_job()]})

    assert response.status_code == 200
    data = response.json()
    assert "valid_jobs" in data
    assert "rejected_jobs" in data
    assert isinstance(data["valid_jobs"], list)
    assert isinstance(data["rejected_jobs"], list)


@patch("src.api.routes.validation.get_agent_factory")
def test_validate_jobs_rejected_job_has_all_fields(
    mock_factory_fn: MagicMock, client: TestClient
) -> None:
    """RejectedJob in response includes id, reason_code, reason_text, validation_duration_ms."""
    mock_factory = MagicMock()
    mock_factory_fn.return_value = mock_factory
    mock_factory.job_validator.validate_job_with_reason = AsyncMock(
        return_value=JobValidationResult(
            is_valid=False,
            reason_code=ValidationFailureReason.JOB_EXPIRED,
            reason_text="No longer accepting applications",
            duration_ms=420,
        )
    )

    job = _job(id="test-id", title="Test Role", company="ACME")
    response = client.post("/api/validate_jobs", json={"jobs": [job]})

    assert response.status_code == 200
    rj = response.json()["rejected_jobs"][0]
    assert rj["id"] == "test-id"
    assert rj["title"] == "Test Role"
    assert rj["company"] == "ACME"
    assert rj["reason_code"] == "JOB_EXPIRED"
    assert rj["reason_text"] == "No longer accepting applications"
    assert rj["validation_duration_ms"] == 420


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_validate_jobs_empty_list(client: TestClient) -> None:
    """Empty job list returns 200 with empty lists."""
    response = client.post("/api/validate_jobs", json={"jobs": []})
    assert response.status_code == 200
    data = response.json()
    assert data["valid_jobs"] == []
    assert data["rejected_jobs"] == []


def test_validate_jobs_invalid_body_422(client: TestClient) -> None:
    """Non-list jobs field returns 422 Unprocessable Entity."""
    response = client.post("/api/validate_jobs", json={"jobs": "not-a-list"})
    assert response.status_code == 422


def test_validate_jobs_unauthenticated() -> None:
    """No auth token returns 401."""
    bare_client = TestClient(app)
    response = bare_client.post("/api/validate_jobs", json={"jobs": []})
    assert response.status_code == 401
