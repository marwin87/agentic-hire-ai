"""Tests for async TailorAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.agents.tailor import TailorAgent
from src.schema.state import JobOffer, AgenticHireState
from typing import cast


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM for testing."""
    mock = MagicMock()
    return mock


@pytest.fixture
def tailor(mock_llm: MagicMock) -> TailorAgent:
    """Create a TailorAgent with mocked LLM."""
    return TailorAgent(llm=mock_llm)


@pytest.fixture
def sample_job() -> JobOffer:
    """Create a sample job for testing."""
    return JobOffer(
        id="job-001",
        title="Python Developer",
        company="Tech Corp",
        salary_range="$100k-$150k",
        description="Build Python applications",
        url="http://example.com/jobs/001",
        match_score=0.8,
        analysis="Good match for backend development",
    )


@pytest.fixture
def sample_state(sample_job: JobOffer) -> AgenticHireState:
    """Create a sample state with a job to evaluate."""
    return cast(
        AgenticHireState,
        {
            "shortlisted_jobs": [sample_job],
            "applications": {},
            "max_offers": 1,
            "scout_runs": 0,
            "status": "Starting",
            "valid_jobs": [],
            "rejected_jobs": [],
            "found_jobs": [],
            "resume_context": "Sample CV context",
            "target_criteria": "",
            "seen_jobs": [],
        },
    )


@pytest.mark.asyncio
async def test_tailor_call_is_async(tailor: TailorAgent) -> None:
    """Verify TailorAgent.__call__ is async."""
    import inspect

    assert inspect.iscoroutinefunction(tailor.__call__)


@pytest.mark.asyncio
async def test_tailor_generates_evaluation(
    tailor: TailorAgent, sample_state: AgenticHireState
) -> None:
    """Test that tailor generates evaluation for jobs."""
    # Mock the LLM to return a message
    mock_message = MagicMock()
    mock_message.content = "This job is a great fit for your Python expertise."
    tailor.llm.ainvoke = AsyncMock(return_value=mock_message)

    result = await tailor(sample_state)

    # Verify result has applications
    assert "applications" in result
    assert len(result["applications"]) == 1
    assert "job-001" in result["applications"]


@pytest.mark.asyncio
async def test_tailor_handles_empty_jobs(tailor: TailorAgent) -> None:
    """Test tailor handles empty job list gracefully."""
    state = cast(
        AgenticHireState,
        {
            "shortlisted_jobs": [],
            "applications": {},
            "max_offers": 0,
            "scout_runs": 0,
            "status": "Starting",
            "valid_jobs": [],
            "rejected_jobs": [],
            "found_jobs": [],
            "resume_context": "",
            "target_criteria": "",
            "seen_jobs": [],
        },
    )

    result = await tailor(state)

    assert "Tailor skipped" in result.get("status", "")


@pytest.mark.asyncio
async def test_tailor_formats_output(
    tailor: TailorAgent, sample_state: AgenticHireState, sample_job: JobOffer
) -> None:
    """Test that tailor formats output with portal and evaluation."""
    mock_message = MagicMock()
    mock_message.content = "Worth applying - strong match."
    tailor.llm.ainvoke = AsyncMock(return_value=mock_message)

    result = await tailor(sample_state)

    app_data = result["applications"]["job-001"]
    assert "founded_job_offer" in app_data
    assert "job_title" in app_data
    assert "company" in app_data
    assert app_data["job_title"] == sample_job.title
    assert app_data["company"] == sample_job.company
    # Portal should be extracted from URL
    assert "example.com" in app_data["founded_job_offer"]


@pytest.mark.asyncio
async def test_tailor_handles_exception(
    tailor: TailorAgent, sample_state: AgenticHireState
) -> None:
    """Test tailor handles LLM exceptions gracefully."""
    tailor.llm.ainvoke = AsyncMock(side_effect=ValueError("LLM error"))

    # The tailor should not catch exceptions, they bubble up to the endpoint
    with pytest.raises(ValueError, match="LLM error"):
        await tailor(sample_state)
