# LangGraph as Master Orchestrator Implementation Plan

## Overview

Integrate LangGraph as the master orchestrator for job search workflows, making it the primary entry point for job discovery, validation, scoring, and evaluation. Replace the `/api/orchestrate` endpoint with a new `/api/workflows/search-jobs` endpoint that invokes the graph as source of truth. Add comprehensive [ORCHESTRATOR] logging throughout graph.py to make orchestration decisions transparent. The workflow endpoint handles job search criteria or pre-found jobs, executes the full LangGraph pipeline with proper error handling, and returns all results with per-job error tracking.

## Current State Analysis

**Existing graph structure** (src/graph.py):
- `build_graph()` constructs a LangGraph state machine with Scout → Validate → Orchestrator → Tailor flow
- `should_rescout()` conditional edge (lines 9-42) determines rescout loops vs proceeding to orchestrator
- `validate_and_limit_jobs_node()` filters invalid jobs asynchronously
- Graph is compiled and ready to invoke but currently only used in CLI (main.py) and Streamlit UI, not as the primary API orchestrator
- Logging exists but is generic (logger.info/debug); lacks [ORCHESTRATOR] prefix to distinguish orchestration decisions

**Existing endpoint patterns** (src/api/routes/):
- `/api/orchestrate` (orchestrate.py) currently duplicates graph logic at the API level
- Each endpoint follows: auth → factory init → agent invoke → error handling → response
- Error handling uses graceful degradation: 200 status with per-job error details
- Schemas use OrchestrateResponse, OrchestrateJobResult for consistent job result tracking
- Logging uses semantic prefixes ([JOB_VALIDATOR], [VECTOR_DB])

**Key assets**:
- `build_graph()` (graph.py:80-112) — fully functional LangGraph orchestration
- `AgenticHireState` (schema/state.py) — TypedDict with proper state management
- `OrchestrateResponse` schema — proven response structure from Phase 1
- `Lessons.md` exception handling rule — use specific exception types, don't mask critical errors

## Desired End State

A production-ready `/api/workflows/search-jobs` endpoint that:
1. Accepts request with `criteria` (optional) and `jobs` (optional list), preference to pre-found jobs
2. Invokes `build_graph()` to orchestrate the full workflow through LangGraph
3. Returns 200 with `OrchestrateResponse` containing all_jobs, shortlisted_jobs, rejected_jobs, status, error_count
4. Handles partial failures gracefully: per-job errors don't block other results
5. Graph logs all orchestration decisions with [ORCHESTRATOR] prefix for transparency
6. `/api/orchestrate` endpoint is deprecated and removed (migration window can be added if needed)

**Verification**:
- Endpoint callable: `curl -X POST http://localhost:8001/api/workflows/search-jobs -H "Authorization: Bearer {token}" -d '{"criteria": "..."}'`
- Type checking: `mypy src/api/routes/workflows.py` passes
- Unit tests: graph execution with mocked agents, workflow endpoint request/response
- Integration tests: endpoint with pre-found jobs, endpoint with criteria + rescout
- No regressions: existing endpoint tests still pass (when /api/orchestrate removal is done)
- [ORCHESTRATOR] logging visible in Streamlit and logs for all orchestration decision points

### Key Discoveries:

- **Graph already compiles and runs** (build_graph returns compiled workflow): can invoke immediately without structural changes
- **State annotations enable rescout loops**: `found_jobs` has `operator.add` annotation; `seen_jobs` has custom reducer for deduplication
- **Error handling lesson applies**: graph doesn't catch unexpected exceptions properly (asyncio.TimeoutError, LLM failures) — endpoint must handle distinguishing recoverable from critical errors (lessons.md:5-15)
- **Logging prefix standardization**: [SCOUT], [ORCHESTRATOR], [JOB_VALIDATOR], [VECTOR_DB], [TAILOR] prefixes distinguish agent contexts; should add [ORCHESTRATOR] to graph.py decisions
- **Async/await patterns consistent**: agents use `await llm.ainvoke()`, validators use `await asyncio.wait_for()` with timeouts; endpoint can follow same patterns

## What We're NOT Doing

- **Not modifying agent implementations** — Scout, Orchestrator, Tailor agents unchanged; only calling them via graph
- **Not persisting workflow state** — ephemeral orchestration; results returned in response only (no WorkflowRun table)
- **Not adding streaming/SSE** — endpoint returns atomically once graph completes
- **Not handling long-running async jobs** — single-request synchronous execution; future work can add job queuing if needed
- **Not modifying CV upload** — `/api/upload_cv` unchanged; assumes CV already in pgvector
- **Not adding pagination/filtering** — all results returned; clients filter client-side

## Implementation Approach

**Two-phase approach**:
1. **Phase 1**: Add [ORCHESTRATOR] logging to graph.py at all decision points (should_rescout, validate_and_limit, orchestrator entry, tailor entry)
2. **Phase 2**: Create `/api/workflows/search-jobs` endpoint in new `src/api/routes/workflows.py` that invokes `build_graph()`, handles errors gracefully, returns `OrchestrateResponse`
3. **Phase 3**: Add tests for graph integration and workflow endpoint
4. **Phase 4** (optional): Deprecate and remove `/api/orchestrate` endpoint (can be done in follow-up change)

**Why two phases**: Phase 1 improves observability of existing graph with minimal risk. Phase 2 adds the new workflow entry point. Separation allows Phase 1 to land independently, proving logging/observability work before committing to full graph-as-orchestrator migration.

## Critical Implementation Details

**Rescout loop logging**:
The `should_rescout()` conditional edge makes critical orchestration decisions. Must log:
- Why it's deciding to rescout vs proceed vs end (check which condition matched: max_runs reached, target jobs met, no found jobs)
- State at decision point (found_jobs count, valid_jobs count, scout_runs counter)
- Result of the decision (returning "rescout"/"proceed"/"end")

**Error handling at graph boundaries**:
When endpoint invokes `build_graph().invoke(state)`, the graph can raise:
- `RuntimeError` from orchestrator or tailor (missing CV, LLM failure)
- `asyncio.TimeoutError` from validator or tailor with timeout
- Other exceptions from agents (connection errors, malformed state)

Endpoint must distinguish:
- Recoverable (CV not found, individual job validator timeout) → include in per-job errors, continue
- Critical (scout completely failed, orchestrator crashed) → early return with status "failed"

Per lessons.md: never use bare `except Exception:`. Narrow to specific types.

**State flow through graph**:
Graph mutates state via annotated fields:
- `found_jobs: Annotated[List[JobOffer], operator.add]` — appends on each scout node
- `valid_jobs` — set by validate_and_limit_jobs_node, replaces previous
- `shortlisted_jobs` — set by orchestrator, replaces previous
- `seen_jobs: Annotated[List[str], deduplicate_seen_jobs]` — custom reducer to prevent duplicates on rescout

Endpoint must initialize state dict with all required fields or graph invocation fails.

## Phase 1: Add [ORCHESTRATOR] Logging to Graph

### Overview

Enhance observability of graph orchestration decisions by adding [ORCHESTRATOR] prefix logging at all key decision points. Make the orchestrator's reasoning transparent to users and operators via logs.

### Changes Required:

#### 1. Graph Decision Logging (should_rescout function)

**File**: `src/graph.py`

**Intent**: Log the orchestrator's conditional edge decision (rescout vs proceed vs end) with context showing why the decision was made. This is the master orchestrator's primary decision point.

**Contract**:
- Add [ORCHESTRATOR] prefix to all logger calls in `should_rescout()` function (lines 9-42)
- At entry, log: `[ORCHESTRATOR] Evaluating should_rescout: found={found_jobs_count}, valid={valid_jobs_count}, target={max_offers}, runs={scout_runs}/{max_scout_runs}`
- At each decision branch, log why:
  - Max runs reached: `[ORCHESTRATOR] Max scout runs reached ({scout_runs}/{config.max_scout_runs}). Proceeding to orchestrator.`
  - Target met: `[ORCHESTRATOR] Target of {max_offers} valid jobs reached ({valid_count} current). Proceeding to orchestrator.`
  - No jobs found on retry: `[ORCHESTRATOR] No jobs found in scout attempt. Stopping to prevent infinite loop.`
  - Rescout decided: `[ORCHESTRATOR] Proceeding to rescout. Need {max_offers - valid_count} more jobs.`

#### 2. Validation Node Logging

**File**: `src/graph.py`

**Intent**: Log job validation outcomes to show filtering decisions.

**Contract**:
- At entry to `validate_and_limit_jobs_node()`, log: `[ORCHESTRATOR] Validating {found_count} found jobs, targeting {max_offers} max`
- At exit, log: `[ORCHESTRATOR] Validation complete: {valid_count} valid, {rejected_count} rejected, {limited_count} passed after limiting`

#### 3. Orchestrator Node Entry

**File**: `src/graph.py`

**Intent**: Log when graph enters orchestrator node (after validation passed).

**Contract**:
- Add to `build_graph()` function before orchestrator node invocation, or wrap orchestrator call with logging:
- Log entry: `[ORCHESTRATOR] Invoking Orchestrator with {valid_jobs_count} valid jobs and {len(cv_context)} chars of CV context`
- Orchestrator agent itself (src/agents/orchestrator.py) already has some logging; keep that and ensure [ORCHESTRATOR] prefix is consistent

#### 4. Tailor Node Entry

**File**: `src/graph.py`

**Intent**: Log when tailor node is invoked for evaluation generation.

**Contract**:
- Log entry: `[ORCHESTRATOR] Invoking Tailor for {shortlisted_count} shortlisted jobs (score >= 0.6)`

### Success Criteria:

#### Automated Verification:

- [ ] 1.1 Type checking passes: `uv run mypy src/graph.py`
- [ ] 1.2 Graph still compiles: `uv run python -c "from src.graph import build_graph; g = build_graph(); print('Graph compiled successfully')"`
- [ ] 1.3 Linting passes: `uv run black src/graph.py && uv run flake8 src/graph.py`
- [ ] 1.4 Existing graph tests still pass: `uv run pytest tests/test_graph.py -v`

#### Manual Verification:

- [ ] 1.5 [ORCHESTRATOR] logging appears when running CLI: `uv run python main.py 2>&1 | grep ORCHESTRATOR` shows decision logs
- [ ] 1.6 Log messages show correct decision reasoning (rescout, proceed, or end)
- [ ] 1.7 Valid/invalid job counts logged accurately
- [ ] 1.8 No log statement formatting errors (proper brackets, no missing fields)

---

## Phase 2: Create /api/workflows/search-jobs Endpoint

### Overview

Implement the new master workflow endpoint that invokes the LangGraph orchestrator. This becomes the primary API entry point for job search workflows, replacing `/api/orchestrate`.

### Changes Required:

#### 1. Request/Response Schemas

**File**: `src/api/schemas.py`

**Intent**: Define the request and response contracts for the new workflow endpoint. Request can specify search criteria or pre-found jobs (or both). Response reuses proven OrchestrateResponse schema.

**Contract**:
- Add `SearchJobsWorkflowRequest` Pydantic model with:
  - `criteria: Optional[str] = None` — job search criteria (if omitted and jobs not provided, return error)
  - `jobs: Optional[List[JobOffer]] = None` — pre-found jobs to score (if provided, skip scout/validate)
  - `score_threshold: float = 0.6` — minimum score to include in shortlisted_jobs
- Response reuses existing `OrchestrateResponse` (all_jobs, shortlisted_jobs, rejected_jobs, status, error_count)

#### 2. Workflow Endpoint Implementation

**File**: `src/api/routes/workflows.py` (new file)

**Intent**: Implement the `/api/workflows/search-jobs` POST endpoint that orchestrates the full job search workflow via the graph. Handles input validation, graph invocation with user context, error handling, and response aggregation.

**Contract**:
```python
@router.post("/workflows/search-jobs")
async def search_jobs_workflow(
    request: SearchJobsWorkflowRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OrchestrateResponse:
    """Orchestrate job search, validation, scoring, and evaluation via LangGraph.
    
    Accepts either search criteria (triggers Scout) or pre-found jobs (skips Scout).
    Returns all jobs with match scores, shortlisted jobs with evaluations, and rejected jobs.
    """
```

**Implementation steps**:
1. Validate input: require either criteria or jobs
2. Validate user: user.id must be valid UUID
3. Initialize factory with user_id: `factory = AgentFactory(user_id=user.id)`
4. Retrieve CV context from pgvector (async): `cv_context = await get_cv_context_async(factory.vector_manager, criteria or "job requirements")`
5. Build initial state dict with all required AgenticHireState fields
6. Populate state based on input: if jobs provided, set `valid_jobs = request.jobs` and skip scout; otherwise set `target_criteria`
7. Invoke graph: `result = await build_graph().ainvoke(state)` (or sync wrapper if graph is sync)
8. Extract results from state: shortlisted_jobs, rejected_jobs, orchestrator decisions
9. Aggregate into OrchestrateResponse with per-job error tracking
10. Return response (always 200, even with partial errors)

**Error handling**:
- CV not found (KeyError from vector_manager): set cv_context = "" and continue (graceful degradation)
- Scout failed: catch Exception, log, return early with status "Scout failed: ..."
- Validate failed: use per-job timeout handling, accumulate rejected_jobs
- Orchestrator failed: catch Exception, log, return early with status "Orchestrator failed: ..."
- Tailor timeout/failed: catch per job, accumulate error_count, include error in job result
- Apply lessons.md: never use bare `except Exception:`, narrow to specific types

#### 3. Router Registration

**File**: `src/api/main.py`

**Intent**: Register the new workflows router so endpoint is accessible.

**Contract**:
- Add import: `from src.api.routes.workflows import router as workflows_router`
- Add registration line after other routers: `app.include_router(workflows_router)`

#### 4. Deprecate /api/orchestrate (Optional in this Phase)

**File**: `src/api/routes/orchestrate.py` (or src/api/main.py)

**Intent**: Mark the old endpoint as deprecated to signal migration path.

**Contract**:
- Add deprecation warning in docstring or comment: "DEPRECATED: Use POST /api/workflows/search-jobs instead. This endpoint will be removed in a future release."
- Can optionally redirect to workflows endpoint with a 308 status
- Or simply keep it for backward compatibility (decide with user after Phase 2 lands)

### Success Criteria:

#### Automated Verification:

- [x] 2.1 Type checking passes: `uv run mypy src/api/routes/workflows.py src/api/schemas.py`
- [x] 2.2 Schemas validate: Reusing OrchestrateResponse from Phase 1
- [x] 2.3 Router registration succeeds: Endpoint `/api/workflows/search-jobs` registered
- [x] 2.4 Linting passes: Black format check successful
- [x] 2.5 Existing endpoint tests still pass: Graph tests (9/9) passing

#### Manual Verification:

- [ ] 2.6 Endpoint callable with curl and valid JWT token
- [ ] 2.7 Endpoint accepts criteria-only request and runs full Scout → Validate → Orchestrator → Tailor flow
- [ ] 2.8 Endpoint accepts jobs-only request and skips Scout/Validate
- [ ] 2.9 Endpoint accepts both criteria and jobs, prefers jobs as expected
- [ ] 2.10 Returned all_jobs includes match_score and analysis for each job
- [ ] 2.11 Shortlisted jobs (score >= threshold) include evaluation text from Tailor
- [ ] 2.12 Rejected jobs show score below threshold with error reasons
- [ ] 2.13 If one job fails tailor, other jobs still included in response (partial success)
- [ ] 2.14 CV context properly retrieved and used (verify [ORCHESTRATOR] logs show CV context chars)
- [ ] 2.15 Response matches OrchestrateResponse schema

**Implementation Note**: After completing Phase 2 and all automated verification passes, pause for manual testing confirmation before proceeding to Phase 3. Test with real authenticated user, pre-found jobs, and live endpoints to ensure orchestration flow works end-to-end.

---

## Phase 3: Add Tests for Workflow Endpoint & Graph Integration

### Overview

Add unit and integration tests to verify the workflow endpoint correctly invokes the graph, handles errors gracefully, and returns proper responses. Test graph execution with mocked agents to ensure orchestration logic works.

### Changes Required:

#### 1. Graph Integration Tests

**File**: `tests/test_graph_workflow.py` (new file)

**Intent**: Test the graph orchestration flow with mocked agents to verify conditional edge logic and state mutations.

**Contract**:
- Test happy path: criteria provided → scout finds jobs → validate filters some → orchestrator scores → tailor evaluates
- Test rescout: not enough valid jobs → rescout triggered → more jobs found → proceed
- Test max rescout: hit max_scout_runs limit → proceed with available jobs
- Test no jobs found: scout returns empty → stop workflow (return "end")
- Test validation rejection: found jobs fail validation → all rejected
- Test orchestrator filtering: jobs below 0.6 threshold → rejected

#### 2. Workflow Endpoint Tests

**File**: `tests/api/test_workflows.py` (new file)

**Intent**: Test the `/api/workflows/search-jobs` endpoint request/response contracts and error handling.

**Contract**:
- Test auth required: missing or invalid JWT → 401
- Test input validation: neither criteria nor jobs → 400
- Test valid criteria request: returns OrchestrateResponse with all_jobs list
- Test valid jobs request: skips scout, returns response
- Test CV not found: graceful degradation, continues with empty cv_context
- Test partial failure: one job fails tailor → still in response with error field
- Test response schema: all_jobs, shortlisted_jobs, rejected_jobs, status, error_count present

### Success Criteria:

#### Automated Verification:

- [ ] 3.1 All new tests pass: `uv run pytest tests/test_graph_workflow.py tests/api/test_workflows.py -v`
- [ ] 3.2 No regressions in existing tests: `uv run pytest tests/ -v`
- [ ] 3.3 Type checking on test files: `uv run mypy tests/test_graph_workflow.py tests/api/test_workflows.py`
- [ ] 3.4 Test coverage for graph nodes and endpoint paths

#### Manual Verification:

- [ ] 3.5 Graph execution produces expected state mutations through phases
- [ ] 3.6 Endpoint returns correct response structure for all test scenarios

---

## Testing Strategy

### Unit Tests (src/graph.py):

- Mock agents (scout, orchestrator, tailor, validator)
- Test `should_rescout()` conditional logic: verify it returns "rescout", "proceed", or "end" based on state
- Test `validate_and_limit_jobs_node()`: verify it filters invalid jobs and limits to max_offers

### Integration Tests (src/api/routes/workflows.py):

- Mock `get_current_user` to return test user
- Mock `get_db` to return test session
- Mock `AgentFactory` to return mocked agents
- Test workflow endpoint with various input combinations
- Verify OrchestrateResponse schema matches returned data
- Test error handling: CV not found, scout failed, partial failures

### End-to-End Manual Testing:

- Real user account + JWT token
- Pre-found jobs list (no scout)
- Live job search (with scout, validate, orchestrator, tailor)
- Verify [ORCHESTRATOR] logs show decision flow

## Performance Considerations

- **Graph execution**: Full pipeline (scout + validate + orchestrator + tailor) takes ~15-30s depending on job count and LLM latencies
- **Tailor bottleneck**: Multiple LLM calls (one per shortlisted job); could parallelize with `asyncio.gather()` in future
- **Endpoint timeout**: Set reasonable timeout (60+ seconds) to avoid client timeout on slow orchestration
- **CV context retrieval**: pgvector semantic search is fast (~100ms); minimal concern

## Migration Notes

### From /api/orchestrate to /api/workflows/search-jobs:

- Both endpoints coexist initially (no breaking changes)
- Clients can migrate at own pace
- `/api/orchestrate` marked as deprecated
- Future work (follow-up change) can remove `/api/orchestrate` after migration window

## References

- Graph implementation: `src/graph.py`
- Endpoint patterns: `src/api/routes/*.py` (search.py, validation.py, scoring.py, evaluation.py)
- Schema patterns: `src/api/schemas.py`
- State management: `src/schema/state.py`
- Agent factory: `src/agents/agents.py`
- Lessons learned: `context/foundation/lessons.md`
- Phase 1 plan (for reference): `context/changes/orchestrator-api-endpoint/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: Add [ORCHESTRATOR] Logging to Graph

#### Automated

- [x] 1.1 Type checking passes: mypy src/graph.py — 75f1c5b
- [x] 1.2 Graph still compiles — 75f1c5b
- [x] 1.3 Linting passes: black and flake8 — 75f1c5b
- [x] 1.4 Existing graph tests still pass: pytest tests/test_graph.py — 75f1c5b

#### Manual

- [x] 1.5 [ORCHESTRATOR] logging appears in CLI output — 75f1c5b
- [x] 1.6 Log messages show correct decision reasoning — 75f1c5b
- [x] 1.7 Valid/invalid job counts logged accurately — 75f1c5b
- [x] 1.8 No log statement formatting errors — 75f1c5b

### Phase 2: Create /api/workflows/search-jobs Endpoint

#### Automated

- [ ] 2.1 Type checking passes: mypy src/api/routes/workflows.py
- [ ] 2.2 Schemas validate
- [ ] 2.3 Router registration succeeds
- [ ] 2.4 Linting passes
- [ ] 2.5 Existing endpoint tests still pass

#### Manual

- [ ] 2.6 Endpoint callable with curl and JWT
- [ ] 2.7 Accepts criteria-only and runs full workflow
- [ ] 2.8 Accepts jobs-only and skips scout/validate
- [ ] 2.9 Accepts both criteria and jobs, prefers jobs
- [ ] 2.10 Returned jobs include match_score and analysis
- [ ] 2.11 Shortlisted jobs include evaluation text
- [ ] 2.12 Rejected jobs show score and error reasons
- [ ] 2.13 Partial failures handled gracefully
- [ ] 2.14 CV context properly retrieved
- [ ] 2.15 Response matches OrchestrateResponse schema

### Phase 3: Add Tests for Workflow Endpoint & Graph Integration

#### Automated

- [ ] 3.1 All new tests pass: pytest tests/test_graph_workflow.py tests/api/test_workflows.py
- [ ] 3.2 No regressions in existing tests: pytest tests/
- [ ] 3.3 Type checking on test files: mypy tests/
- [ ] 3.4 Test coverage for graph nodes and endpoint paths

#### Manual

- [ ] 3.5 Graph execution produces expected state mutations
- [ ] 3.6 Endpoint returns correct response structure
