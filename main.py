import asyncio
from src.graph import build_graph
from src.agents.agents import get_agent_factory
from src.config.logging import setup_logging
from src.config.settings import config
from src.db.database import init_db, close_db
from loguru import logger
from typing import Any, cast


def _configure_application() -> None:
    """Configures logging for the application."""
    setup_logging(debug=config.debug_mode, log_level=config.log_level)


def _prepare_cv_data(cv_file_path: str, factory_instance: Any) -> Any:
    """Initializes the Vector Manager and ingests the CV."""
    logger.info("Initializing Vector Manager and ingesting CV...")
    cv_manager = factory_instance.vector_manager
    try:
        cv_manager.ingest_cv(cv_file_path)
        logger.info(f"CV from '{cv_file_path}' ingested successfully.")
    except FileNotFoundError:
        logger.error(
            f"CV file not found at '{cv_file_path}'. Please check the path in config.py."
        )
        raise
    except Exception as e:
        logger.error(f"Error ingesting CV: {e}")
        raise
    return cv_manager


def _initialize_state(
    cv_manager: Any, app_config: Any, user_prompt: str = config.initial_prompt
) -> dict[str, Any]:
    """Sets up the initial state for the LangGraph application."""
    logger.info("Fetching full resume text for initial context...")
    initial_context = cv_manager.get_full_resume_text()

    initial_state = {
        "resume_context": initial_context,
        "target_criteria": user_prompt,
        "found_jobs": [],
        "shortlisted_jobs": [],
        "applications": {},
        "status": "Starting AgenticHire AI...",
        "max_offers": app_config.max_valid_offers,
        "max_scout_runs": app_config.max_scout_runs,
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


def main() -> None:
    _configure_application()
    logger.info("Starting AgenticHire AI main process.")

    # Initialize database engine before creating agents
    asyncio.run(init_db(config))

    try:
        # Get the factory and build the graph
        factory_instance = get_agent_factory()
        app_instance = build_graph()

        cv_manager = _prepare_cv_data(config.cv_file_path, factory_instance)
        initial_state = _initialize_state(cv_manager, config)
        final_state = _run_graph(initial_state, app_instance)
        _display_results(final_state)
    finally:
        # Clean up database connections
        asyncio.run(close_db())


if __name__ == "__main__":
    main()
