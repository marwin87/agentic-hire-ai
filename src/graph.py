from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from src.schema.state import AgenticHireState
from src.agents.agents import get_agent_factory
from src.config.settings import config
from src.utils.progress import emit
from loguru import logger
from typing import Any

# Node and edge name constants — single source of truth to prevent typo-silent failures.
NODE_SCOUT = "scout"
NODE_VALIDATE = "validate_jobs"
NODE_ORCHESTRATOR = "orchestrator"
NODE_TAILOR = "tailor"
EDGE_RESCOUT = "rescout"
EDGE_PROCEED = "proceed"
EDGE_END = "end"


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
        return EDGE_PROCEED

    if len(valid_jobs) >= max_offers:
        logger.info(
            f"[ORCHESTRATOR] Target of {max_offers} valid jobs reached ({len(valid_jobs)} current). Proceeding to orchestrator."
        )
        return EDGE_PROCEED

    if not found_jobs and scout_runs > 0:
        logger.warning(
            "[ORCHESTRATOR] No jobs found in scout attempt. Stopping to prevent infinite loop."
        )
        return EDGE_END

    logger.info(
        f"[ORCHESTRATOR] Proceeding to rescout. Need {max_offers - len(valid_jobs)} more jobs."
    )
    return EDGE_RESCOUT


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
    factory = get_agent_factory(user_id=state.get("user_id"))
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
    factory = get_agent_factory(user_id=state.get("user_id"))
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


def build_graph() -> CompiledStateGraph:
    factory = get_agent_factory()
    logger.info("[ORCHESTRATOR] Building LangGraph workflow")
    workflow = StateGraph(AgenticHireState)

    workflow.add_node(NODE_SCOUT, factory.scout)
    workflow.add_node(NODE_VALIDATE, validate_and_limit_jobs_node)
    workflow.add_node(NODE_ORCHESTRATOR, orchestrator_node)
    workflow.add_node(NODE_TAILOR, tailor_node)

    workflow.set_entry_point(NODE_SCOUT)

    workflow.add_edge(NODE_SCOUT, NODE_VALIDATE)

    workflow.add_conditional_edges(
        NODE_VALIDATE,
        should_rescout,
        {EDGE_RESCOUT: NODE_SCOUT, EDGE_PROCEED: NODE_ORCHESTRATOR, EDGE_END: END},
    )

    workflow.add_edge(NODE_ORCHESTRATOR, NODE_TAILOR)
    workflow.add_edge(NODE_TAILOR, END)

    return workflow.compile()
