import asyncio
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
    logger.debug(f"[ORIO] Search Query: {query}")
    logger.debug(f"[ORIO] Connecting to: {config.oriosearch_base_url}")
    payload: dict[str, str | int] = {"query": query, "num_results": 10, "search_depth": "advanced"}

    max_retries = 3
    retry_delay = 1  # Start with 1 second

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{config.oriosearch_base_url}/search"
                logger.debug(
                    f"[ORIO] Attempt {attempt + 1}/{max_retries}: Sending request to: {url}"
                )
                logger.debug(f"[ORIO] Payload: {payload}")
                response = await client.post(url, json=payload)
                logger.debug(f"[ORIO] Response status: {response.status_code}")

                # Retry on 503 Service Unavailable
                if response.status_code == 503:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"[ORIO] Got 503 Service Unavailable. Retrying in {retry_delay}s..."
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error(f"[ORIO] Got 503 after {max_retries} attempts")
                        return "OrioSearch service temporarily unavailable. Try again in a few moments."

                response.raise_for_status()

                # Success - parse and return results
                results = response.json()
                logger.debug(
                    f"[ORIO] Received {len(str(results))} characters of results"
                )
                logger.debug(f"[ORIO] Results preview: {str(results)[:500]}")
                return str(results)

        except httpx.HTTPError as e:
            logger.error(f"[ORIO] HTTP Error on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                return f"Error connecting to OrioSearch: {str(e)}"
        except Exception as e:
            logger.error(
                f"[ORIO] Unexpected error on attempt {attempt + 1}: {str(e)}",
                exc_info=True,
            )
            if attempt == max_retries - 1:
                return f"Error in job search: {str(e)}"

    return "Failed to connect to OrioSearch after multiple attempts."


class JobSearchProvider:
    """
    A wrapper class to manage search operations.
    In a real-world scenario, this could handle rotating API keys or
    filtering results before they reach the agent.
    """

    def __init__(self) -> None:
        self.search_tool = job_search_tool
