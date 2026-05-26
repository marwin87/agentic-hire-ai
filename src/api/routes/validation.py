"""Validation endpoint - filter invalid and expired jobs."""

import asyncio

from fastapi import APIRouter, Depends
from loguru import logger

from src.api.dependencies import get_current_user
from src.api.schemas import ValidateJobsRequest
from src.agents.agents import get_agent_factory
from src.config.settings import config
from src.db import User
from src.schema.state import JobOffer
from src.schema.validation import (
    RejectedJob,
    ValidationFailureReason,
    ValidateJobsResponse,
)

router = APIRouter(prefix="/api", tags=["validation"])

# Total per-job timeout: HTTP timeout + buffer for LLM retry loop
_PER_JOB_TIMEOUT_S: float = config.validator_timeout + 15


async def _validate_single_job(
    job: JobOffer,
) -> tuple[JobOffer | None, RejectedJob | None]:
    """Validate one job with a total-per-job timeout.

    Returns (job, None) on success, (None, rejected_job) on failure.
    asyncio.TimeoutError is caught here and mapped to VALIDATION_TIMEOUT.
    """
    factory = get_agent_factory()
    try:
        result = await asyncio.wait_for(
            factory.job_validator.validate_job_with_reason(job),
            timeout=_PER_JOB_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return None, RejectedJob(
            id=job.id,
            title=job.title,
            company=job.company,
            url=job.url,
            description=job.description,
            salary_range=job.salary_range,
            reason_code=ValidationFailureReason.VALIDATION_TIMEOUT,
            reason_text=f"Validation exceeded total timeout of {_PER_JOB_TIMEOUT_S:.0f}s",
            validation_duration_ms=int(_PER_JOB_TIMEOUT_S * 1000),
        )

    if result.is_valid:
        return job, None

    return None, RejectedJob(
        id=job.id,
        title=job.title,
        company=job.company,
        url=job.url,
        description=job.description,
        salary_range=job.salary_range,
        reason_code=result.reason_code or ValidationFailureReason.HTTP_ERROR,
        reason_text=result.reason_text,
        validation_duration_ms=result.duration_ms,
    )


@router.post("/validate_jobs", response_model=ValidateJobsResponse)
async def validate_jobs(
    request: ValidateJobsRequest,
    user: User = Depends(get_current_user),
) -> ValidateJobsResponse:
    """Validate jobs from Scout — remove dead links and expired postings.

    Accepts a list of JobOffer objects found by the Scout agent and validates each by:
    - Checking URL format (rejects URL_INVALID)
    - Making an HTTP GET request to the job page (rejects HTTP_ERROR on 4xx/5xx)
    - Using an LLM to detect expired/closed postings (rejects JOB_EXPIRED)
    - Enforcing a per-job timeout (rejects VALIDATION_TIMEOUT if exceeded)

    Always returns HTTP 200. Rejection reasons are in the `rejected_jobs` list.
    Partial results are returned if some jobs time out — other jobs still complete.

    Args:
        request: List of jobs to validate (from Scout agent output)
        user: Authenticated user from JWT token

    Returns:
        ValidateJobsResponse with valid_jobs and rejected_jobs (with reason codes)
    """
    logger.info(
        f"POST /validate_jobs — {len(request.jobs)} jobs received from {user.email}"
    )

    valid_jobs: list[JobOffer] = []
    rejected_jobs: list[RejectedJob] = []

    for job in request.jobs:
        valid, rejected = await _validate_single_job(job)
        if valid is not None:
            valid_jobs.append(valid)
        elif rejected is not None:
            rejected_jobs.append(rejected)

    logger.info(
        f"Validated {len(request.jobs)} jobs for {user.email}: "
        f"{len(valid_jobs)} passed, {len(rejected_jobs)} rejected"
    )

    return ValidateJobsResponse(valid_jobs=valid_jobs, rejected_jobs=rejected_jobs)
