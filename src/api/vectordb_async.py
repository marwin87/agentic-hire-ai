"""Async wrapper for CVVectorManager to avoid blocking FastAPI event loop."""

from typing import Any
from src.tools.vectordb import CVVectorManager


async def get_cv_context_async(
    vector_manager: CVVectorManager, query: str = "job matching criteria"
) -> str:
    """Retrieve CV context asynchronously without event loop conflicts.

    Directly calls the async get_context_async() method to avoid creating
    a new event loop via asyncio.Runner(), which causes asyncpg connection
    pool errors when crossing event loop boundaries.

    Args:
        vector_manager: CVVectorManager instance with user_id scoped embeddings
        query: Search query string for semantic similarity (default: "job matching criteria")

    Returns:
        CV context string (empty if no embeddings found for user)
    """
    return await vector_manager.get_context_async(query)
