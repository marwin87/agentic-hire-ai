from langgraph.graph import StateGraph, END
from src.schema.state import AgenticHireState
from src.agents.agents import get_agent_factory  # Import the getter function
from src.config.settings import config
from loguru import logger
from typing import Any


def should_rescout(state: AgenticHireState) -> str:
    """
    Conditional logic to decide whether to re-run the scout or proceed.
    """
    logger.info("Evaluating conditional edge 'should_rescout'")
    valid_jobs = state.get("valid_jobs", [])
    found_jobs = state.get("found_jobs", [])
    rejected_jobs = state.get("rejected_jobs", [])
    max_offers = state.get("max_offers", 5)
    scout_runs = state.get("scout_runs", 0)

    logger.debug(
        f"State variables - found_jobs count: {len(found_jobs)}, valid_jobs count: {len(valid_jobs)} | Total rejected jobs: {len(rejected_jobs)} | Scout runs: {scout_runs}/{config.max_scout_runs}"
    )

    if scout_runs >= config.max_scout_runs:
        logger.warning("Max scout runs reached. Proceeding with available jobs.")
        return "proceed"

    if len(valid_jobs) >= max_offers:
        logger.info(
            f"Target of {max_offers} valid jobs reached (currently {len(valid_jobs)}). Proceeding."
        )
        return "proceed"

    if not found_jobs and scout_runs > 0:
        # If we've already tried and still have nothing, stop.
        logger.warning(
            "No jobs found in the previous scout run. Stopping to prevent infinite loops."
        )
        return "end"

    logger.info("Requirements not met, deciding to 'rescout'")
    return "rescout"


async def validate_and_limit_jobs_node(state: AgenticHireState) -> dict[str, Any]:
    """
    Node to filter out invalid or expired job offers and limit the number.
    """
    factory = get_agent_factory()
    logger.info("--- [NODE] EXECUTING JOB VALIDATION ---")
    found_jobs = state.get("found_jobs", [])
    max_offers = state.get("max_offers", 5)

    logger.debug(f"Validating {len(found_jobs)} found jobs")

    validated_jobs_with_status = []
    rejected_jobs = []  # New list for invalid jobs
    for job in found_jobs:
        is_valid = await factory.job_validator.is_job_valid(job)
        if is_valid:
            validated_jobs_with_status.append(job)
        else:
            rejected_jobs.append(job)  # Track as rejected

    valid_jobs = validated_jobs_with_status

    logger.debug(f"Found {len(valid_jobs)} valid jobs out of {len(found_jobs)}")

    # Limit the number of jobs to the configured maximum
    limited_jobs = valid_jobs[:max_offers]
    logger.debug(f"Limited jobs to {len(limited_jobs)} (max_offers={max_offers})")

    return {
        "valid_jobs": limited_jobs,
        "rejected_jobs": rejected_jobs,  # Include in state (appends via annotation)
        "status": f"Validated and limited to {len(limited_jobs)} jobs.",
    }


def build_graph() -> Any:
    factory = get_agent_factory()
    # 2. Initialize the Graph with our State schema
    logger.debug("Building LangGraph workflow")
    workflow = StateGraph(AgenticHireState)

    # 3. Add Nodes (The Workers)
    workflow.add_node("scout", factory.scout)
    workflow.add_node("validate_jobs", validate_and_limit_jobs_node)
    workflow.add_node("orchestrator", factory.orchestrator)
    workflow.add_node("tailor", factory.tailor)

    # 4. Set the Entry Point
    workflow.set_entry_point("scout")

    # 5. Define the Flow (Edges)
    workflow.add_edge("scout", "validate_jobs")

    # After validation, check if we need to scout again
    workflow.add_conditional_edges(
        "validate_jobs",
        should_rescout,
        {"rescout": "scout", "proceed": "orchestrator", "end": END},
    )

    # If we have jobs, they go from Matchmaker to Tailor
    workflow.add_edge("orchestrator", "tailor")

    # After tailoring, we are done
    workflow.add_edge("tailor", END)

    # 6. Compile the graph
    return workflow.compile()
