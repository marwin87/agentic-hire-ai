"""Async wrapper for CVVectorManager to avoid blocking FastAPI event loop."""

import asyncio
from typing import Any


async def get_cv_context_async(
    vector_manager: Any, query: str = "job matching criteria"
) -> str:
    """Retrieve CV context asynchronously to avoid blocking FastAPI event loop.

    Wraps the synchronous CVVectorManager.get_context() method using asyncio.to_thread()
    so it doesn't block the FastAPI async event loop.

    Args:
        vector_manager: CVVectorManager instance with user_id scoped embeddings
        query: Search query string for semantic similarity (default: "job matching criteria")

    Returns:
        CV context string (empty if no embeddings found for user)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, vector_manager.get_context, query)
