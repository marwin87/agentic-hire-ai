"""Workflow endpoints - primary orchestration API."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agents import AgentFactory
from src.api.dependencies import get_current_user, get_db
from src.api.schemas import (
    OrchestrateJobResult,
    OrchestrateRequest,
    OrchestrateResponse,
    WorkflowStreamEvent,
)
from src.api.vectordb_async import get_cv_context_async
from src.db import EvaluationRepository, Job, JobRepository, User
from src.graph import build_graph
from src.schema.state import AgenticHireState
from src.utils.progress import set_progress_queue

router = APIRouter(prefix="/api", tags=["workflows"])


@router.post("/workflows/search-jobs")
async def search_jobs_workflow(
    request: OrchestrateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OrchestrateResponse:
    """Orchestrate job search, validation, scoring, and evaluation via LangGraph.

    Accepts either search criteria (triggers Scout) or pre-found jobs (skips Scout).
    Returns all jobs with match scores, shortlisted jobs with evaluations, and rejected jobs.

    Args:
        request: OrchestrateRequest with criteria and/or jobs list
        user: Authenticated user from JWT
        session: Database session for persistence

    Returns:
        OrchestrateResponse with all_jobs, shortlisted_jobs, rejected_jobs
    """
    logger.info(
        f"POST /workflows/search-jobs requested by {user.email} with "
        f"criteria={'yes' if request.criteria else 'no'}, "
        f"jobs={len(request.jobs) if request.jobs else 0}"
    )

    # Validate input
    if not request.criteria and not request.jobs:
        logger.warning("Workflow called with neither criteria nor jobs")
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
        except KeyError:
            logger.warning(f"CV not found for user {user.id}")
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
            "score_threshold": request.score_threshold,
        }

        # Determine workflow: use provided jobs or run graph
        if request.jobs:
            logger.info(
                f"Using {len(request.jobs)} provided jobs, invoking graph starting at orchestrator"
            )
            state["valid_jobs"] = request.jobs
        elif request.criteria:
            logger.info(f"Running graph with criteria: {request.criteria}")
            state["target_criteria"] = request.criteria
        else:
            # Should not reach here due to initial validation
            return OrchestrateResponse(
                all_jobs=[],
                shortlisted_jobs=[],
                rejected_jobs=[],
                status="No input provided",
                error_count=1,
            )

        # Invoke the graph
        try:
            logger.info("[ORCHESTRATOR] Invoking LangGraph workflow")
            graph = build_graph()
            result = await graph.ainvoke(state)
            logger.info("[ORCHESTRATOR] Graph execution complete")
        except Exception as e:
            logger.error(
                f"Graph execution failed: {type(e).__name__}: {repr(e)}",
                exc_info=True,
            )
            return OrchestrateResponse(
                all_jobs=[],
                shortlisted_jobs=[],
                rejected_jobs=[],
                status=f"Graph execution failed: {str(e)}",
                error_count=1,
            )

        # Extract results from graph state
        shortlisted_jobs = result.get("shortlisted_jobs", [])
        rejected_jobs = result.get("rejected_jobs", [])
        all_jobs = result.get("valid_jobs", [])
        applications = result.get("applications", {})

        logger.info(
            f"Graph results: {len(shortlisted_jobs)} shortlisted, {len(rejected_jobs)} rejected"
        )

        # Persist jobs and evaluations
        try:
            # Jobs must be written before evaluations (FK constraint)
            for job in all_jobs:
                job_db = Job(
                    id=job.id,
                    user_id=user.id,
                    title=job.title,
                    company=job.company,
                    description=job.description,
                    url=job.url,
                    salary_range=job.salary_range,
                )
                await JobRepository.create_or_update(session, job_db)
            for job in shortlisted_jobs:
                eval_data = applications.get(job.id, {})
                tailor_summary = eval_data.get("founded_job_offer") or None
                await EvaluationRepository.upsert(
                    session,
                    user_id=user.id,
                    job_id=job.id,
                    match_score=job.match_score,
                    orchestrator_reasoning=job.analysis or None,
                    tailor_summary=tailor_summary,
                )
            await session.commit()
            logger.info(
                f"[ORCHESTRATOR] Persisted {len(all_jobs)} jobs, "
                f"{len(shortlisted_jobs)} evaluations"
            )
        except Exception as e:
            await session.rollback()
            logger.error(
                f"Persistence failed (non-critical): {type(e).__name__}: {repr(e)}",
                exc_info=True,
            )

        # Build response: aggregate all jobs with results
        all_job_results = []
        shortlisted_results = []

        # Process shortlisted jobs (should have evaluations from tailor)
        for job in shortlisted_jobs:
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

        # Process rejected jobs (below threshold)
        for job in rejected_jobs:
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

        # Filter shortlisted by score threshold
        final_shortlisted = [
            job
            for job in shortlisted_results
            if job.match_score >= request.score_threshold
        ]

        # Filter rejected: below threshold
        final_rejected = [
            job for job in all_job_results if job.match_score < request.score_threshold
        ]

        status = (
            f"Workflow complete: {len(final_shortlisted)} shortlisted, "
            f"{len(final_rejected)} below threshold"
        )
        logger.info(status)

        return OrchestrateResponse(
            all_jobs=all_job_results,
            shortlisted_jobs=final_shortlisted,
            rejected_jobs=final_rejected,
            status=status,
            error_count=0,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Unexpected error in workflow: {type(e).__name__}: {repr(e)}",
            exc_info=True,
        )
        return OrchestrateResponse(
            all_jobs=[],
            shortlisted_jobs=[],
            rejected_jobs=[],
            status=f"Workflow failed: {str(e)}",
            error_count=1,
        )


def _extract_node_summary(
    node_name: str, node_update: dict[str, Any]
) -> dict[str, Any]:
    """Extract a human-readable summary dict from a LangGraph node update."""
    if node_name == "scout":
        return {
            "jobs_found": len(node_update.get("found_jobs", [])),
            "scout_run": node_update.get("scout_runs", 0),
        }
    if node_name == "validate_jobs":
        return {
            "jobs_valid": len(node_update.get("valid_jobs", [])),
            "jobs_rejected": len(node_update.get("rejected_jobs", [])),
        }
    if node_name == "orchestrator":
        return {
            "jobs_shortlisted": len(node_update.get("shortlisted_jobs", [])),
        }
    if node_name == "tailor":
        return {
            "evaluations": len(node_update.get("applications", {})),
        }
    return {}


@router.post("/workflows/search-jobs/stream")
async def search_jobs_stream(
    request: OrchestrateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream LangGraph workflow progress as Server-Sent Events.

    Emits one WorkflowStreamEvent per node completion, followed by a final
    'workflow' event carrying the complete OrchestrateResponse. Each event is
    formatted as an SSE 'data:' line.

    Args:
        request: OrchestrateRequest with criteria and/or jobs list
        user: Authenticated user from JWT
        session: Database session for persistence

    Returns:
        StreamingResponse with text/event-stream content type
    """
    logger.info(
        f"POST /workflows/search-jobs/stream requested by {user.email} with "
        f"criteria={'yes' if request.criteria else 'no'}, "
        f"jobs={len(request.jobs) if request.jobs else 0}"
    )

    if not request.criteria and not request.jobs:
        raise HTTPException(
            status_code=422,
            detail="Provide either criteria or jobs",
        )

    if not user.id or not isinstance(user.id, UUID):
        raise HTTPException(status_code=401, detail="Invalid user identity")

    # Build CV context and initial state before entering the generator so
    # HTTP-layer errors (auth, bad input) surface as proper HTTP responses
    # rather than as SSE error events the client may not detect.
    factory = AgentFactory(user_id=user.id)
    cv_context = ""
    try:
        query = request.criteria if request.criteria else "job requirements"
        cv_context = await get_cv_context_async(factory.vector_manager, query)
        logger.debug(f"CV context retrieved: {len(cv_context)} characters")
    except KeyError:
        logger.warning(
            f"CV not found for user {user.id}; continuing without CV context"
        )
    except Exception as e:
        # CV retrieval failure is recoverable — log and continue with empty context
        logger.error(
            f"CV context retrieval failed (non-critical): {type(e).__name__}: {repr(e)}",
            exc_info=True,
        )

    initial_state: AgenticHireState = {
        "user_id": user.id,
        "resume_context": cv_context,
        "target_criteria": request.criteria or "",
        "found_jobs": [],
        "valid_jobs": request.jobs or [],
        "shortlisted_jobs": [],
        "rejected_jobs": [],
        "applications": {},
        "status": "Starting streaming orchestration...",
        "max_offers": len(request.jobs) if request.jobs else 10,
        "scout_runs": 0,
        "search_queries": [],
        "seen_jobs": [],
        "score_threshold": request.score_threshold,
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        # Single queue receives both progress log events (from agents via emit())
        # and node-completion events (pushed by run_graph below).
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        set_progress_queue(q)

        # Accumulators — mutated inside run_graph via the shared dict.
        acc: dict[str, Any] = {
            "found_jobs": [],
            "rejected_jobs": [],
            "valid_jobs": [],
            "shortlisted_jobs": [],
            "applications": {},
        }

        async def run_graph() -> None:
            try:
                graph = build_graph()
                logger.info("[STREAM] Starting graph.astream()")
                async for event in graph.astream(initial_state, stream_mode="updates"):
                    for node_name, node_update in event.items():
                        logger.info(f"[STREAM] Node complete: {node_name}")
                        if node_name == "scout":
                            acc["found_jobs"] += node_update.get("found_jobs", [])
                        elif node_name == "validate_jobs":
                            acc["valid_jobs"] = node_update.get("valid_jobs", [])
                            acc["rejected_jobs"] += node_update.get("rejected_jobs", [])
                        elif node_name == "orchestrator":
                            acc["shortlisted_jobs"] = node_update.get(
                                "shortlisted_jobs", []
                            )
                            acc["rejected_jobs"] += node_update.get("rejected_jobs", [])
                        elif node_name == "tailor":
                            acc["applications"] = node_update.get("applications", {})
                        summary = _extract_node_summary(node_name, node_update)
                        await q.put(
                            {
                                "type": "node_complete",
                                "node": node_name,
                                "data": summary,
                            }
                        )

                logger.info("[STREAM] Graph complete; building final response")

                # Persist jobs and evaluations (session from outer scope)
                try:
                    # Jobs must be written before evaluations (FK constraint)
                    for job in acc["valid_jobs"]:
                        job_db = Job(
                            id=job.id,
                            user_id=user.id,
                            title=job.title,
                            company=job.company,
                            description=job.description,
                            url=job.url,
                            salary_range=job.salary_range,
                        )
                        await JobRepository.create_or_update(session, job_db)
                    for job in acc["shortlisted_jobs"]:
                        eval_data = acc["applications"].get(job.id, {})
                        tailor_summary = eval_data.get("founded_job_offer") or None
                        await EvaluationRepository.upsert(
                            session,
                            user_id=user.id,
                            job_id=job.id,
                            match_score=job.match_score,
                            orchestrator_reasoning=job.analysis or None,
                            tailor_summary=tailor_summary,
                        )
                    await session.commit()
                    logger.info(
                        f"[STREAM] Persisted {len(acc['valid_jobs'])} jobs, "
                        f"{len(acc['shortlisted_jobs'])} evaluations"
                    )
                except Exception as e:
                    await session.rollback()
                    logger.error(
                        f"[STREAM] Persistence failed (non-critical): {type(e).__name__}: {repr(e)}",
                        exc_info=True,
                    )

                shortlisted_results: list[OrchestrateJobResult] = []
                all_job_results: list[OrchestrateJobResult] = []
                for job in acc["shortlisted_jobs"]:
                    eval_data = acc["applications"].get(job.id, {})
                    result = OrchestrateJobResult(
                        id=job.id,
                        title=job.title,
                        company=job.company,
                        url=job.url,
                        match_score=job.match_score,
                        analysis=job.analysis,
                        evaluation=eval_data.get("founded_job_offer", ""),
                        error=None,
                    )
                    all_job_results.append(result)
                    shortlisted_results.append(result)
                for job in acc["rejected_jobs"]:
                    score = getattr(job, "match_score", 0.0)
                    # Skip validation-rejected jobs (score == 0.0, never actually scored)
                    # so they don't appear as "0% match" cards in the UI.
                    if score == 0.0:
                        continue
                    all_job_results.append(
                        OrchestrateJobResult(
                            id=job.id,
                            title=job.title,
                            company=job.company,
                            url=job.url,
                            match_score=score,
                            analysis=getattr(job, "analysis", None),
                            evaluation=None,
                            error=None,
                        )
                    )
                final_shortlisted = [
                    j
                    for j in shortlisted_results
                    if j.match_score >= request.score_threshold
                ]
                final_rejected = [
                    j
                    for j in all_job_results
                    if j.match_score < request.score_threshold
                ]
                final_response = OrchestrateResponse(
                    all_jobs=all_job_results,
                    shortlisted_jobs=final_shortlisted,
                    rejected_jobs=final_rejected,
                    status=f"Workflow complete: {len(final_shortlisted)} shortlisted, {len(final_rejected)} below threshold",
                    error_count=0,
                )
                await q.put(
                    {"type": "workflow_complete", "data": final_response.model_dump()}
                )
            except Exception as e:
                logger.error(
                    f"[STREAM] Graph failed: {type(e).__name__}: {repr(e)}",
                    exc_info=True,
                )
                await q.put(
                    {"type": "error", "node": "workflow", "data": {"message": str(e)}}
                )
            finally:
                await q.put(None)  # sentinel — signals generator to stop

        task = asyncio.create_task(run_graph())

        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                item_type = item.get("type", "log")
                node = item.get("node", "workflow")
                data = item.get("data", {})

                if item_type == "log":
                    status = "log"
                elif item_type == "node_complete":
                    status = "complete"
                elif item_type == "workflow_complete":
                    node = "workflow"
                    status = "complete"
                elif item_type == "error":
                    status = "error"
                else:
                    continue

                yield f"data: {WorkflowStreamEvent(node=node, status=status, data=data).model_dump_json()}\n\n"
        finally:
            if not task.done():
                task.cancel()
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
