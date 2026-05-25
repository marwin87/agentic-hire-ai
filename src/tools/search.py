import httpx
from src.config.settings import config
from langchain_core.tools import tool
from loguru import logger


@tool
async def job_search_tool(query: str) -> str:
    """
    Search the web using OrioSearch API for job postings.
    Input should be a specific search query like 'Senior Python Developer jobs London'.
    Returns a string containing a list of search results with titles, snippets, and URLs.
    """
    logger.debug(f"Search Query: {query}")
    payload: dict[str, str | int] = {"query": query, "num_results": 10}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(config.oriosearch_base_url, json=payload)
            response.raise_for_status()

            # We return the raw string or JSON-like string for the LLM to parse
            results = response.json()
            return str(results)

    except httpx.HTTPError as e:
        return f"Error connecting to OrioSearch: {str(e)}"


class JobSearchProvider:
    """
    A wrapper class to manage search operations.
    In a real-world scenario, this could handle rotating API keys or
    filtering results before they reach the agent.
    """

    def __init__(self) -> None:
        self.search_tool = job_search_tool
