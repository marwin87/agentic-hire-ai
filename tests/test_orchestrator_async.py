"""Tests for async OrchestratorAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from src.agents.orchestrator import OrchestratorAgent, MatchRating
from src.schema.state import JobOffer, AgenticHireState
from typing import cast


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM for testing."""
    mock = MagicMock()
    # Mock with_structured_output to return self for chaining
    mock.with_structured_output = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def mock_vector_manager() -> MagicMock:
    """Create a mock CVVectorManager for testing."""
    mock = MagicMock()
    mock.get_context = MagicMock(return_value="Relevant CV context")
    return mock


@pytest.fixture
def orchestrator(
    mock_llm: MagicMock, mock_vector_manager: MagicMock
) -> OrchestratorAgent:
    """Create an OrchestratorAgent with mocked LLM and vector manager."""
    return OrchestratorAgent(
        llm=mock_llm, vector_manager=mock_vector_manager, user_id=uuid4()
    )


@pytest.fixture
def sample_job() -> JobOffer:
    """Create a sample job for testing."""
    return JobOffer(
        id="job-001",
        title="Python Developer",
        company="Tech Corp",
        salary_range="$100k-$150k",
        description="Build Python applications with modern frameworks",
        url="http://example.com/jobs/001",
    )


@pytest.fixture
def sample_state(sample_job: JobOffer) -> AgenticHireState:
    """Create a sample state with a valid job."""
    return cast(
        AgenticHireState,
        {
            "valid_jobs": [sample_job],
            "shortlisted_jobs": [],
            "rejected_jobs": [],
            "max_offers": 1,
            "scout_runs": 0,
            "status": "Starting",
            "search_queries": [],
            "applications": {},
            "found_jobs": [],
            "resume_context": "",
            "target_criteria": "",
            "seen_jobs": [],
        },
    )


@pytest.mark.asyncio
async def test_orchestrator_call_is_async(
    orchestrator: OrchestratorAgent,
) -> None:
    """Verify OrchestratorAgent.__call__ is async."""
    import inspect

    assert inspect.iscoroutinefunction(orchestrator.__call__)


@pytest.mark.asyncio
async def test_orchestrator_calls_vector_retrieval(
    orchestrator: OrchestratorAgent, sample_state: AgenticHireState
) -> None:
    """Test that orchestrator calls CVVectorManager for RAG context."""
    # Mock the judge to return a good match
    rating = MatchRating(score=0.8, reasoning="Good match")
    orchestrator.judge = MagicMock()
    orchestrator.judge.ainvoke = AsyncMock(return_value=rating)

    result = await orchestrator(sample_state)

    # Verify vector manager was called (would be wrapped in asyncio.to_thread)
    assert orchestrator.vector_manager.get_context.called


@pytest.mark.asyncio
async def test_orchestrator_score_threshold_filtering(
    orchestrator: OrchestratorAgent, sample_state: AgenticHireState
) -> None:
    """Test that jobs below score threshold (0.6) are rejected."""
    # Mock judge to return a low score
    rating = MatchRating(score=0.3, reasoning="Poor match")
    orchestrator.judge = MagicMock()
    orchestrator.judge.ainvoke = AsyncMock(return_value=rating)

    result = await orchestrator(sample_state)

    # Job should be rejected due to score < 0.6
    assert len(result.get("shortlisted_jobs", [])) == 0
    assert len(result.get("rejected_jobs", [])) == 1


@pytest.mark.asyncio
async def test_orchestrator_accepts_jobs_at_threshold(
    orchestrator: OrchestratorAgent, sample_state: AgenticHireState
) -> None:
    """Test that jobs with score >= 0.6 are shortlisted."""
    # Mock judge to return a score at threshold
    rating = MatchRating(score=0.6, reasoning="Meets threshold")
    orchestrator.judge = MagicMock()
    orchestrator.judge.ainvoke = AsyncMock(return_value=rating)

    result = await orchestrator(sample_state)

    # Job should be accepted at threshold
    assert len(result.get("shortlisted_jobs", [])) == 1
    assert len(result.get("rejected_jobs", [])) == 0


@pytest.mark.asyncio
async def test_orchestrator_sorts_by_score(
    orchestrator: OrchestratorAgent,
    sample_state: AgenticHireState,
    sample_job: JobOffer,
) -> None:
    """Test that shortlisted jobs are sorted by score descending."""
    job2 = JobOffer(
        id="job-002",
        title="Senior Python Developer",
        company="Tech Corp 2",
        salary_range="$150k-$200k",
        description="Lead Python development",
        url="http://example.com/jobs/002",
    )
    sample_state["valid_jobs"] = [sample_job, job2]

    # Mock judge to return different scores
    ratings = [
        MatchRating(score=0.7, reasoning="Good match"),
        MatchRating(score=0.9, reasoning="Excellent match"),
    ]
    orchestrator.judge = MagicMock()
    orchestrator.judge.ainvoke = AsyncMock(side_effect=ratings)

    result = await orchestrator(sample_state)

    shortlisted = result.get("shortlisted_jobs", [])
    assert len(shortlisted) == 2
    # Verify sorting: highest score first
    assert shortlisted[0].match_score >= shortlisted[1].match_score


@pytest.mark.asyncio
async def test_orchestrator_handles_empty_valid_jobs(
    orchestrator: OrchestratorAgent, sample_state: AgenticHireState
) -> None:
    """Test orchestrator handles empty valid_jobs gracefully."""
    sample_state["valid_jobs"] = []

    result = await orchestrator(sample_state)

    assert len(result.get("shortlisted_jobs", [])) == 0
    assert "Orchestrator skipped" in result.get("status", "")
