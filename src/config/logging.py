import os
import sys

from loguru import logger


def setup_logging(debug: bool = False, log_level: str = "DEBUG") -> None:
    logger.remove()  # remove default handler

    json_logs = os.getenv("AGENTIC_HIRE_JSON_LOGS", "false").lower() == "true"

    # Plain text sink — active when not in JSON-only mode
    if not json_logs:
        if debug:
            logger.add(
                sys.stdout,
                level=log_level,
                format=(
                    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                    "<level>{level: <8}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                    "<level>{message}</level>"
                ),
            )
        else:
            logger.add(
                sys.stdout,
                level=log_level,
                format="{time} | {level} | {message}",
            )

    # JSON sink — opt-in via AGENTIC_HIRE_JSON_LOGS=true.
    # Phase 2 observability: pipe stderr into Datadog/Splunk/Loki.
    if json_logs:
        logger.add(
            sys.stderr,
            level=log_level,
            serialize=True,  # loguru built-in JSON serialisation
        )
