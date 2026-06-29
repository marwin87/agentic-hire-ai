"""Tests for LangGraph workflow orchestration and state management."""

import pytest
from typing import Any, cast
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

from src.graph import (
    should_rescout,
    validate_and_limit_jobs_node,
    orchestrator_node,
    tailor_node,
    build_graph,
)
from src.schema.state import AgenticHireState, JobOffer


@pytest.fixture
def initial_state() -> AgenticHireState:
    """Create a minimal initial state for testing."""
    return AgenticHireState(
        found_jobs=[],
        valid_jobs=[],
        rejected_jobs=[],
        shortlisted_jobs=[],
        applications={},
        resume_context="",
        target_criteria="",
        status="Initial",
        max_offers=3,
        scout_runs=0,
        seen_jobs=[],
    )


@pytest.fixture
def mock_job_offer() -> JobOffer:
    """Create a sample JobOffer for testing."""
    return JobOffer(
        id="job-123",
        title="Python Engineer",
        company="Tech Corp",
        description="Build backend services with Python",
        url="https://example.com/jobs/123",
        salary_range="$120k-$150k",
    )


# ===== Tests for should_rescout Logic =====


@patch("src.graph.config")
def test_should_rescout_max_runs_reached(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    """When max scout runs reached, should return 'proceed'."""
    mock_config.max_scout_runs = 3
    state = cast(AgenticHireState, {**initial_state, "scout_runs": 3, "valid_jobs": []})
    assert should_rescout(state) == "proceed"


@patch("src.graph.config")
def test_should_rescout_target_jobs_reached(
    mock_config: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """When max_offers reached, should return 'proceed'."""
    mock_config.max_scout_runs = 5
    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    job2 = mock_job_offer.model_copy(update={"id": "job2"})
    job3 = mock_job_offer.model_copy(update={"id": "job3"})

    state = cast(
        AgenticHireState,
        {**initial_state, "valid_jobs": [job1, job2, job3], "max_offers": 3},
    )
    assert should_rescout(state) == "proceed"


@patch("src.graph.config")
def test_should_rescout_no_jobs_found_after_run(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    """When no jobs found after scout_runs > 0, should return 'end'."""
    mock_config.max_scout_runs = 5
    state = cast(
        AgenticHireState,
        {**initial_state, "found_jobs": [], "scout_runs": 1, "valid_jobs": []},
    )
    assert should_rescout(state) == "end"


@patch("src.graph.config")
def test_should_rescout_initial_run_no_jobs(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    """On first run with no jobs, should rescout (not end)."""
    mock_config.max_scout_runs = 3
    state = cast(
        AgenticHireState,
        {**initial_state, "found_jobs": [], "scout_runs": 0, "valid_jobs": []},
    )
    assert should_rescout(state) == "rescout"


@patch("src.graph.config")
def test_should_rescout_need_more_jobs(
    mock_config: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """When valid_jobs < max_offers and no limits hit, should rescout."""
    mock_config.max_scout_runs = 5
    job1 = mock_job_offer.model_copy(update={"id": "job1"})

    state = cast(
        AgenticHireState,
        {
            **initial_state,
            "found_jobs": [job1],
            "valid_jobs": [job1],
            "max_offers": 5,
            "scout_runs": 0,
        },
    )
    assert should_rescout(state) == "rescout"


# ===== Tests for Validation Node =====


@patch("src.graph.get_agent_factory")
@pytest.mark.asyncio
async def test_validate_and_limit_all_valid(
    mock_get_factory: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """All jobs valid → should all pass validation."""
    mock_factory = MagicMock()
    mock_factory.job_validator.is_job_valid = AsyncMock(return_value=True)
    mock_get_factory.return_value = mock_factory

    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    job2 = mock_job_offer.model_copy(update={"id": "job2"})
    state = cast(
        AgenticHireState, {**initial_state, "found_jobs": [job1, job2], "max_offers": 5}
    )

    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 2
    assert len(result["rejected_jobs"]) == 0
    assert result["valid_jobs"][0].id == "job1"
    assert result["valid_jobs"][1].id == "job2"


@patch("src.graph.get_agent_factory")
@pytest.mark.asyncio
async def test_validate_and_limit_some_invalid(
    mock_get_factory: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """Some jobs invalid → should separate into valid/rejected."""
    mock_factory = MagicMock()

    async def mock_is_valid(job: JobOffer) -> bool:
        return job.id != "job2"

    mock_factory.job_validator.is_job_valid = mock_is_valid
    mock_get_factory.return_value = mock_factory

    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    job2 = mock_job_offer.model_copy(update={"id": "job2"})
    job3 = mock_job_offer.model_copy(update={"id": "job3"})
    state = cast(
        AgenticHireState,
        {**initial_state, "found_jobs": [job1, job2, job3], "max_offers": 5},
    )

    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 2
    assert len(result["rejected_jobs"]) == 1
    assert result["valid_jobs"][0].id == "job1"
    assert result["valid_jobs"][1].id == "job3"
    assert result["rejected_jobs"][0].id == "job2"


@patch("src.graph.get_agent_factory")
@pytest.mark.asyncio
async def test_validate_and_limit_enforces_limit(
    mock_get_factory: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """Max_offers limit enforced even if all jobs valid."""
    mock_factory = MagicMock()
    mock_factory.job_validator.is_job_valid = AsyncMock(return_value=True)
    mock_get_factory.return_value = mock_factory

    jobs = [mock_job_offer.model_copy(update={"id": f"job{i}"}) for i in range(10)]
    state = cast(
        AgenticHireState, {**initial_state, "found_jobs": jobs, "max_offers": 3}
    )

    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 3
    assert len(result["rejected_jobs"]) == 0


# ===== Tests for Graph Compilation =====


@patch("src.graph.get_agent_factory")
@patch("src.graph.StateGraph")
def test_build_graph_structure(
    mock_state_graph_class: Any, mock_get_factory: Any
) -> None:
    """Graph should compile with all nodes and edges."""
    mock_workflow = MagicMock()
    mock_state_graph_class.return_value = mock_workflow

    mock_factory = MagicMock()
    mock_get_factory.return_value = mock_factory

    compiled_graph = build_graph()

    # Verify nodes were added
    assert (
        mock_workflow.add_node.call_count >= 4
    )  # scout, validate, orchestrator, tailor
    mock_workflow.set_entry_point.assert_called_once_with("scout")

    # Verify edges were added
    assert mock_workflow.add_edge.call_count >= 2
    mock_workflow.add_conditional_edges.assert_called_once()

    # Verify compilation
    mock_workflow.compile.assert_called_once()


# ===== Tests for Node Invocations =====


@patch("src.graph.get_agent_factory")
@pytest.mark.asyncio
async def test_orchestrator_node_invocation(
    mock_get_factory: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """Orchestrator node should invoke factory.orchestrator and return result."""
    mock_factory = MagicMock()
    mock_factory.orchestrator = AsyncMock(
        return_value={"shortlisted_jobs": [mock_job_offer]}
    )
    mock_get_factory.return_value = mock_factory

    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    state = cast(AgenticHireState, {**initial_state, "valid_jobs": [job1]})

    result = await orchestrator_node(state)

    mock_factory.orchestrator.assert_called_once()
    assert "shortlisted_jobs" in result


@patch("src.graph.get_agent_factory")
@pytest.mark.asyncio
async def test_tailor_node_invocation(
    mock_get_factory: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """Tailor node should invoke factory.tailor and return result."""
    mock_factory = MagicMock()
    mock_factory.tailor = AsyncMock(
        return_value={"applications": {"job1": {"evaluation": "Great fit"}}}
    )
    mock_get_factory.return_value = mock_factory

    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    state = cast(AgenticHireState, {**initial_state, "shortlisted_jobs": [job1]})

    result = await tailor_node(state)

    mock_factory.tailor.assert_called_once()
    assert "applications" in result
