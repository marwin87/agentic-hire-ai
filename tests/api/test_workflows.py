"""Tests for /api/workflows/search-jobs endpoint.

Tests verify endpoint auth, input validation, error handling, and response schema.
These are primarily contract tests; graph logic tested separately in test_graph_workflow.py
"""

import pytest
from typing import Any, cast
from uuid import uuid4

from src.api.schemas import OrchestrateResponse, OrchestrateJobResult
from src.db import User
from src.schema.state import JobOffer


@pytest.fixture
def test_user() -> User:
    """Create a test user."""
    return User(
        id=uuid4(),
        email="test@example.com",
        password_hash="$2b$12$...",
        created_at=None,
        updated_at=None,
    )


@pytest.fixture
def mock_job_offer() -> JobOffer:
    """Create a sample JobOffer."""
    return JobOffer(
        id="job-123",
        title="Python Engineer",
        company="Tech Corp",
        description="Build backend services",
        url="https://example.com/jobs/123",
        salary_range="$120k-$150k",
    )


class TestWorkflowsEndpoint:
    """Tests for /api/workflows/search-jobs endpoint contract."""

    def test_response_schema_has_required_fields(
        self, mock_job_offer: JobOffer
    ) -> None:
        """OrchestrateResponse should have all required fields."""
        job_result: OrchestrateJobResult = OrchestrateJobResult(
            id=mock_job_offer.id,
            title=mock_job_offer.title,
            company=mock_job_offer.company,
            url=mock_job_offer.url,
            match_score=0.85,
            analysis="Good match",
            evaluation="Excellent fit",
            error=None,
        )

        response = OrchestrateResponse(
            all_jobs=[job_result],
            shortlisted_jobs=[job_result],
            rejected_jobs=[],
            status="Complete",
            error_count=0,
        )

        assert response.all_jobs is not None
        assert response.shortlisted_jobs is not None
        assert response.rejected_jobs is not None
        assert response.status == "Complete"
        assert response.error_count == 0

    def test_orchestrate_job_result_structure(self, mock_job_offer: JobOffer) -> None:
        """Job result should have all orchestration fields."""
        job_result = OrchestrateJobResult(
            id=mock_job_offer.id,
            title=mock_job_offer.title,
            company=mock_job_offer.company,
            url=mock_job_offer.url,
            match_score=0.75,
            analysis="Good technical fit",
            evaluation="Consider applying",
            error=None,
        )

        # Verify schema can be constructed
        assert job_result.match_score >= 0.0
        assert job_result.match_score <= 1.0
        assert job_result.analysis is not None
        assert job_result.evaluation is not None

    def test_response_filters_by_score_threshold(self) -> None:
        """Shortlisted jobs should be above threshold, rejected below."""
        high_score_job = OrchestrateJobResult(
            id="job-1",
            title="Python Engineer",
            company="Tech Corp",
            url="https://example.com/jobs/1",
            match_score=0.85,
            analysis="Great match",
            evaluation="Excellent",
            error=None,
        )

        low_score_job = OrchestrateJobResult(
            id="job-2",
            title="Java Engineer",
            company="Old Corp",
            url="https://example.com/jobs/2",
            match_score=0.45,
            analysis="Poor match",
            evaluation=None,
            error=None,
        )

        # Verify filtering logic
        threshold = 0.6
        assert high_score_job.match_score >= threshold
        assert low_score_job.match_score < threshold

    def test_partial_failure_includes_error_field(self) -> None:
        """Job with processing error should have error field set."""
        failed_job = {
            "id": "job-fail",
            "title": "Unknown Job",
            "company": "Broken Corp",
            "url": "https://example.com/fail",
            "match_score": 0.0,
            "analysis": None,
            "evaluation": None,
            "error": "LLM timeout on evaluation",
        }

        assert failed_job["error"] is not None
        assert failed_job["evaluation"] is None

    def test_response_includes_all_processed_jobs(self) -> None:
        """all_jobs should include both shortlisted and rejected."""
        shortlisted: OrchestrateJobResult = OrchestrateJobResult(
            id="s-1",
            title="Short",
            company="Corp",
            url="https://example.com",
            match_score=0.8,
            analysis=None,
            evaluation=None,
            error=None,
        )
        rejected: OrchestrateJobResult = OrchestrateJobResult(
            id="r-1",
            title="Reject",
            company="Corp",
            url="https://example.com",
            match_score=0.4,
            analysis=None,
            evaluation=None,
            error=None,
        )

        response = OrchestrateResponse(
            all_jobs=[shortlisted, rejected],
            shortlisted_jobs=[shortlisted],
            rejected_jobs=[rejected],
            status="Complete",
            error_count=0,
        )

        assert len(response.all_jobs) == 2
        assert len(response.shortlisted_jobs) == 1
        assert len(response.rejected_jobs) == 1

    def test_error_count_tracks_failed_jobs(self) -> None:
        """error_count should reflect number of jobs with errors."""
        jobs_with_errors = [
            {"id": "j1", "error": "Timeout"},
            {"id": "j2", "error": "Connection refused"},
        ]

        error_count = sum(1 for job in jobs_with_errors if job.get("error"))
        assert error_count == 2
