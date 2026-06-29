import asyncio
from src.graph import build_graph
from src.agents.agents import AgentFactory, get_agent_factory
from src.config.logging import setup_logging
from src.config.settings import config
from src.tools.vectordb import CVVectorManager
from src.db.database import init_db, close_db
from loguru import logger
from typing import Any, cast


def _configure_application() -> None:
    setup_logging(debug=config.debug_mode, log_level=config.log_level)


async def _prepare_cv_data(
    cv_file_path: str, factory_instance: AgentFactory
) -> CVVectorManager:
    """Ingest CV using the async pipeline — no sync wrapper, no asyncio.run() trap."""
    logger.info("Initializing Vector Manager and ingesting CV...")
    cv_manager = factory_instance.vector_manager
    try:
        await cv_manager.ingest_cv_async(cv_file_path)
        logger.info(f"CV from '{cv_file_path}' ingested successfully.")
    except FileNotFoundError:
        logger.error(
            f"CV file not found at '{cv_file_path}'. Please check the path in config."
        )
        raise
    except Exception as e:
        logger.error(f"Error ingesting CV: {e}")
        raise
    return cv_manager


async def _initialize_state(
    cv_manager: CVVectorManager,
    app_config: Any,
    user_prompt: str = config.initial_prompt,
) -> dict[str, Any]:
    """Build the initial LangGraph state using async resume retrieval."""
    logger.info("Fetching full resume text for initial context...")
    initial_context = await cv_manager.get_full_resume_text_async()

    initial_state: dict[str, Any] = {
        "resume_context": initial_context,
        "target_criteria": user_prompt,
        "found_jobs": [],
        "valid_jobs": [],
        "shortlisted_jobs": [],
        "rejected_jobs": [],
        "seen_jobs": [],
        "applications": {},
        "status": "Starting AgenticHire AI...",
        "max_offers": app_config.max_valid_offers,
        "scout_runs": 0,
    }

    logger.debug(
        f"Initial state setup with target_criteria: '{initial_state['target_criteria']}' and max_offers: {app_config.max_valid_offers}"
    )
    return initial_state


def _run_graph(initial_state: dict[str, Any], app_instance: Any) -> dict[str, Any]:
    """Invokes the LangGraph application with the initial state."""
    print("🚀 AgenticHire AI is starting...")
    logger.info("Invoking LangGraph application...")
    final_state = app_instance.invoke(initial_state)
    logger.info("LangGraph application finished successfully.")
    return cast(dict[str, Any], final_state)


def _display_results(final_state: dict[str, Any]) -> None:
    """Prints a summary of the job search results."""
    print("\n" + "=" * 30)
    print("🎯 JOB SEARCH SUMMARY")
    print("=" * 30)

    apps = final_state.get("applications", {})
    if not apps:
        print("No applications were generated.")
        logger.warning("No applications were generated in final state.")
        return

    for job_id, content in apps.items():
        print(
            f"\n📍 {content.get('job_title', 'N/A')} at {content.get('company', 'N/A')}"
        )
        if "founded_job_offer" in content:
            # Ensure 'founded_job_offer' is a string before slicing
            offer_text = str(content["founded_job_offer"])
            print(f"{offer_text[:500]}...")
        print("-" * 20)


async def _run_workflow() -> None:
    await init_db(config)
    try:
        factory_instance = get_agent_factory()
        app_instance = build_graph()
        cv_manager = await _prepare_cv_data(config.cv_file_path, factory_instance)
        initial_state = await _initialize_state(cv_manager, config)
        final_state = _run_graph(initial_state, app_instance)
        _display_results(final_state)
    finally:
        await close_db()


def main() -> None:
    _configure_application()
    logger.info("Starting AgenticHire AI main process.")
    asyncio.run(_run_workflow())


if __name__ == "__main__":
    main()
