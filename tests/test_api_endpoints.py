"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from src.api.main import app
from src.schema.state import JobOffer


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test that /health endpoint responds correctly."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("src.api.routes.search.get_factory")
def test_search_jobs_endpoint(mock_get_factory: MagicMock, client: TestClient) -> None:
    """Test POST /search_jobs endpoint."""
    # Mock the factory and scout agent
    mock_factory = MagicMock()
    mock_get_factory.return_value = mock_factory

    # Mock scout to return some jobs
    job1 = JobOffer(
        id="1",
        title="Python Dev",
        company="Corp A",
        salary_range="$100k",
        description="Python role",
        url="http://example.com/1",
    )
    mock_factory.scout = AsyncMock(
        return_value={
            "found_jobs": [job1],
            "status": "Found 1 job",
        }
    )

    response = client.post(
        "/api/search_jobs",
        json={"criteria": "Python developer", "max_results": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert "found_jobs" in data
    assert data["status"] == "Found 1 job"


@patch("src.api.routes.validation.get_factory")
def test_validate_jobs_endpoint(
    mock_get_factory: MagicMock, client: TestClient
) -> None:
    """Test POST /validate_jobs endpoint."""
    mock_factory = MagicMock()
    mock_get_factory.return_value = mock_factory

    # Mock validator to mark job as valid
    async def mock_validate(job: JobOffer) -> bool:
        return job.id != "job-2"

    mock_factory.job_validator.is_job_valid = mock_validate

    job1 = {
        "id": "job-1",
        "title": "Python Dev",
        "company": "Corp A",
        "salary_range": "$100k",
        "description": "Python role",
        "url": "http://example.com/1",
    }
    job2 = {
        "id": "job-2",
        "title": "Go Dev",
        "company": "Corp B",
        "salary_range": "$120k",
        "description": "Go role",
        "url": "http://example.com/2",
    }

    response = client.post("/api/validate_jobs", json={"jobs": [job1, job2]})

    assert response.status_code == 200
    data = response.json()
    assert "valid_jobs" in data
    assert "rejected_jobs" in data


@patch("src.api.routes.scoring.get_factory")
def test_score_jobs_endpoint(
    mock_get_factory: MagicMock, client: TestClient
) -> None:
    """Test POST /score_jobs endpoint."""
    mock_factory = MagicMock()
    mock_get_factory.return_value = mock_factory

    job1 = JobOffer(
        id="job-1",
        title="Python Dev",
        company="Corp A",
        salary_range="$100k",
        description="Python role",
        url="http://example.com/1",
        match_score=0.8,
        analysis="Good match",
    )
    mock_factory.orchestrator = AsyncMock(
        return_value={
            "shortlisted_jobs": [job1],
            "rejected_jobs": [],
            "status": "Shortlisted 1 job",
        }
    )

    response = client.post(
        "/api/score_jobs",
        json=[
            {
                "id": "job-1",
                "title": "Python Dev",
                "company": "Corp A",
                "salary_range": "$100k",
                "description": "Python role",
                "url": "http://example.com/1",
            }
        ],
    )

    # The endpoint expects {"jobs": [...]} but we're testing the body format
    response = client.post(
        "/api/score_jobs",
        json={
            "jobs": [
                {
                    "id": "job-1",
                    "title": "Python Dev",
                    "company": "Corp A",
                    "salary_range": "$100k",
                    "description": "Python role",
                    "url": "http://example.com/1",
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "shortlisted_jobs" in data
    assert "scores" in data


@patch("src.api.routes.evaluation.get_factory")
def test_evaluate_job_endpoint(
    mock_get_factory: MagicMock, client: TestClient
) -> None:
    """Test POST /evaluate_job/{job_id} endpoint."""
    mock_factory = MagicMock()
    mock_get_factory.return_value = mock_factory

    mock_factory.tailor = AsyncMock(
        return_value={
            "applications": {
                "job-1": {
                    "founded_job_offer": "example.com -> http://example.com/1\nWorth applying",
                    "job_title": "Python Dev",
                    "company": "Corp A",
                }
            },
            "status": "Generated 1 evaluation",
        }
    )

    response = client.post(
        "/api/evaluate_job/job-1",
        json={
            "job_id": "job-1",
            "job": {
                "id": "job-1",
                "title": "Python Dev",
                "company": "Corp A",
                "salary_range": "$100k",
                "description": "Python role",
                "url": "http://example.com/1",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "job-1"
    assert "evaluation" in data


def test_invalid_json_request(client: TestClient) -> None:
    """Test that invalid JSON returns 422 error."""
    response = client.post("/api/validate_jobs", json={"jobs": "not-a-list"})
    assert response.status_code == 422
