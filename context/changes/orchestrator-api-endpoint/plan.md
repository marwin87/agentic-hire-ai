# Orchestrator API Endpoint Implementation Plan

## Overview

Create a new unified `/api/orchestrate` endpoint that coordinates the job scoring and evaluation workflow. This endpoint accepts either search criteria or pre-found jobs, runs the Orchestrator agent to score jobs against the user's CV using RAG, and generates tailored evaluations via the Tailor agent. The endpoint returns all jobs with match scores and reasoning, providing a complete end-to-end orchestration result in a single request.

## Current State Analysis

The system currently exposes the orchestration workflow as separate API endpoints:
- `POST /api/scout` — finds jobs via external search service
- `POST /api/validate_jobs` — filters invalid/expired jobs
- `POST /api/score_jobs` — scores jobs using Orchestrator agent
- `POST /api/evaluate_job/{job_id}` — generates evaluation via Tailor agent

**Key gap discovered**: The `/api/score_jobs` endpoint does not pass the authenticated user's ID to the orchestrator, breaking CV context retrieval from pgvector. Orchestrator receives a dummy resume_context string instead of actual user CV data, making scoring ineffective.

**Existing assets**:
- `AgentFactory` (src/agents/agents.py:13-91) — factory pattern for agent initialization, correctly injects user_id
- `OrchestratorAgent` (src/agents/orchestrator.py:17-110) — performs semantic job matching using RAG + LLM scoring
- `TailorAgent` (src/agents/tailor.py) — generates personalized evaluations
- Request/response schemas (src/api/schemas.py) — patterns for validation and error handling
- Endpoint patterns across `/src/api/routes/*.py` — consistent structure for auth, logging, error handling

## Desired End State

A production-ready `/api/orchestrate` endpoint that:
1. Accepts either `criteria` (for Scout to find jobs) or `jobs` (pre-found jobs), or both
2. If jobs are provided, skips Scout and Validate steps; if criteria provided, runs full discovery
3. Invokes Orchestrator with proper user context (authenticated user_id) to retrieve CV from pgvector and score jobs using RAG
4. For each job with score >= 0.6, invokes Tailor to generate a personalized evaluation
5. Returns comprehensive result: all jobs with match_score, analysis, and (if shortlisted) evaluation text
6. Handles errors gracefully: returns partial results with per-job error details instead of failing the entire request
7. Properly typed with Pydantic schemas, authenticated with JWT, logged with loguru

**Verification**: 
- Endpoint is callable via `curl -X POST http://localhost:8001/api/orchestrate -H "Authorization: Bearer {token}" -d {...}`
- Type checking passes: `mypy src/api/routes/orchestrate.py`
- Request/response schemas match Pydantic validation rules
- Unit tests mock agents and verify request → state → response flow
- Integration test calls endpoint with real authenticated user + pre-found jobs

### Key Discoveries:

- **User context is critical**: OrchestratorAgent requires `user_id` to retrieve correct CV from pgvector (agents.py:25, orchestrator.py:25-28)
- **Partial success pattern**: Validation endpoint (validation.py:41-66) uses `RejectedJob` with reason_code for granular error tracking; scoring should follow this
- **Agent state flow**: Each agent (scout → validator → orchestrator → tailor) takes state dict, modifies it, returns updated dict (patterns at search.py:78-97, scoring.py:46-64, evaluation.py:55-73)
- **Tailor output format**: Returns `applications: {job_id: {founded_job_offer, job_title, company}}` (tailor.py:94-97)
- **Error handling precedent**: Endpoints return 200 with error fields in response body rather than HTTP exceptions (scoring.py:93-102, evaluation.py:88-100)
- **Logging & instrumentation**: All endpoints log request, intermediate steps, and result using loguru (search.py:42-44, scoring.py:34-36)

## What We're NOT Doing

- **Not modifying existing endpoints** — `/api/scout`, `/api/validate_jobs`, `/api/score_jobs`, `/api/evaluate_job` remain unchanged
- **Not handling CV upload** — orchestrate endpoint assumes CV is pre-loaded in pgvector; separate `/api/upload_cv` handles ingestion
- **Not changing agent implementations** — Orchestrator, Scout, Tailor agents work as-is; we only coordinate them
- **Not implementing filtering/pagination** — all scores returned; clients can filter client-side if needed
- **Not handling async long-running jobs** — endpoint returns synchronously; if needed, future work can add job queuing

## Implementation Approach

**Single phase approach**:
1. Create `src/api/routes/orchestrate.py` following the established endpoint pattern (auth, logging, error handling)
2. Define `OrchestrateRequest` and `OrchestrateResponse` schemas in `src/api/schemas.py`
3. Implement the orchestrate handler:
   - Extract user_id from authenticated User object
   - Build AgentFactory(user_id=user.id) to ensure CV context retrieval works
   - If jobs provided, skip scout/validate and pass to orchestrator
   - If criteria provided, run scout first, then validate
   - Run orchestrator with populated state
   - For each shortlisted job (score >= 0.6), run tailor to generate evaluation
   - Aggregate results into response: all jobs with scores, shortlisted with evaluations
   - Handle errors gracefully: catch exceptions per job, include error details in response
4. Register route in `src/api/main.py` (line 125-130 where other routes are registered)
5. Add route to imports if needed

**Why single phase**: The orchestration is a straightforward sequencing of existing agents; no architectural decisions or data model changes block progress. Testing can happen once the implementation lands.

## Critical Implementation Details

**State building**:
The orchestrator requires CV context (`resume_context`) to be populated in state. Unlike the buggy `/api/score_jobs` which hardcodes a dummy string, we must:
1. Retrieve CV context from pgvector using `factory.vector_manager.get_context()` before invoking orchestrator
2. Pass this CV context in the state dict under `resume_context` key (state.py:45)

**User isolation**:
Always instantiate `AgentFactory(user_id=user.id)` where `user` is the authenticated User object from JWT. This ensures:
- CVVectorManager retrieves only that user's CV chunks
- Orchestrator scores jobs against the correct user's experience

**Partial success handling**:
When processing multiple jobs (scout finds many), if one job fails orchestration (e.g., tailor timeout), don't fail the entire response. Instead:
1. Catch exception per job in the tailor loop
2. Add error details to that job's response entry
3. Continue with remaining jobs
4. Return overall status indicating some jobs had errors

**Error codes to define**:
- `ORCHESTRATE_TIMEOUT` — orchestrator exceeded time limit
- `ORCHESTRATE_NO_CV` — user has no CV in pgvector
- `TAILOR_TIMEOUT` — tailor agent exceeded time limit (timeout for individual tailor calls, not full endpoint)

## Phase 1: Create Unified Orchestrate Endpoint

### Overview

Implement the `/api/orchestrate` endpoint that takes search criteria or pre-found jobs, coordinates Orchestrator and Tailor agents with proper user context, and returns comprehensive job scoring + evaluation results.

### Changes Required:

#### 1. Request/Response Schemas

**File**: `src/api/schemas.py`

**Intent**: Define the contract for `/api/orchestrate` request and response. The request should support flexible input (criteria or jobs or both), and the response should include all jobs with scores plus optional evaluations for shortlisted jobs.

**Contract**: 
- Add `OrchestrateRequest` class with:
  - `criteria: Optional[str]` — search criteria for Scout (if omitted, use provided jobs)
  - `jobs: Optional[List[JobOffer]]` — pre-found jobs to score directly (if omitted, run scout with criteria)
  - `score_threshold: float = 0.6` — minimum score to include in response
- Add `OrchestrateResponse` class with:
  - `all_jobs: List[dict]` — all jobs with id, title, company, url, match_score, analysis, evaluation (if shortlisted), and per-job errors
  - `shortlisted_jobs: List[dict]` — filtered to score >= 0.6, same fields, with evaluation included
  - `rejected_jobs: List[dict]` — jobs below threshold, with score and rejection reason
  - `status: str` — overall operation status
  - `error_count: int` — number of jobs that failed orchestration/tailor

#### 2. Orchestrate Endpoint Implementation

**File**: `src/api/routes/orchestrate.py` (new file)

**Intent**: Implement the `/api/orchestrate` POST endpoint that orchestrates the full workflow. Accepts flexible input, coordinates agents with proper user context, handles partial failures gracefully.

**Contract**: 
```python
@router.post("/orchestrate")
async def orchestrate(
    request: OrchestrateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Orchestrate job search, validation, scoring, and evaluation.
    
    Coordinates Orchestrator + Tailor agents to provide comprehensive
    job matching against user's CV with personalized evaluations.
    
    Args:
        request: OrchestrateRequest with criteria and/or jobs list
        user: Authenticated user from JWT
        session: Database session for persistence
    
    Returns:
        OrchestrateResponse with all_jobs, shortlisted_jobs, rejected_jobs
    """
```

**Implementation steps**:
1. Log the request with user email and input (criteria length, jobs count)
2. Instantiate `AgentFactory(user_id=user.id)` — critical for user-scoped CV context
3. Retrieve CV context from pgvector using `factory.vector_manager.get_context(query="")` or similar (handle case where CV doesn't exist)
4. **Build state**:
   - If `request.criteria` provided, initialize state for scout (found_jobs=[], valid_jobs=[], etc.)
   - If `request.jobs` provided, skip scout/validate and set state.valid_jobs = request.jobs
5. **Run scout** (if criteria provided):
   - Invoke `factory.scout(state)` with user's CV context
   - Extract found_jobs from result
6. **Run validator** (if found_jobs exists):
   - Call validate_and_limit_jobs_node (from graph validation pattern) or inline validation
   - Extract valid_jobs from result
7. **Run orchestrator**:
   - Invoke `factory.orchestrator(state)` with valid_jobs and resume_context populated
   - Extract shortlisted_jobs (score >= 0.6) from result
   - All jobs (including rejected) tracked for response
8. **Run tailor** (for shortlisted jobs):
   - For each shortlisted job, invoke `factory.tailor(state)` where state.shortlisted_jobs = [single_job]
   - Catch timeout/error exceptions per job; log and include error in response
   - Extract evaluation from result.applications[job_id].founded_job_offer
9. **Aggregate response**:
   - all_jobs: all processed jobs with match_score, analysis, evaluation (if tailor succeeded)
   - shortlisted_jobs: filtered to score >= request.score_threshold
   - rejected_jobs: jobs below threshold or failed validation
   - status: "Orchestration complete: X shortlisted, Y rejected, Z errors"
   - error_count: number of jobs that failed tailor
10. Return response as dict (following pattern of scoring.py:70-91)

#### 3. Route Registration

**File**: `src/api/main.py`

**Intent**: Register the new orchestrate router so it's accessible at `/api/orchestrate`.

**Contract**: 
- Add import: `from src.api.routes.orchestrate import router as orchestrate_router`
- Add line after line 130: `app.include_router(orchestrate_router)`

### Success Criteria:

#### Automated Verification:

- [ ] Type checking passes: `uv run mypy src/api/routes/orchestrate.py`
- [ ] Schemas validate: `OrchestrateRequest` and `OrchestrateResponse` are valid Pydantic models
- [ ] Route registration succeeds: `src/api/main.py` imports and includes orchestrate router without errors
- [ ] Linting passes: `uv run black src/api/routes/orchestrate.py src/api/schemas.py` and `uv run flake8` pass
- [ ] Existing tests still pass: `uv run pytest tests/` (no regressions in other endpoints)
- [ ] Unit tests for orchestrate endpoint pass (mocked agents, happy path + error cases)

#### Manual Verification:

- [ ] Endpoint is callable via curl with proper JWT auth
- [ ] Endpoint accepts criteria-only request and runs full scout → validate → orchestrate flow
- [ ] Endpoint accepts jobs-only request and skips scout/validate
- [ ] Endpoint accepts both criteria and jobs (preference to provided jobs)
- [ ] Returned all_jobs includes match_score and analysis for each job
- [ ] Shortlisted jobs include evaluation text from Tailor
- [ ] Rejected jobs show below-threshold scores with reasoning
- [ ] Error handling: if one job fails tailor, other jobs still included in response
- [ ] CV context is properly retrieved (verify via logs that RAG context was populated)
- [ ] Response matches OrchestrateResponse schema

**Implementation Note**: After completing this phase, pause for manual testing confirmation before declaring completion. The endpoint should be tested with a real user account, pre-loaded CV, and actual job data to ensure orchestration flow works end-to-end.

---

## Testing Strategy

### Unit Tests:

Create `tests/api/test_orchestrate.py`:
- Mock `get_current_user` to return test user
- Mock `get_db` to return test database session
- Mock `AgentFactory` to return mocked agents
- Test happy path: criteria provided → scout runs → orchestrator runs → tailor runs
- Test: jobs provided → skip scout/validate, go straight to orchestrator
- Test: both criteria and jobs → prefer jobs, don't run scout
- Test: no criteria and no jobs → return error
- Test: partial failure (one job fails tailor) → other jobs still in response
- Test: CV not found → return error with clear message
- Test: orchestrator returns no shortlisted jobs → response with empty shortlisted_jobs

### Integration Tests:

- Call endpoint with authenticated user + pre-found jobs (use test job fixtures)
- Verify response structure matches OrchestrateResponse
- Verify match_score is populated (not 0.0 default)
- Verify analysis field contains reasoning

## Performance Considerations

- **Orchestrator RAG call**: Happens once per job; scales with job count. For ~10 jobs, expect < 5s with RAG context retrieval.
- **Tailor LLM calls**: Happens per shortlisted job (typically 2-3). Each tailor call is ~2-3s; multiple calls can happen sequentially or in parallel (future optimization: use asyncio.gather).
- **Overall request timeout**: Set reasonable timeout (e.g., 30-60s) to avoid client timeouts on slow LLM calls. Consider returning results as they're ready (streaming) as future enhancement.
- **Vector DB queries**: pgvector semantic search is fast (~100ms per query). Minimal performance concern.

## Migration Notes

No database schema changes. No data migration needed. The endpoint uses existing user/job/CV tables and pgvector columns. Existing `/api/score_jobs` endpoint continues to work (with its CV context bug). Future work can deprecate `/api/score_jobs` if the unified orchestrate endpoint proves sufficient.

## References

- Related agents: `src/agents/{scout, orchestrator, tailor}.py`
- Existing endpoint patterns: `src/api/routes/{search, validation, scoring, evaluation}.py`
- State management: `src/schema/state.py`
- Factory pattern: `src/agents/agents.py`
- Vector DB access: `src/tools/vectordb.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: Create Unified Orchestrate Endpoint

#### Automated

- [x] 1.1 Type checking passes: mypy src/api/routes/orchestrate.py
- [x] 1.2 Schemas validate: OrchestrateRequest and OrchestrateResponse are valid Pydantic models
- [x] 1.3 Route registration succeeds: src/api/main.py imports and includes orchestrate router
- [x] 1.4 Linting passes: black and flake8
- [x] 1.5 Existing tests still pass: pytest tests/

#### Manual

- [ ] 1.6 Endpoint callable via curl with JWT auth
- [ ] 1.7 Endpoint accepts criteria-only and runs full workflow
- [ ] 1.8 Endpoint accepts jobs-only and skips scout/validate
- [ ] 1.9 Returned jobs include match_score and analysis
- [ ] 1.10 Shortlisted jobs include evaluation text from Tailor
- [ ] 1.11 Error handling works: partial success when one job fails
- [ ] 1.12 CV context properly retrieved and used in orchestration
