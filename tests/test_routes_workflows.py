"""Tests for evaluation and job persistence in the workflow endpoint."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.main import app
from src.api.routes.workflows import search_jobs_workflow
from src.api.schemas import OrchestrateRequest, OrchestrateResponse
from src.schema.state import JobOffer

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
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def two_shortlisted_jobs() -> list[JobOffer]:
    return [
        JobOffer(
            id="job-1",
            title="Python Engineer",
            company="Corp A",
            description="Build backend services",
            url="https://example.com/1",
            salary_range="$120k",
            match_score=0.85,
            analysis="Great technical fit",
        ),
        JobOffer(
            id="job-2",
            title="Backend Developer",
            company="Corp B",
            description="More backend work",
            url="https://example.com/2",
            salary_range="$130k",
            match_score=0.75,
            analysis="Good culture fit",
        ),
    ]


def _graph_result(shortlisted: list[JobOffer]) -> dict:
    """Build a minimal graph state dict with shortlisted jobs and tailor applications."""
    return {
        "shortlisted_jobs": shortlisted,
        "rejected_jobs": [],
        "valid_jobs": shortlisted,
        "applications": {
            job.id: {"founded_job_offer": f"Tailor summary for {job.id}"}
            for job in shortlisted
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(
    "src.api.routes.workflows.JobRepository.create_or_update", new_callable=AsyncMock
)
@patch("src.api.routes.workflows.EvaluationRepository.upsert", new_callable=AsyncMock)
@patch("src.api.routes.workflows.build_graph")
@patch("src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock)
@patch("src.api.routes.workflows.AgentFactory")
async def test_workflow_persists_evaluations_for_shortlisted_jobs(
    mock_factory_cls: MagicMock,
    mock_cv_context: AsyncMock,
    mock_build_graph: MagicMock,
    mock_upsert: AsyncMock,
    mock_create_or_update: AsyncMock,
    mock_user: MagicMock,
    mock_session: AsyncMock,
    two_shortlisted_jobs: list[JobOffer],
) -> None:
    """EvaluationRepository.upsert called once per shortlisted job; session committed once."""
    mock_cv_context.return_value = "CV context text"
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_graph_result(two_shortlisted_jobs))
    mock_build_graph.return_value = mock_graph

    request = OrchestrateRequest(criteria="Python engineer remote")
    response = await search_jobs_workflow(
        request=request,
        user=mock_user,
        session=mock_session,
    )

    assert mock_upsert.call_count == 2
    assert mock_session.commit.call_count == 1
    assert isinstance(response, OrchestrateResponse)
    assert len(response.shortlisted_jobs) == 2
    assert response.error_count == 0


@pytest.mark.asyncio
@patch(
    "src.api.routes.workflows.JobRepository.create_or_update", new_callable=AsyncMock
)
@patch("src.api.routes.workflows.EvaluationRepository.upsert", new_callable=AsyncMock)
@patch("src.api.routes.workflows.build_graph")
@patch("src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock)
@patch("src.api.routes.workflows.AgentFactory")
async def test_workflow_returns_response_on_persistence_failure(
    mock_factory_cls: MagicMock,
    mock_cv_context: AsyncMock,
    mock_build_graph: MagicMock,
    mock_upsert: AsyncMock,
    mock_create_or_update: AsyncMock,
    mock_user: MagicMock,
    mock_session: AsyncMock,
    two_shortlisted_jobs: list[JobOffer],
) -> None:
    """DB commit failure must not block the workflow response."""
    mock_cv_context.return_value = "CV context text"
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_graph_result(two_shortlisted_jobs))
    mock_build_graph.return_value = mock_graph
    mock_session.commit.side_effect = Exception("DB down")

    request = OrchestrateRequest(criteria="Python engineer remote")
    response = await search_jobs_workflow(
        request=request,
        user=mock_user,
        session=mock_session,
    )

    assert isinstance(response, OrchestrateResponse)
    assert len(response.shortlisted_jobs) == 2
    assert response.error_count == 0


@pytest.mark.asyncio
@patch(
    "src.api.routes.workflows.JobRepository.create_or_update", new_callable=AsyncMock
)
@patch("src.api.routes.workflows.EvaluationRepository.upsert", new_callable=AsyncMock)
@patch("src.api.routes.workflows.build_graph")
@patch("src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock)
@patch("src.api.routes.workflows.AgentFactory")
async def test_stream_endpoint_persists_evaluations_for_shortlisted_jobs(
    mock_factory_cls: MagicMock,
    mock_cv_context: AsyncMock,
    mock_build_graph: MagicMock,
    mock_upsert: AsyncMock,
    mock_create_or_update: AsyncMock,
    mock_user: MagicMock,
    mock_session: AsyncMock,
    two_shortlisted_jobs: list[JobOffer],
) -> None:
    """Streaming endpoint: EvaluationRepository.upsert called per shortlisted job."""
    mock_cv_context.return_value = "CV context text"

    applications = {
        job.id: {"founded_job_offer": f"Summary for {job.id}"}
        for job in two_shortlisted_jobs
    }

    async def mock_astream(*args: object, **kwargs: object):  # type: ignore[return]
        yield {"scout": {"found_jobs": two_shortlisted_jobs}}
        yield {
            "validate_jobs": {
                "valid_jobs": two_shortlisted_jobs,
                "rejected_jobs": [],
            }
        }
        yield {
            "orchestrator": {
                "shortlisted_jobs": two_shortlisted_jobs,
                "rejected_jobs": [],
            }
        }
        yield {"tailor": {"applications": applications}}

    mock_graph = MagicMock()
    mock_graph.astream = mock_astream
    mock_build_graph.return_value = mock_graph

    async def override_get_db():  # type: ignore[return]
        yield mock_session

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with client.stream(
                "POST",
                "/api/workflows/search-jobs/stream",
                json={"criteria": "Python engineer remote"},
            ) as response:
                # Consume the full SSE stream so run_graph() completes
                async for _ in response.aiter_lines():
                    pass
        # Allow the background task to finish
        await asyncio.sleep(0.1)
    finally:
        app.dependency_overrides.clear()

    assert mock_upsert.call_count == 2
