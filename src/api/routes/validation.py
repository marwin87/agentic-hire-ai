"""Validation endpoint - filter invalid and expired jobs."""

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from src.api.dependencies import get_factory, get_current_user
from src.api.schemas import ValidateJobsRequest
from src.db import User
from src.graph import validate_and_limit_jobs_node
from src.schema.state import AgenticHireState, JobOffer

router = APIRouter(prefix="/api", tags=["validation"])


@router.post("/validate_jobs")
async def validate_jobs(
    request: ValidateJobsRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate and filter jobs - remove dead links and expired postings.

    Takes a list of jobs found by the Scout agent and filters out:
    - Jobs with invalid URLs
    - Dead links (HTTP 400+)
    - Expired/closed job postings

    Args:
        request: ValidateJobsRequest with list of jobs to validate
        user: Authenticated user from JWT token

    Returns:
        Dictionary with valid_jobs and rejected_jobs lists
    """
    logger.info(f"POST /validate_jobs requested by {user.email} with {len(request.jobs)} jobs")

    try:
        # Convert request job dicts to JobOffer objects
        jobs = [JobOffer(**job) if isinstance(job, dict) else job for job in request.jobs]

        # Build state for validation node
        state: AgenticHireState = {
            "found_jobs": jobs,
            "valid_jobs": [],
            "rejected_jobs": [],
            "max_offers": len(jobs),
            "scout_runs": 0,
            "status": "Starting validation...",
            "search_queries": [],
            "shortlisted_jobs": [],
            "applications": {},
            "resume_context": "",
            "target_criteria": "",
            "seen_jobs": [],
        }

        # Invoke validation node
        logger.debug(f"Invoking validation node with {len(jobs)} jobs")
        result = await validate_and_limit_jobs_node(state)

        valid_jobs = result.get("valid_jobs", [])
        rejected_jobs = result.get("rejected_jobs", [])

        logger.info(f"Validation complete: {len(valid_jobs)} valid, {len(rejected_jobs)} rejected")

        return {
            "valid_jobs": [
                {
                    "id": job.id if hasattr(job, "id") else "",
                    "title": job.title if hasattr(job, "title") else "",
                    "company": job.company if hasattr(job, "company") else "",
                    "url": job.url if hasattr(job, "url") else "",
                }
                for job in valid_jobs
            ],
            "rejected_jobs": [
                {
                    "id": job.id if hasattr(job, "id") else "",
                    "title": job.title if hasattr(job, "title") else "",
                    "company": job.company if hasattr(job, "company") else "",
                    "url": job.url if hasattr(job, "url") else "",
                }
                for job in rejected_jobs
            ],
            "status": result.get("status", "Validation complete"),
        }

    except Exception as e:
        logger.error(f"Error in validate_jobs endpoint: {str(e)}", exc_info=e)
        return {
            "error": "validation_failed",
            "detail": str(e),
            "code": "VALIDATION_ERROR",
            "valid_jobs": [],
            "rejected_jobs": [],
            "status": f"Validation failed: {str(e)}",
        }
