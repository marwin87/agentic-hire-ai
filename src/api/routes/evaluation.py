"""Evaluation endpoint - generate tailored application insights per job."""

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel

from src.api.dependencies import get_factory, get_current_user
from src.api.schemas import EvaluateJobRequest
from src.db import User
from src.schema.state import AgenticHireState, JobOffer

router = APIRouter(prefix="/api", tags=["evaluation"])


class EvaluateJobResponse(BaseModel):
    """Response model for evaluation endpoint."""

    job_id: str
    job_title: str
    company: str
    evaluation: str
    status: str


@router.post("/evaluate_job/{job_id}")
async def evaluate_job(
    job_id: str,
    request: EvaluateJobRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Generate tailored application insights for a specific job.

    Takes a job object and generates personalized evaluation using TailorAgent.
    The agent analyzes the match between candidate CV and job to determine
    if it's worth applying.

    Args:
        job_id: Unique identifier for the job
        request: EvaluateJobRequest with job details
        user: Authenticated user from JWT token

    Returns:
        Dictionary with job_id, evaluation text, and status
    """
    logger.info(f"POST /evaluate_job/{job_id} requested")

    try:
        factory = get_factory()

        # Convert job dict to JobOffer if needed
        job = JobOffer(**request.job) if isinstance(request.job, dict) else request.job

        # Build state for tailor agent
        state: AgenticHireState = {
            "shortlisted_jobs": [job],
            "applications": {},
            "max_offers": 1,
            "scout_runs": 0,
            "status": "Generating evaluation...",
            "search_queries": [],
            "valid_jobs": [],
            "rejected_jobs": [],
            "found_jobs": [],
            "resume_context": "Candidate CV context will be loaded in Phase 2",
            "target_criteria": "",
            "seen_jobs": [],
        }

        # Invoke Tailor agent
        logger.debug(f"Invoking Tailor agent for job {job_id}")
        result = await factory.tailor(state)

        applications = result.get("applications", {})
        evaluation_data = applications.get(job_id, {})

        logger.info(f"Tailor generated evaluation for job {job_id}")

        return {
            "job_id": job_id,
            "job_title": job.title,
            "company": job.company,
            "evaluation": evaluation_data.get("founded_job_offer", ""),
            "status": result.get("status", "Evaluation complete"),
        }

    except Exception as e:
        logger.error(
            f"Error in evaluate_job endpoint for job {job_id}: {str(e)}",
            exc_info=e,
        )
        return {
            "error": "evaluation_failed",
            "detail": str(e),
            "code": "EVALUATION_ERROR",
            "job_id": job_id,
            "evaluation": "",
            "status": f"Evaluation failed: {str(e)}",
        }
