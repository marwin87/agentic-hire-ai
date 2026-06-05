from langgraph.graph import StateGraph, END
from src.schema.state import AgenticHireState
from src.agents.agents import get_agent_factory  # Import the getter function
from src.config.settings import config
from src.utils.progress import emit
from loguru import logger
from typing import Any


def should_rescout(state: AgenticHireState) -> str:
    """
    Conditional logic to decide whether to re-run the scout or proceed.
    """
    valid_jobs = state.get("valid_jobs", [])
    found_jobs = state.get("found_jobs", [])
    rejected_jobs = state.get("rejected_jobs", [])
    max_offers = state.get("max_offers", 5)
    scout_runs = state.get("scout_runs", 0)

    logger.info(
        f"[ORCHESTRATOR] Evaluating should_rescout: found={len(found_jobs)}, valid={len(valid_jobs)}, target={max_offers}, runs={scout_runs}/{config.max_scout_runs}"
    )

    if scout_runs >= config.max_scout_runs:
        logger.warning(
            f"[ORCHESTRATOR] Max scout runs reached ({scout_runs}/{config.max_scout_runs}). Proceeding to orchestrator."
        )
        return "proceed"

    if len(valid_jobs) >= max_offers:
        logger.info(
            f"[ORCHESTRATOR] Target of {max_offers} valid jobs reached ({len(valid_jobs)} current). Proceeding to orchestrator."
        )
        return "proceed"

    if not found_jobs and scout_runs > 0:
        # If we've already tried and still have nothing, stop.
        logger.warning(
            "[ORCHESTRATOR] No jobs found in scout attempt. Stopping to prevent infinite loop."
        )
        return "end"

    logger.info(
        f"[ORCHESTRATOR] Proceeding to rescout. Need {max_offers - len(valid_jobs)} more jobs."
    )
    return "rescout"


async def orchestrator_node(state: AgenticHireState) -> dict[str, Any]:
    """Wrapper to add logging around orchestrator agent invocation."""
    factory = get_agent_factory(user_id=state.get("user_id"))
    valid_jobs = state.get("valid_jobs", [])
    cv_context = state.get("resume_context", "")
    logger.info(
        f"[ORCHESTRATOR] Invoking Orchestrator with {len(valid_jobs)} valid jobs and {len(cv_context)} chars of CV context"
    )
    result = await factory.orchestrator(state)
    shortlisted = result.get("shortlisted_jobs", [])
    logger.info(
        f"[ORCHESTRATOR] Orchestrator complete: {len(shortlisted)} shortlisted (score >= 0.6)"
    )
    return result


async def tailor_node(state: AgenticHireState) -> dict[str, Any]:
    """Wrapper to add logging around tailor agent invocation."""
    factory = get_agent_factory()
    shortlisted_jobs = state.get("shortlisted_jobs", [])
    logger.info(
        f"[ORCHESTRATOR] Invoking Tailor for {len(shortlisted_jobs)} shortlisted jobs"
    )
    result = await factory.tailor(state)
    logger.info("[ORCHESTRATOR] Tailor complete: evaluations generated")
    return result


async def validate_and_limit_jobs_node(state: AgenticHireState) -> dict[str, Any]:
    """
    Node to filter out invalid or expired job offers and limit the number.
    """
    factory = get_agent_factory()
    found_jobs = state.get("found_jobs", [])
    max_offers = state.get("max_offers", 5)

    logger.info(
        f"[ORCHESTRATOR] Validating {len(found_jobs)} found jobs, targeting {max_offers} max"
    )

    validated_jobs_with_status = []
    rejected_jobs = []  # New list for invalid jobs
    for job in found_jobs:
        await emit("validate_jobs", f"Checking: {job.title} @ {job.company}")
        is_valid = await factory.job_validator.is_job_valid(job)
        if is_valid:
            validated_jobs_with_status.append(job)
            await emit("validate_jobs", f"  ✓ Active")
        else:
            rejected_jobs.append(job)  # Track as rejected
            await emit("validate_jobs", f"  ✗ Inactive or expired")

    valid_jobs = validated_jobs_with_status

    # Limit the number of jobs to the configured maximum
    limited_jobs = valid_jobs[:max_offers]

    logger.info(
        f"[ORCHESTRATOR] Validation complete: {len(valid_jobs)} valid, {len(rejected_jobs)} rejected, {len(limited_jobs)} passed after limiting"
    )
    needs_more = len(limited_jobs) < max_offers
    await emit(
        "validate_jobs",
        f"✓ {len(limited_jobs)} valid, {len(rejected_jobs)} rejected"
        + (
            f" — need {max_offers - len(limited_jobs)} more, rescouting..."
            if needs_more
            else ""
        ),
    )

    return {
        "valid_jobs": limited_jobs,
        "rejected_jobs": rejected_jobs,  # Include in state (appends via annotation)
        "status": f"Validated and limited to {len(limited_jobs)} jobs.",
    }


def build_graph() -> Any:
    factory = get_agent_factory()
    # 2. Initialize the Graph with our State schema
    logger.info("[ORCHESTRATOR] Building LangGraph workflow")
    workflow = StateGraph(AgenticHireState)

    # 3. Add Nodes (The Workers)
    workflow.add_node("scout", factory.scout)
    workflow.add_node("validate_jobs", validate_and_limit_jobs_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("tailor", tailor_node)

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
