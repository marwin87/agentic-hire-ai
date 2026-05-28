"""Job listing endpoints - retrieve user's discovered and evaluated jobs."""

import math
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas import GetJobsResponse, JobListItemResponse
from src.db import User
from src.db.repositories import JobRepository

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def get_jobs(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        10, ge=1, le=50, description="Items per page (1-50, default 10)"
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> GetJobsResponse:
    """Retrieve paginated list of user's discovered jobs.

    Returns the authenticated user's job listings with optional match scores
    from the orchestrator (if jobs have been evaluated). Results are sorted
    by discovery date (newest first). Invalid pagination parameters are
    clamped to valid ranges. User can only see their own jobs (enforced by
    JWT authentication and database user_id filtering).

    Returns:
        GetJobsResponse: Paginated jobs with pagination metadata and optional match scores.
    """
    logger.info(
        f"GET /jobs requested by {user.email} (page={page}, page_size={page_size})"
    )

    user_id = cast(UUID, user.id)

    # Fetch jobs and pagination metadata with error handling
    try:
        # Get total count for pagination
        total_count = await JobRepository.count_by_user(session, user_id)

        # Clamp page to valid range: [1, ceil(total_count / page_size)]
        if total_count > 0:
            max_page = math.ceil(total_count / page_size)
            clamped_page = min(max(page, 1), max_page)
        else:
            clamped_page = 1

        # Calculate offset
        offset = (clamped_page - 1) * page_size

        # Fetch jobs with optional scores
        job_score_tuples = await JobRepository.get_jobs_with_scores(
            session, user_id, limit=page_size, offset=offset
        )
    except Exception as e:
        logger.error(
            f"Database error in GET /jobs: {type(e).__name__}: {repr(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="Job service temporarily unavailable"
        )

    # Build response
    jobs_list: list[JobListItemResponse] = [
        JobListItemResponse(
            id=cast(str, job.id),
            title=cast(str, job.title),
            company=cast(str, job.company),
            url=cast(str, job.url),
            match_score=score,
        )
        for job, score in job_score_tuples
    ]

    logger.info(
        f"GET /jobs returning page {clamped_page} with {len(jobs_list)} jobs for {user.email}"
    )

    return GetJobsResponse(
        page=clamped_page, total_count=total_count, page_size=page_size, jobs=jobs_list
    )


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a single job owned by the authenticated user."""
    user_id = cast(UUID, user.id)
    deleted = await JobRepository.delete_by_id(session, job_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    await session.commit()
    logger.info(f"DELETE /jobs/{job_id} by {user.email}")


@router.delete("/jobs", status_code=200)
async def delete_all_jobs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Delete all jobs for the authenticated user."""
    user_id = cast(UUID, user.id)
    count = await JobRepository.delete_all_by_user(session, user_id)
    await session.commit()
    logger.info(f"DELETE /jobs (all) by {user.email}: {count} deleted")
    return {"deleted": count}
