"""Orchestrate endpoint - coordinate job scoring and evaluation."""

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agents import AgentFactory, get_agent_factory
from src.api.dependencies import get_current_user, get_db
from src.api.schemas import (
    OrchestrateRequest,
    OrchestrateResponse,
    OrchestrateJobResult,
)
from src.api.vectordb_async import get_cv_context_async
from src.config.settings import config
from src.db import User
from src.schema.state import AgenticHireState, JobOffer
from src.schema.validation import ValidationFailureReason, RejectedJob

router = APIRouter(prefix="/api", tags=["orchestration"])

# Per-job validation timeout
_PER_JOB_VALIDATION_TIMEOUT_S: float = config.validator_timeout + 15


async def _validate_single_job(
    job: JobOffer,
) -> tuple[JobOffer | None, dict[str, Any] | None]:
    """Validate one job with timeout. Returns (job, None) on success or (None, error_dict) on failure."""
    factory = get_agent_factory()
    try:
        result = await asyncio.wait_for(
            factory.job_validator.validate_job_with_reason(job),
            timeout=_PER_JOB_VALIDATION_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Validation timeout for job {job.id}")
        return None, {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "reason": "Validation timeout",
        }

    if result.is_valid:
        return job, None

    logger.debug(f"Job {job.id} validation failed: {result.reason_text}")
    return None, {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "reason": result.reason_text,
    }


@router.post("/orchestrate")
async def orchestrate(
    request: OrchestrateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OrchestrateResponse:
    """Orchestrate job search, validation, scoring, and evaluation.

    Coordinates Orchestrator + Tailor agents to provide comprehensive
    job matching against user's CV with personalized evaluations.

    Accepts either search criteria (for Scout to find jobs) or pre-found jobs
    (to skip Scout/Validate), or both. Returns all jobs with match scores
    and evaluations for high-scoring jobs.

    Args:
        request: OrchestrateRequest with criteria and/or jobs list
        user: Authenticated user from JWT
        session: Database session for persistence

    Returns:
        OrchestrateResponse with all_jobs, shortlisted_jobs, rejected_jobs
    """
    logger.info(
        f"POST /orchestrate requested by {user.email} with "
        f"criteria={'yes' if request.criteria else 'no'}, "
        f"jobs={len(request.jobs) if request.jobs else 0}"
    )

    # Validate input
    if not request.criteria and not request.jobs:
        logger.warning("Orchestrate called with neither criteria nor jobs")
        return OrchestrateResponse(
            all_jobs=[],
            shortlisted_jobs=[],
            rejected_jobs=[],
            status="Error: provide either criteria or jobs",
            error_count=1,
        )

    try:
        # Validate user identity
        if not user.id or not isinstance(user.id, UUID):
            logger.error(f"Invalid user identity for {user.email}")
            raise HTTPException(status_code=401, detail="Invalid user identity")

        # Initialize factory with user_id for user-scoped CV context
        logger.debug(f"Initializing AgentFactory for user {user.id}")
        factory = AgentFactory(user_id=user.id)

        # Retrieve CV context from pgvector
        cv_context = ""
        try:
            logger.debug(f"Retrieving CV context for user {user.id}")
            query = request.criteria if request.criteria else "job requirements"
            cv_context = await get_cv_context_async(factory.vector_manager, query)
            logger.debug(f"CV context retrieved: {len(cv_context)} characters")
        except KeyError as e:
            logger.warning(
                f"CV not found for user {user.id}: {e}",
            )
            cv_context = ""
        except Exception as e:
            logger.error(
                f"CV context retrieval failed: {type(e).__name__}: {repr(e)}",
                exc_info=True,
            )
            cv_context = ""

        # Initialize state
        state: AgenticHireState = {
            "resume_context": cv_context,
            "target_criteria": request.criteria or "",
            "found_jobs": [],
            "valid_jobs": [],
            "shortlisted_jobs": [],
            "rejected_jobs": [],
            "applications": {},
            "status": "Starting orchestration...",
            "max_offers": len(request.jobs) if request.jobs else 10,
            "scout_runs": 0,
            "search_queries": [],
            "seen_jobs": [],
        }

        # Determine workflow: use provided jobs or run scout
        valid_jobs = []
        jobs_rejected_by_validator = []
        if request.jobs:
            logger.info(
                f"Using {len(request.jobs)} provided jobs, skipping scout and validation"
            )
            valid_jobs = request.jobs
        elif request.criteria:
            logger.info(f"Running scout with criteria: {request.criteria}")
            state["target_criteria"] = request.criteria
            try:
                scout_result = await factory.scout(state, cv_context=cv_context)
                found_jobs = scout_result.get("found_jobs", [])
                logger.info(f"Scout found {len(found_jobs)} jobs")

                # Validate jobs: check for dead links and expired postings
                logger.info(f"Validating {len(found_jobs)} jobs")
                for job in found_jobs:
                    valid, error = await _validate_single_job(job)
                    if valid is not None:
                        valid_jobs.append(valid)
                    elif error is not None:
                        jobs_rejected_by_validator.append(error)

                logger.info(
                    f"Validation complete: {len(valid_jobs)} valid, "
                    f"{len(jobs_rejected_by_validator)} rejected"
                )

            except Exception as e:
                logger.error(
                    f"Scout failed: {type(e).__name__}: {repr(e)}",
                    exc_info=True,
                )
                return OrchestrateResponse(
                    all_jobs=[],
                    shortlisted_jobs=[],
                    rejected_jobs=[],
                    status=f"Scout failed: {str(e)}",
                    error_count=1,
                )
        else:
            # Should not reach here due to initial validation
            return OrchestrateResponse(
                all_jobs=[],
                shortlisted_jobs=[],
                rejected_jobs=[],
                status="No input provided",
                error_count=1,
            )

        if not valid_jobs:
            logger.warning("No valid jobs to orchestrate")
            return OrchestrateResponse(
                all_jobs=[],
                shortlisted_jobs=[],
                rejected_jobs=[],
                status="No valid jobs found",
                error_count=0,
            )

        # Run orchestrator to score jobs
        logger.info(f"Running orchestrator on {len(valid_jobs)} jobs")
        state["valid_jobs"] = valid_jobs
        try:
            orchestrator_result = await factory.orchestrator(state)
            shortlisted_jobs = orchestrator_result.get("shortlisted_jobs", [])
            rejected_by_orchestrator = orchestrator_result.get("rejected_jobs", [])
            logger.info(
                f"Orchestrator shortlisted {len(shortlisted_jobs)} jobs, "
                f"rejected {len(rejected_by_orchestrator)}"
            )
        except Exception as e:
            logger.error(
                f"Orchestrator failed: {type(e).__name__}: {repr(e)}",
                exc_info=True,
            )
            return OrchestrateResponse(
                all_jobs=[],
                shortlisted_jobs=[],
                rejected_jobs=[
                    OrchestrateJobResult(
                        id=job.id,
                        title=job.title,
                        company=job.company,
                        url=job.url,
                        match_score=0.0,
                        analysis=None,
                        evaluation=None,
                        error=f"Orchestrator failed: {str(e)}",
                    )
                    for job in valid_jobs
                ],
                status=f"Orchestrator failed: {str(e)}",
                error_count=len(valid_jobs),
            )

        # Generate evaluations for shortlisted jobs
        error_count = 0
        all_job_results = []
        shortlisted_results = []

        logger.info(
            f"Generating evaluations for {len(shortlisted_jobs)} shortlisted jobs"
        )
        for job in shortlisted_jobs:
            try:
                logger.debug(f"Generating evaluation for job {job.id}")
                tailor_state: AgenticHireState = {
                    "shortlisted_jobs": [job],
                    "applications": {},
                    "resume_context": cv_context,
                    "target_criteria": request.criteria or "",
                    "found_jobs": [job],
                    "valid_jobs": [job],
                    "rejected_jobs": [],
                    "status": "Generating evaluation...",
                    "max_offers": 1,
                    "scout_runs": 0,
                    "search_queries": [],
                    "seen_jobs": [job.url],
                }

                tailor_result = await asyncio.wait_for(
                    factory.tailor(tailor_state), timeout=30
                )
                applications = tailor_result.get("applications", {})
                evaluation_data = applications.get(job.id, {})
                evaluation = evaluation_data.get("founded_job_offer", "")

                job_result = OrchestrateJobResult(
                    id=job.id,
                    title=job.title,
                    company=job.company,
                    url=job.url,
                    match_score=job.match_score,
                    analysis=job.analysis,
                    evaluation=evaluation,
                    error=None,
                )
                all_job_results.append(job_result)
                shortlisted_results.append(job_result)
                logger.debug(f"Evaluation generated for job {job.id}")

            except asyncio.TimeoutError:
                logger.warning(f"Tailor timeout for job {job.id}")
                error_count += 1
                job_result = OrchestrateJobResult(
                    id=job.id,
                    title=job.title,
                    company=job.company,
                    url=job.url,
                    match_score=job.match_score,
                    analysis=job.analysis,
                    evaluation=None,
                    error="Tailor evaluation timeout",
                )
                all_job_results.append(job_result)
                shortlisted_results.append(job_result)

            except Exception as e:
                logger.error(
                    f"Tailor failed for job {job.id}: {type(e).__name__}: {repr(e)}",
                    exc_info=True,
                )
                error_count += 1
                job_result = OrchestrateJobResult(
                    id=job.id,
                    title=job.title,
                    company=job.company,
                    url=job.url,
                    match_score=job.match_score,
                    analysis=job.analysis,
                    evaluation=None,
                    error=f"Tailor failed: {str(e)}",
                )
                all_job_results.append(job_result)
                shortlisted_results.append(job_result)

        # Add rejected jobs to all_job_results (orchestrator rejections)
        for job in rejected_by_orchestrator:
            job_result = OrchestrateJobResult(
                id=job.id,
                title=job.title,
                company=job.company,
                url=job.url,
                match_score=job.match_score if hasattr(job, "match_score") else 0.0,
                analysis=job.analysis if hasattr(job, "analysis") else None,
                evaluation=None,
                error=None,
            )
            all_job_results.append(job_result)

        # Add validation rejections to all_job_results
        for rejected in jobs_rejected_by_validator:
            job_result = OrchestrateJobResult(
                id=rejected["id"],
                title=rejected["title"],
                company=rejected["company"],
                url=rejected["url"],
                match_score=0.0,
                analysis=None,
                evaluation=None,
                error=f"Validation failed: {rejected['reason']}",
            )
            all_job_results.append(job_result)

        # Filter shortlisted by score threshold
        final_shortlisted = [
            job
            for job in shortlisted_results
            if job.match_score >= request.score_threshold
        ]

        # Filter rejected: below threshold or had errors (including validation rejections)
        final_rejected = [
            job
            for job in all_job_results
            if job.match_score < request.score_threshold or job.error is not None
        ]

        status = (
            f"Orchestration complete: {len(final_shortlisted)} shortlisted, "
            f"{len(final_rejected)} below threshold, {error_count} evaluation errors"
        )
        logger.info(status)

        return OrchestrateResponse(
            all_jobs=all_job_results,
            shortlisted_jobs=final_shortlisted,
            rejected_jobs=final_rejected,
            status=status,
            error_count=error_count,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Unexpected error in orchestrate: {type(e).__name__}: {repr(e)}",
            exc_info=True,
        )
        return OrchestrateResponse(
            all_jobs=[],
            shortlisted_jobs=[],
            rejected_jobs=[],
            status=f"Orchestration failed: {str(e)}",
            error_count=1,
        )
