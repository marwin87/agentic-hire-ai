"""Scout agent endpoint - search for jobs."""

import asyncio
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agents import AgentFactory
from src.api.dependencies import get_current_user, get_db
from src.api.schemas import SearchJobsRequest
from src.api.vectordb_async import get_cv_context_async
from src.config.settings import config
from src.db import User, JobRepository, SearchSessionRepository, Job
from src.schema.state import AgenticHireState

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/scout")
async def scout_search(
    request: SearchJobsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Search for jobs using Scout agent with user's CV context.

    Authenticates user, retrieves CV from pgvector, invokes Scout agent,
    and stores results in database scoped to user_id.

    Args:
        request: SearchJobsRequest with criteria and optional max_results
        user: Authenticated user from JWT token
        session: Database session for persistence

    Returns:
        Dictionary with search_id, found_jobs array, search metadata, and status
    """
    logger.info(
        f"POST /scout requested by {user.email} with criteria: {request.criteria}"
    )

    search_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        # Initialize AgentFactory with user_id for user-scoped embeddings
        if not user.id or not isinstance(user.id, UUID):
            raise HTTPException(status_code=401, detail="Invalid user identity")

        logger.debug(f"[SCOUT] Initializing AgentFactory for user {user.id}")
        factory = AgentFactory(user_id=user.id)
        logger.debug(f"[SCOUT] AgentFactory initialized successfully")

        # Retrieve CV context asynchronously from pgvector
        cv_context = ""
        cv_warning = ""
        try:
            logger.debug(f"[SCOUT] Retrieving CV context for user {user.id}")
            cv_context = await get_cv_context_async(
                factory.vector_manager, request.criteria
            )
            logger.debug(f"[SCOUT] CV context retrieved: {len(cv_context)} characters")
            if not cv_context:
                cv_warning = "CV not uploaded; results based on criteria only"
                logger.warning(f"No CV found for user {user.id}")
        except Exception as e:
            logger.error(
                f"CV context retrieval failed for user {user.id}: {type(e).__name__}: {repr(e)}",
                exc_info=True,
            )
            cv_context = ""
            cv_warning = "CV context unavailable; results based on criteria only"

        # Build state for Scout agent
        logger.debug("[SCOUT] Building AgenticHireState")
        state: AgenticHireState = {
            "resume_context": cv_context,
            "target_criteria": request.criteria,
            "found_jobs": [],
            "valid_jobs": [],
            "shortlisted_jobs": [],
            "applications": {},
            "status": "Starting scout agent...",
            "max_offers": request.max_results or 10,
            "scout_runs": 0,
            "rejected_jobs": [],
            "seen_jobs": [],
        }
        logger.debug("[SCOUT] State built successfully")

        # Invoke Scout agent with pre-fetched CV context
        logger.info(f"Invoking Scout agent for user {user.email}")
        result = await factory.scout(state, cv_context=cv_context)

        # Extract results
        found_jobs = result.get("found_jobs", [])
        agent_status = result.get("status", "Search complete")

        logger.info(f"Scout agent found {len(found_jobs)} jobs for user {user.email}")

        # Persist found jobs to database, scoped to user_id
        for job_offer in found_jobs:
            # Convert JobOffer (Pydantic) to Job (ORM) with user_id
            job_db = Job(
                id=job_offer.id,
                user_id=user.id,
                title=job_offer.title,
                company=job_offer.company,
                description=job_offer.description,
                url=job_offer.url,
                salary_range=job_offer.salary_range,
            )
            assert (
                job_db.user_id == user.id
            ), f"Job user_id mismatch: {job_db.user_id} != {user.id}"
            await JobRepository.create_or_update(session, job_db)

        # Log search session
        await SearchSessionRepository.create(
            session,
            user_id=cast(UUID, user.id),
            criteria=request.criteria,
            found_count=len(found_jobs),
        )

        # Commit database changes
        try:
            async with asyncio.timeout(10):
                await session.commit()
        except asyncio.TimeoutError:
            logger.error(f"Database commit timeout for user {user.id}")
            await session.rollback()
            raise HTTPException(status_code=503, detail="Database timeout")
        logger.debug(f"Persisted {len(found_jobs)} jobs for user {user.id}")

        # Build response with search metadata
        status_message = cv_warning if cv_warning else agent_status

        return {
            "search_id": search_id,
            "found_jobs": [
                {
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "url": job.url,
                    "description": job.description,
                    "salary_range": job.salary_range,
                }
                for job in found_jobs
            ],
            "criteria": request.criteria,
            "count": len(found_jobs),
            "timestamp": timestamp,
            "status": status_message,
        }

    except Exception as e:
        logger.error("Error in scout_search endpoint", exc_info=True)
        await session.rollback()

        # Return graceful error response (200 with empty results + detail)
        detail = "Search failed due to an internal error"
        if config.debug_mode:
            try:
                detail = f"Search failed: {type(e).__name__}"
            except Exception:
                detail = "Search failed: unknown error"

        return {
            "search_id": search_id,
            "found_jobs": [],
            "criteria": request.criteria,
            "count": 0,
            "timestamp": timestamp,
            "status": detail,
        }
