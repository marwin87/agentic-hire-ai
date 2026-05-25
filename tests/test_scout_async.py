"""Tests for async Scout agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.agents.scout import ScoutAgent
from src.schema.state import AgenticHireState, JobOffer


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM for testing."""
    mock = MagicMock()
    # Mock bind_tools to return self for chaining
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def scout_agent(mock_llm: MagicMock) -> ScoutAgent:
    """Create a Scout agent with mocked LLM."""
    return ScoutAgent(llm=mock_llm)


@pytest.fixture
def initial_state() -> AgenticHireState:
    """Create a basic initial state."""
    return AgenticHireState(
        resume_context="Python developer with 5 years experience",
        target_criteria="Python developer roles",
        found_jobs=[],
        valid_jobs=[],
        rejected_jobs=[],
        max_offers=5,
        scout_runs=0,
        status="Initial",
        search_queries=[],
        shortlisted_jobs=[],
        applications={},
        seen_jobs=[],
    )


@pytest.mark.asyncio
async def test_scout_agent_is_async(scout_agent: ScoutAgent) -> None:
    """Verify Scout agent __call__ is async."""
    import inspect

    assert inspect.iscoroutinefunction(scout_agent.__call__)


@pytest.mark.asyncio
async def test_scout_agent_with_no_tool_calls(
    scout_agent: ScoutAgent, initial_state: AgenticHireState
) -> None:
    """Test Scout agent when LLM doesn't make tool calls."""
    # Mock LLM to return a message with no tool calls
    mock_response = MagicMock()
    mock_response.tool_calls = []
    mock_response.type = "ai"
    mock_response.content = "I found these jobs: Job1, Job2"

    scout_agent.llm.ainvoke = AsyncMock(return_value=mock_response)
    scout_agent.parser.parse = MagicMock(return_value=[])

    result = await scout_agent(initial_state)

    assert "found_jobs" in result
    assert "scout_runs" in result
    assert result["scout_runs"] == 1


@pytest.mark.asyncio
async def test_scout_agent_increments_scout_runs(
    scout_agent: ScoutAgent, initial_state: AgenticHireState
) -> None:
    """Test Scout agent increments scout_runs counter."""
    mock_response = MagicMock()
    mock_response.tool_calls = []
    mock_response.type = "ai"
    mock_response.content = ""

    scout_agent.llm.ainvoke = AsyncMock(return_value=mock_response)
    scout_agent.parser.parse = MagicMock(return_value=[])

    # First call
    result1 = await scout_agent(initial_state)
    assert result1["scout_runs"] == 1

    # Second call with previous scout_runs
    initial_state_2 = {**initial_state, "scout_runs": 1}
    result2 = await scout_agent(initial_state_2)
    assert result2["scout_runs"] == 2
