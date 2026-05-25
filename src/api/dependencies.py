"""FastAPI dependency injection utilities."""

from typing import Any

from src.agents.agents import get_agent_factory
from src.config.settings import config


def get_factory() -> Any:
    """Get the AgentFactory singleton instance.

    This is a FastAPI dependency that can be injected into route handlers.
    """
    return get_agent_factory()


def get_config() -> Any:
    """Get the AppConfig singleton instance.

    This is a FastAPI dependency that can be injected into route handlers.
    """
    return config
