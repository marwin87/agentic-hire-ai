import pytest
from typing import cast, Any
from unittest.mock import MagicMock, patch
from src.graph import (
    should_rescout,
    validate_and_limit_jobs_node,
    orchestrator_node,
    tailor_node,
    build_graph,
)
from src.schema.state import AgenticHireState, JobOffer, deduplicate_seen_jobs
from langgraph.graph import StateGraph, END


# Fixture for a basic AgenticHireState
@pytest.fixture
def initial_state() -> AgenticHireState:
    return AgenticHireState(
        found_jobs=[],
        valid_jobs=[],
        rejected_jobs=[],
        max_offers=5,
        scout_runs=0,
        status="Initial state",
    )


# Fixture for a mock JobOffer
@pytest.fixture
def mock_job_offer() -> JobOffer:
    return JobOffer(
        id="123",
        title="Software Engineer",
        company="Tech Corp",
        salary_range="N/A",
        description="Exciting role",
        url="http://example.com/job/123",
    )


# --- Tests for should_rescout ---


@patch("src.graph.config")
def test_should_rescout_max_runs_reached(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    mock_config.max_scout_runs = 2
    state = cast(AgenticHireState, {**initial_state, "scout_runs": 2})
    assert should_rescout(state) == "proceed"


@patch("src.graph.config")
def test_should_rescout_max_valid_jobs_reached(
    mock_config: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    mock_config.max_scout_runs = 5
    state = cast(
        AgenticHireState,
        {**initial_state, "max_offers": 5, "valid_jobs": [mock_job_offer] * 5},
    )
    assert should_rescout(state) == "proceed"


@patch("src.graph.config")
def test_should_rescout_no_jobs_found_after_first_run(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    mock_config.max_scout_runs = 5
    state = cast(AgenticHireState, {**initial_state, "found_jobs": [], "scout_runs": 1})
    assert should_rescout(state) == "end"


@patch("src.graph.config")
def test_should_rescout_no_jobs_found_initial_run(
    mock_config: Any, initial_state: AgenticHireState
) -> None:
    # If no jobs found on initial run (scout_runs=0), it should still rescout
    mock_config.max_scout_runs = 1
    state = cast(AgenticHireState, {**initial_state, "found_jobs": [], "scout_runs": 0})
    assert should_rescout(state) == "rescout"


# --- Risk #5: Rescout boundary conditions ---


@patch("src.graph.config")
def test_should_rescout_one_below_max_scout_runs(
    mock_config: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """scout_runs == max_scout_runs - 1 must return 'rescout', not 'proceed'.

    Catches off-by-one: the loop should only stop AT max_scout_runs, not one run early.
    """
    mock_config.max_scout_runs = 3
    state = cast(
        AgenticHireState,
        {
            **initial_state,
            "scout_runs": 2,  # one below max (3 - 1 = 2)
            "valid_jobs": [],
            "found_jobs": [mock_job_offer],
        },
    )
    assert should_rescout(state) == "rescout"


@patch("src.graph.config")
def test_should_rescout_one_below_max_valid_jobs(
    mock_config: Any, initial_state: AgenticHireState, mock_job_offer: JobOffer
) -> None:
    """valid_jobs == max_offers - 1 must return 'rescout', not 'proceed'.

    Catches off-by-one: proceed requires reaching the target, not being one short.
    """
    mock_config.max_scout_runs = 5
    state = cast(
        AgenticHireState,
        {
            **initial_state,
            "max_offers": 3,
            "valid_jobs": [mock_job_offer, mock_job_offer],  # 2 jobs, target is 3
            "scout_runs": 0,
        },
    )
    assert should_rescout(state) == "rescout"


def test_deduplicate_seen_jobs_strips_duplicates_across_cycles() -> None:
    """deduplicate_seen_jobs must return unique URLs when the same URL appears in both lists.

    Simulates two scout cycles that both surface the same job posting.
    """
    existing = ["https://a.com", "https://b.com"]
    new = ["https://b.com", "https://c.com"]
    result = deduplicate_seen_jobs(existing, new)
    assert len(result) == 3
    assert set(result) == {"https://a.com", "https://b.com", "https://c.com"}


def test_deduplicate_seen_jobs_fully_overlapping_lists() -> None:
    """deduplicate_seen_jobs with fully identical lists returns unique URLs only."""
    urls = ["https://x.com", "https://y.com"]
    result = deduplicate_seen_jobs(urls, urls)
    assert len(result) == 2
    assert set(result) == {"https://x.com", "https://y.com"}


# --- Tests for validate_and_limit_jobs_node ---


@patch("src.graph.get_agent_factory")  # Patch the getter function
@pytest.mark.asyncio
async def test_validate_and_limit_jobs_node_all_valid(
    mock_get_agent_factory: Any,
    initial_state: AgenticHireState,
    mock_job_offer: JobOffer,
) -> None:
    from unittest.mock import AsyncMock

    mock_factory_instance = MagicMock()
    mock_get_agent_factory.return_value = mock_factory_instance

    mock_factory_instance.job_validator.is_job_valid = AsyncMock(return_value=True)
    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    job2 = mock_job_offer.model_copy(update={"id": "job2"})

    state = cast(
        AgenticHireState, {**initial_state, "found_jobs": [job1, job2], "scout_runs": 0}
    )
    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 2
    assert len(result["rejected_jobs"]) == 0
    assert result["valid_jobs"][0].id == "job1"
    assert result["valid_jobs"][1].id == "job2"
    assert "Validated and limited to 2 jobs." in result["status"]
    mock_factory_instance.job_validator.is_job_valid.assert_called_with(
        job2
    )  # Called for each job


@patch("src.graph.get_agent_factory")  # Patch the getter function
@pytest.mark.asyncio
async def test_validate_and_limit_jobs_node_some_invalid(
    mock_get_agent_factory: Any,
    initial_state: AgenticHireState,
    mock_job_offer: JobOffer,
) -> None:
    from unittest.mock import AsyncMock

    job1 = mock_job_offer.model_copy(update={"id": "job1"})
    job2 = mock_job_offer.model_copy(update={"id": "job2"})
    job3 = mock_job_offer.model_copy(update={"id": "job3"})

    mock_factory_instance = MagicMock()
    mock_get_agent_factory.return_value = mock_factory_instance

    # Mock validator to make job2 invalid
    async def mock_is_valid(job: JobOffer) -> bool:
        return job.id != "job2"

    mock_factory_instance.job_validator.is_job_valid = mock_is_valid

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
    assert "Validated and limited to 2 jobs." in result["status"]


@patch("src.graph.get_agent_factory")  # Patch the getter function
@pytest.mark.asyncio
async def test_validate_and_limit_jobs_node_limit_applied(
    mock_get_agent_factory: Any,
    initial_state: AgenticHireState,
    mock_job_offer: JobOffer,
) -> None:
    from unittest.mock import AsyncMock

    mock_factory_instance = MagicMock()
    mock_get_agent_factory.return_value = mock_factory_instance

    mock_factory_instance.job_validator.is_job_valid = AsyncMock(return_value=True)

    jobs = [mock_job_offer.model_copy(update={"id": f"job{i}"}) for i in range(10)]

    state = cast(
        AgenticHireState, {**initial_state, "found_jobs": jobs, "max_offers": 3}
    )

    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 3
    assert len(result["rejected_jobs"]) == 0
    assert result["valid_jobs"][0].id == "job0"
    assert result["valid_jobs"][2].id == "job2"
    assert "Validated and limited to 3 jobs." in result["status"]


@patch("src.graph.get_agent_factory")  # Patch the getter function
@pytest.mark.asyncio
async def test_validate_and_limit_jobs_node_no_jobs(
    mock_get_agent_factory: Any, initial_state: AgenticHireState
) -> None:
    from unittest.mock import AsyncMock

    mock_factory_instance = MagicMock()
    mock_get_agent_factory.return_value = mock_factory_instance

    mock_factory_instance.job_validator.is_job_valid = AsyncMock(return_value=True)

    state = cast(AgenticHireState, {**initial_state, "found_jobs": [], "max_offers": 5})

    result = await validate_and_limit_jobs_node(state)

    assert len(result["valid_jobs"]) == 0
    assert len(result["rejected_jobs"]) == 0
    assert "Validated and limited to 0 jobs." in result["status"]


# --- Tests for build_graph ---


@patch("src.graph.get_agent_factory")  # Patch the getter function
@patch("src.graph.StateGraph")
@patch("src.graph.logger")
def test_build_graph_compiles_and_adds_nodes_edges(
    mock_logger: Any, MockStateGraph: Any, mock_get_agent_factory: Any
) -> None:
    # Mock the workflow object that StateGraph() returns
    mock_workflow = MagicMock(spec=StateGraph)
    MockStateGraph.return_value = mock_workflow

    # Create a mock factory instance that the getter will return
    mock_factory_instance = MagicMock()
    mock_get_agent_factory.return_value = mock_factory_instance

    # Call the function under test
    compiled_graph = build_graph()

    # Assert that StateGraph was initialized
    MockStateGraph.assert_called_once_with(AgenticHireState)

    # Assert nodes were added using the mock_factory_instance
    mock_workflow.add_node.assert_any_call("scout", mock_factory_instance.scout)
    mock_workflow.add_node.assert_any_call(
        "validate_jobs", validate_and_limit_jobs_node
    )
    mock_workflow.add_node.assert_any_call("orchestrator", orchestrator_node)
    mock_workflow.add_node.assert_any_call("tailor", tailor_node)

    # Assert entry point was set
    mock_workflow.set_entry_point.assert_called_once_with("scout")

    # Assert edges were added
    mock_workflow.add_edge.assert_any_call("scout", "validate_jobs")
    mock_workflow.add_conditional_edges.assert_called_once_with(
        "validate_jobs",
        should_rescout,
        {"rescout": "scout", "proceed": "orchestrator", "end": END},
    )
    mock_workflow.add_edge.assert_any_call("orchestrator", "tailor")
    mock_workflow.add_edge.assert_any_call("tailor", END)

    # Assert compile was called
    mock_workflow.compile.assert_called_once()
    assert compiled_graph == mock_workflow.compile.return_value
