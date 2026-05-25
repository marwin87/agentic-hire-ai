"""Scout agent endpoint - search for jobs."""

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from src.agents.agents import get_agent_factory
from src.api.dependencies import get_factory, get_current_user
from src.api.schemas import SearchJobsRequest
from src.config.settings import config
from src.db import User
from src.schema.state import AgenticHireState

router = APIRouter(prefix="/api", tags=["search"])


class SearchJobsResponse:
    """Response model for search_jobs endpoint."""

    def __init__(self, found_jobs: list[Any], status: str) -> None:
        self.found_jobs = found_jobs
        self.status = status

    def dict(self) -> dict[str, Any]:
        return {"found_jobs": self.found_jobs, "status": self.status}


@router.post("/search_jobs")
async def search_jobs(
    request: SearchJobsRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search for jobs using the Scout agent.

    Accepts job search criteria and returns a list of job offers found via OrioSearch.

    Args:
        request: SearchJobsRequest with criteria and optional max_results
        user: Authenticated user from JWT token

    Returns:
        Dictionary with found_jobs list and status message
    """
    logger.info(
        f"POST /search_jobs requested by {user.email} with criteria: {request.criteria}"
    )

    try:
        factory = get_factory()

        # Build initial state for the agent
        # Note: resume_context will come from user's uploaded CV in future phases
        state: AgenticHireState = {
            "resume_context": "Candidate CV context will be added in Phase 2 after user authentication",
            "target_criteria": request.criteria,
            "found_jobs": [],
            "valid_jobs": [],
            "shortlisted_jobs": [],
            "applications": {},
            "search_queries": [],
            "status": "Starting scout agent...",
            "max_offers": request.max_results or 10,
            "scout_runs": 0,
            "rejected_jobs": [],
            "seen_jobs": [],
        }

        # Invoke Scout agent asynchronously
        logger.debug(f"Invoking Scout agent with state: {state}")
        result = await factory.scout(state)

        # Extract results
        found_jobs = result.get("found_jobs", [])
        status = result.get("status", "Search complete")

        logger.info(f"Scout agent found {len(found_jobs)} jobs")
        return {
            "found_jobs": [
                {
                    "id": job.id if hasattr(job, "id") else "",
                    "title": job.title if hasattr(job, "title") else "",
                    "company": job.company if hasattr(job, "company") else "",
                    "url": job.url if hasattr(job, "url") else "",
                }
                for job in found_jobs
            ],
            "status": status,
        }

    except Exception as e:
        logger.error(f"Error in search_jobs endpoint: {str(e)}", exc_info=e)
        return {
            "error": "search_failed",
            "detail": str(e),
            "code": "SEARCH_AGENT_ERROR",
            "found_jobs": [],
            "status": f"Search failed: {str(e)}",
        }
