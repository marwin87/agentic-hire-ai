"""Scoring endpoint - semantically match jobs to candidate CV."""

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from src.api.dependencies import get_factory, get_current_user
from src.api.schemas import ScoreJobsRequest
from src.db import User
from src.schema.state import AgenticHireState, JobOffer

router = APIRouter(prefix="/api", tags=["scoring"])


@router.post("/score_jobs")
async def score_jobs(
    request: ScoreJobsRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Score jobs based on semantic match to candidate CV.

    Uses RAG (Retrieval-Augmented Generation) to find relevant CV sections
    and LLM evaluation to score each job's relevance (0.0–1.0).
    Only shortlists jobs with score >= 0.6.

    Args:
        request: ScoreJobsRequest with list of jobs to score
        user: Authenticated user from JWT token

    Returns:
        Dictionary with shortlisted_jobs and scores
    """
    logger.info(f"POST /score_jobs requested by {user.email} with {len(request.jobs)} jobs")

    try:
        factory = get_factory()

        # Convert request job dicts to JobOffer objects
        valid_jobs = [JobOffer(**job) if isinstance(job, dict) else job for job in request.jobs]

        # Build state for orchestrator
        state: AgenticHireState = {
            "valid_jobs": valid_jobs,
            "shortlisted_jobs": [],
            "rejected_jobs": [],
            "max_offers": len(request.jobs),
            "scout_runs": 0,
            "status": "Starting job scoring...",
            "search_queries": [],
            "applications": {},
            "found_jobs": [],
            "resume_context": "Candidate CV context will be loaded from database in Phase 2",
            "target_criteria": "",
            "seen_jobs": [],
        }

        # Invoke Orchestrator agent
        logger.debug(f"Invoking Orchestrator with {len(request.jobs)} jobs")
        result = await factory.orchestrator(state)

        shortlisted_jobs = result.get("shortlisted_jobs", [])

        logger.info(f"Orchestrator shortlisted {len(shortlisted_jobs)} jobs")

        return {
            "shortlisted_jobs": [
                {
                    "id": job.id if hasattr(job, "id") else "",
                    "title": job.title if hasattr(job, "title") else "",
                    "company": job.company if hasattr(job, "company") else "",
                    "url": job.url if hasattr(job, "url") else "",
                    "match_score": job.match_score if hasattr(job, "match_score") else 0.0,
                    "analysis": job.analysis if hasattr(job, "analysis") else "",
                }
                for job in shortlisted_jobs
            ],
            "scores": {
                (job.id if hasattr(job, "id") else ""): (job.match_score if hasattr(job, "match_score") else 0.0)
                for job in shortlisted_jobs
            },
            "status": result.get("status", "Scoring complete"),
        }

    except Exception as e:
        logger.error(f"Error in score_jobs endpoint: {str(e)}", exc_info=e)
        return {
            "error": "scoring_failed",
            "detail": str(e),
            "code": "SCORING_ERROR",
            "shortlisted_jobs": [],
            "scores": {},
            "status": f"Scoring failed: {str(e)}",
        }
