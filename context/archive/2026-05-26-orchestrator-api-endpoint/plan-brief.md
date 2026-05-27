# Orchestrator API Endpoint — Plan Brief

> Full plan: `context/changes/orchestrator-api-endpoint/plan.md`

## What & Why

Build a unified `/api/orchestrate` endpoint that coordinates the job scoring and evaluation workflow in a single request. Currently, this workflow is split across four separate endpoints (scout → validate → score → evaluate), and the existing score endpoint has a critical bug: it doesn't pass the user's ID to the orchestrator, breaking CV context retrieval from the vector database. The unified orchestrate endpoint fixes this and provides a cleaner API for clients.

## Starting Point

The system already has:
- Separate endpoints for scout, validation, scoring, and evaluation
- A working Orchestrator agent that scores jobs using RAG + LLM matching
- A Tailor agent that generates personalized evaluations
- User authentication and database persistence
- Vector database (pgvector) with embedded CVs

The gap: no unified endpoint, and the existing `/api/score_jobs` doesn't properly load user CV context from pgvector, making scoring ineffective.

## Desired End State

A production-ready `/api/orchestrate` endpoint that:
- Accepts either search criteria (for Scout to find jobs) or pre-found jobs (to skip Scout), or both
- Runs the Orchestrator agent with proper user context to score jobs against the user's CV
- For high-scoring jobs (≥0.6), runs the Tailor agent to generate personalized evaluations
- Returns all jobs with match scores, reasoning, and (if shortlisted) evaluation text
- Handles errors gracefully: returns partial results with per-job error details

## Key Decisions Made

| Decision                          | Choice                                    | Why (1 sentence)                                        | Source |
| --------------------------------- | ----------------------------------------- | ------------------------------------------------------- | ------ |
| Endpoint scope                    | New unified `/api/orchestrate`            | Provides clean abstraction; existing separate endpoints stay unchanged | Plan   |
| Input flexibility                 | Accept criteria + jobs (either/both)      | Flexible: supports both "find new jobs" and "score pre-found jobs"    | Plan   |
| CV context handling               | Assume pre-loaded; separate upload API    | Simpler orchestrate endpoint; clear separation of concerns             | Plan   |
| Result detail                     | All jobs with scores + reasoning          | Maximum transparency; clients can filter, see why jobs were rejected   | Plan   |
| Tailor integration                | Score + evaluate shortlisted jobs         | Complete end-to-end result in one endpoint                            | Plan   |
| Skip scout/validate if jobs given | Yes                                       | Avoids redundant validation; reuses pre-found/validated jobs          | Plan   |
| Error handling strategy           | Partial success with per-job error details | Robust: maximizes useful output even if some jobs fail                 | Plan   |

## Scope

**In scope:** 
- New `/api/orchestrate` endpoint (scouts, validates, scores, evaluates in one call)
- OrchestrateRequest and OrchestrateResponse Pydantic schemas
- Proper user context (user_id) passed to orchestrator for CV retrieval
- Flexible input: criteria-only, jobs-only, or both
- Graceful error handling: partial success with per-job error tracking

**Out of scope:** 
- Modifying existing endpoints (`/scout`, `/validate_jobs`, `/score_jobs`, `/evaluate_job`)
- Handling CV upload/ingestion (separate `/api/upload_cv` handles that)
- Changing agent implementations (Orchestrator, Scout, Tailor work as-is)
- Async job queuing or long-running job handling
- Filtering/pagination (clients filter client-side)

## Architecture / Approach

The endpoint follows a sequential agent coordination pattern:

```
User request (criteria or jobs)
    ↓
AgentFactory(user_id) — ensures CV context retrieval
    ↓
Scout (if criteria provided) → find jobs
    ↓
Validator (if needed) → filter invalid jobs
    ↓
Orchestrator → score jobs using RAG + LLM
    ↓
Tailor (for shortlisted only) → generate evaluations
    ↓
Aggregate response (all jobs + scores + evaluations)
```

Key insight: Always instantiate AgentFactory with authenticated user_id, ensuring vector DB queries retrieve only that user's CV chunks. This fixes the bug in the existing `/api/score_jobs` endpoint.

## Phases at a Glance

| Phase | What it delivers                              | Key risk                                    |
| ----- | --------------------------------------------- | ------------------------------------------- |
| 1     | `/api/orchestrate` endpoint fully implemented | Tailor timeout on many shortlisted jobs; need per-job error handling |

**Prerequisites:** User has authenticated and uploaded CV to pgvector (existing `/api/upload_cv` handles this)
**Estimated effort:** ~1-2 sessions (endpoint + schemas + tests)

## Open Risks & Assumptions

- **Assumption**: User has CV already loaded in pgvector. If missing, orchestrator will have no context and scores will be poor. The endpoint should detect this and return clear error.
- **Risk**: If many jobs are shortlisted (score >= 0.6), calling Tailor for each one sequentially will be slow (~2-3s per job). Currently no async parallelization; future optimization can use asyncio.gather.
- **Risk**: Request timeout if orchestrator + tailor calls exceed client timeout (30s typical). Consider streaming results as future enhancement.

## Success Criteria (Summary)

- Endpoint is callable via authenticated HTTP POST with criteria or jobs input
- Orchestrator receives proper user_id and retrieves CV context from pgvector
- All jobs returned with match_score and reasoning
- Shortlisted jobs (score >= 0.6) include personalized evaluation text from Tailor
- Partial success: if tailor fails on one job, other jobs still returned in response
