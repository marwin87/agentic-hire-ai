# Validation Endpoint Refactor Implementation Plan

## Overview

Refactor the job validation endpoint to work properly with Scout agent output in the new FastAPI-based flow. Currently, validation logic exists but isn't integrated with Scout's results. The endpoint will be synchronous, receive jobs from Scout (via Orchestrator coordination), validate them using existing rules (URL accessibility, HTTP status, job expiration detection), and return detailed results with rejection reasons and timeout flags.

## Current State Analysis

**What exists:**
- `JobValidator` class in `src/tools/job_validator.py` with three validation stages: URL format check, HTTP accessibility check (GET request with 400+ rejection), LLM-based expiration detection
- FastAPI endpoint `POST /api/validate_jobs` at `src/api/routes/validation.py` that takes job dicts and calls `validate_and_limit_jobs_node()`
- Configuration in `src/config/settings.py` for validator timeout (10s), content limits (6000 chars), retry logic (2 max retries), and cache enablement
- LangGraph integration via `validate_and_limit_jobs_node()` in `src/graph.py`

**What's missing:**
- Integration with Scout agent output — Scout returns jobs but validation isn't automatically triggered
- Proper error response contract — current endpoint doesn't return structured failure reasons or timeout flags
- Clear separation between Orchestrator-initiated flow and legacy CLI/Streamlit flow
- Per-job failure reason codes (needed for Orchestrator to handle rejections intelligently)

**Key constraints discovered:**
- Synchronous endpoint preferred (5-10 jobs max, in-memory caching, simple flow)
- Orchestrator will orchestrate: Scout → (Orchestrator calls validate) → (Orchestrator receives result) → Orchestrator scoring
- Partial results acceptable on timeout (mark timed-out jobs with flag rather than failing entire request)
- Current validation rules (URL format, HTTP check, LLM expiration) are sufficient for Phase 1

## Desired End State

When complete, the validation endpoint will:
1. Accept a list of jobs from Scout (via Orchestrator caller) with structured JobOffer format
2. Validate each job using existing rules with per-job timeout handling
3. Return `200 OK` with `{valid_jobs: [...], rejected_jobs: [{id, reason_code, reason_text, ...}]}`
4. Include timeout flags in rejected jobs if validation didn't complete
5. Log only summary (X validated, Y rejected) to keep output clean
6. Be ready for Orchestrator agent to receive results and proceed to scoring

**Verification:** Orchestrator can successfully call endpoint, parse response, and handle both valid jobs and rejection reasons without errors.

## What We're NOT Doing

- Async/fire-and-forget pattern — keeping it synchronous for simplicity
- Adding new validation rules in Phase 1 — sticking with URL check + HTTP + expiration
- Webhook callbacks or long-running job queue — in-memory processing only
- Backwards compatibility with old CLI validation flow — this is a full refactor
- Real-time job status updates during validation — single synchronous response

## Implementation Approach

**Architecture:**
- Refactor `POST /api/validate_jobs` to accept Scout job output format and return structured failure reasons
- Separate request schema from response schema (input: list of jobs, output: {valid_jobs, rejected_jobs})
- Implement failure reason enum (e.g., `URL_INVALID`, `HTTP_ERROR`, `JOB_EXPIRED`, `VALIDATION_TIMEOUT`)
- Reuse existing `JobValidator` logic; wrap with per-job timeout tracking and reason assignment
- Keep logging minimal (summary only) to avoid log spam

**Rationale:**
- Scout already works; we're not changing it
- `JobValidator` is proven; we wrap it, not rewrite it
- Synchronous keeps the code simple and matches Orchestrator expectations
- Partial results + timeout flags give Orchestrator visibility into what happened without blocking
- Reason codes let Orchestrator programmatically decide (retry, skip, log, etc.)

## Critical Implementation Details

**Timeout strategy:**
The endpoint has a global timeout (e.g., 30 seconds total). If validating 8 jobs with 10s timeout each, we may not finish all. When a job times out during HTTP request or LLM call:
- Catch the timeout exception
- Mark that job as rejected with `reason_code: 'VALIDATION_TIMEOUT'`
- Continue to the next job
- Return partial results: some valid, some rejected (with mixed reasons)

This prevents one slow job from blocking all results and lets Orchestrator see what worked.

## Phase 1: Refactor Validation Endpoint

### Overview

Refactor the existing `/api/validate_jobs` endpoint to match the new Scout→Validate→Orchestrator flow. The endpoint will accept jobs and return structured results with per-job failure reasons and timeout flags. Validation logic itself doesn't change; we're fixing the integration and response contract.

### Changes Required:

#### 1. Request/Response Schemas (`src/api/schemas.py`)

**File**: `src/api/schemas.py`

**Intent**: Define clear input and output types for the validation endpoint. The request accepts jobs from Scout, the response returns structured valid/rejected lists with reason codes.

**Contract**: 
- Input schema `ValidateJobsRequest`: List of job objects (can reuse/extend existing schema if present, or create new `JobToValidate` Pydantic model with fields: id, title, company, url, description, salary_range)
- Output schema `ValidateJobsResponse`: `{valid_jobs: List[JobOffer], rejected_jobs: List[RejectedJob]}` where `RejectedJob` has fields: id, title, company, url, reason_code (enum), reason_text, validation_duration_ms
- Reason code enum: `URL_INVALID | HTTP_ERROR | JOB_EXPIRED | VALIDATION_TIMEOUT`

#### 2. Validation Endpoint (`src/api/routes/validation.py`)

**File**: `src/api/routes/validation.py`

**Intent**: Refactor the endpoint to handle per-job timeouts, capture failure reasons, and return structured rejection data. The endpoint calls `JobValidator` for each job, catches exceptions/timeouts, assigns reason codes, and returns partial results.

**Contract**: 
- Route: `POST /api/validate_jobs` (keep existing route)
- Request body: `ValidateJobsRequest` (list of jobs)
- Response: `ValidateJobsResponse` (always 200 OK, with valid_jobs and rejected_jobs lists)
- Each rejected job includes: reason_code (enum), reason_text (human-readable), duration_ms
- Timeout per job: inherit from config (e.g., 10 seconds per job, configurable in `AppConfig`)
- Logging: Single log line: "Validated N jobs: X passed, Y rejected" (no per-job logging)

**Implementation note**: The endpoint will iterate through jobs, call `factory.job_validator.is_job_valid(job)` with timeout wrapping, catch `asyncio.TimeoutError` and other exceptions, build RejectedJob objects with reason codes, and return the structured response. Reuse existing `JobValidator` — don't modify its core logic.

#### 3. Rejection Reason Enum (`src/schema/validation.py` or add to `src/schema/state.py`)

**File**: `src/schema/validation.py` (new file)

**Intent**: Centralize validation failure reasons as an enum so Orchestrator can programmatically handle different rejection types.

**Contract**: 
- Enum `ValidationFailureReason` with values: `URL_INVALID`, `HTTP_ERROR`, `JOB_EXPIRED`, `VALIDATION_TIMEOUT`
- Each maps to a human-readable message
- Keep enum in a dedicated schema file for reuse

### Success Criteria:

#### Automated Verification:

- Type checking passes: `uv run mypy src/api/`
- Linting passes: `uv run black src/api/ --check` (or your linter)
- Unit tests pass for validation endpoint: `uv run pytest tests/test_api_endpoints.py::test_validate_jobs* -v`
- Unit tests pass for new schemas: `uv run pytest tests/ -k validation -v`
- Endpoint returns 200 OK with valid response structure (no 5xx errors)
- Rejection reason codes are assigned correctly (URL_INVALID for bad URLs, HTTP_ERROR for 4xx/5xx, etc.)

#### Manual Verification:

- Call endpoint with mixed jobs: some valid, some with dead URLs, some expired
  - Verify valid jobs appear in `valid_jobs` list
  - Verify invalid jobs appear in `rejected_jobs` with correct `reason_code`
  - Verify response is always 200 OK, never 500
- Test timeout scenario: add a job with a very slow URL
  - Verify job is rejected with `VALIDATION_TIMEOUT` code
  - Verify other jobs are still validated (partial result)
- Verify response matches `ValidateJobsResponse` schema
- Check logs show only summary line, no per-job details

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual testing confirmation before proceeding to Phase 2.

---

## Phase 2: Integration & Testing

### Overview

Verify the endpoint works end-to-end when called by Orchestrator (or a mock caller). Add comprehensive test coverage for edge cases and mixed scenarios (all jobs fail, timeouts, mixed results). Ensure type hints are complete and schemas are correct.

### Changes Required:

#### 1. Integration Tests (`tests/test_api_endpoints.py`)

**File**: `tests/test_api_endpoints.py`

**Intent**: Test the endpoint with realistic Scout job output and verify Orchestrator can parse and handle the response. Test edge cases: all jobs fail, mixed valid/invalid, timeouts.

**Contract**: 
- Test: "All jobs pass validation" → verify valid_jobs is populated, rejected_jobs is empty
- Test: "All jobs fail validation" → verify valid_jobs is empty, rejected_jobs populated with reasons
- Test: "Mixed results" → verify both lists populated correctly
- Test: "Some jobs timeout" → verify timeout jobs marked with VALIDATION_TIMEOUT code, others still processed
- Test: "Invalid URL formats" → verify URL_INVALID reason code assigned
- Test: "HTTP errors (404, 500, etc.)" → verify HTTP_ERROR reason code assigned
- Test: "Response schema matches ValidateJobsResponse" → schema validation passes
- Mock `JobValidator.is_job_valid()` to simulate various outcomes and timeouts

#### 2. Type Hints Audit

**File**: `src/api/routes/validation.py`, `src/api/schemas.py`

**Intent**: Ensure all functions and variables have complete type hints (mypy strict mode requirement).

**Contract**: 
- All function signatures include parameter types and return types
- All module-level variables typed
- No `Any` types without explicit justification
- Mypy strict mode passes with no errors

### Success Criteria:

#### Automated Verification:

- All integration tests pass: `uv run pytest tests/test_api_endpoints.py::test_validate_jobs* -v`
- Edge case tests pass (all fail, timeouts, mixed)
- Type checking passes: `uv run mypy src/api/ --strict`
- No warnings from linter

#### Manual Verification:

- Write a simple test script that calls the endpoint like Orchestrator would
  - Pass 5-10 realistic jobs (mix of valid and invalid URLs)
  - Verify response structure is correct
  - Verify reason codes are sensible
- Simulate a slow job (mock response delay) and verify timeout handling
- Verify logs show only summary, no spam

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 3.

---

## Phase 3: Documentation & Verification

### Overview

Document the endpoint contract so Orchestrator knows what to expect. Perform full manual verification that the flow works: Scout (returns raw jobs) → Orchestrator (calls validate) → (receives valid/rejected jobs) → (ready for Orchestrator scoring).

### Changes Required:

#### 1. OpenAPI Documentation (`src/api/routes/validation.py`)

**File**: `src/api/routes/validation.py`

**Intent**: Add docstrings and FastAPI route annotations so the endpoint is self-documenting in OpenAPI/Swagger.

**Contract**: 
- Add docstring to the validation endpoint function describing purpose, input, output, and error scenarios
- Ensure FastAPI extracts correct request/response schemas for Swagger UI
- Document reason codes in docstring or via Pydantic field descriptions
- Include example request/response in docstring or as JSON schema example

#### 2. Integration Verification Document (`context/changes/validate-jobs-endpoint/VERIFICATION.md`)

**File**: `context/changes/validate-jobs-endpoint/VERIFICATION.md`

**Intent**: Provide step-by-step instructions for verifying the flow works end-to-end.

**Contract**: 
- Document test scenarios: valid jobs, invalid jobs, mixed, timeouts
- Provide curl commands or Python script to call the endpoint
- Specify expected responses for each scenario
- Include screenshot or output examples

### Success Criteria:

#### Automated Verification:

- No new test failures introduced
- Type checking passes
- Swagger/OpenAPI docs generate without errors

#### Manual Verification:

- Orchestrator agent can call the endpoint and receive valid response
- Response schema is correct and parseable by Orchestrator
- All rejection reason codes are documented and sensible
- Logs show clean summary output (no spam, no missing info)
- Flow works: Scout output → Validation → Orchestrator ready to score
- Verify no regressions in existing features (Scout, Orchestrator scoring, Tailor)

**Implementation Note**: This is the final phase. After manual verification passes, the change is complete and ready for review.

---

## Testing Strategy

### Unit Tests

- **Validation schemas**: Test that `ValidateJobsRequest` and `ValidateJobsResponse` serialize/deserialize correctly
- **Reason code assignment**: Test that each failure type (URL_INVALID, HTTP_ERROR, JOB_EXPIRED, VALIDATION_TIMEOUT) is assigned to the correct job
- **Edge cases**: All jobs pass, all jobs fail, empty job list, single job
- **Timeout handling**: Job times out → reason_code = VALIDATION_TIMEOUT, other jobs still processed

### Integration Tests

- **Full endpoint flow**: POST to `/api/validate_jobs`, verify response matches schema and content is correct
- **Mixed results**: Call with jobs that will pass and fail, verify both lists populated
- **HTTP errors**: Mock `JobValidator.is_job_valid()` to return False with specific reasons (404, expired, invalid URL)
- **Timeout scenario**: Mock slow response, verify job marked as timed out and other jobs continue

### Manual Testing Steps

1. Start the application: `uv run python main.py` or `uv run streamlit run ui.py`
2. Call the validation endpoint with a set of test jobs:
   ```bash
   curl -X POST http://localhost:8000/api/validate_jobs \
     -H "Content-Type: application/json" \
     -d '{"jobs": [...]}'
   ```
3. Verify response contains valid_jobs and rejected_jobs with correct reason codes
4. Test with a job that has an invalid URL — should be rejected with URL_INVALID
5. Test with a dead job URL — should be rejected with HTTP_ERROR
6. Test with a job posting that's expired (old posting date) — should be rejected with JOB_EXPIRED
7. Verify logs show only summary line like "Validated 5 jobs: 3 passed, 2 rejected"
8. Verify Orchestrator can process the response without errors

## Performance Considerations

- **Timeout per job**: 10 seconds (configurable in `AppConfig`). If 10 jobs all timeout, endpoint could take ~100 seconds; acceptable for async background process, not for synchronous UI request. Monitor and adjust if needed.
- **In-memory caching**: `JobValidator` caches results; revalidating the same URL within a session returns cached result. This improves performance for rescout scenarios.
- **HTTP request overhead**: Each validation makes HTTP request to job URL. Consider adding rate limiting or circuit breaker if scaling to many jobs.

## Migration Notes

This is a refactor, not a backwards-compatible change. The old validation flow (if any exists in CLI) will need to be updated to use the new endpoint and response schema. If Scout is currently calling validation internally, it must be refactored to rely on Orchestrator coordination.

## References

- Job Validator tool: `src/tools/job_validator.py:20-133`
- Current validation endpoint: `src/api/routes/validation.py:14-105`
- Validation node in graph: `src/graph.py:45-77`
- Config: `src/config/settings.py:69-80`
- JobOffer schema: `src/schema/state.py:7-29`
- AgenticHireState: `src/schema/state.py:36-82`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: Refactor Validation Endpoint

#### Automated

- [x] 1.1 Create validation reason enum and rejection schemas
- [x] 1.2 Refactor validation endpoint request/response contracts
- [x] 1.3 Implement per-job timeout handling with reason code assignment
- [x] 1.4 Update validation endpoint logging to summary only
- [x] 1.5 Type checking passes

#### Manual

- [x] 1.6 Endpoint returns correct response for mixed valid/invalid jobs
- [x] 1.7 Timeout jobs marked with VALIDATION_TIMEOUT code
- [x] 1.8 Response schema validates against ValidateJobsResponse

### Phase 2: Integration & Testing

#### Automated

- [x] 2.1 Integration tests for all jobs pass scenario
- [x] 2.2 Integration tests for all jobs fail scenario
- [x] 2.3 Integration tests for mixed results scenario
- [x] 2.4 Integration tests for timeout scenario
- [x] 2.5 Type hints complete, mypy strict passes
- [x] 2.6 All tests passing

#### Manual

- [x] 2.7 Test script simulates Orchestrator calling endpoint
- [x] 2.8 Slow job scenario verified (timeout handling works)

### Phase 3: Documentation & Verification

#### Automated

- [x] 3.1 OpenAPI/Swagger docs generated correctly
- [x] 3.2 No new test failures

#### Manual

- [x] 3.3 Orchestrator can call endpoint and parse response
- [x] 3.4 End-to-end flow verified: Scout → Validate → Orchestrator ready
- [x] 3.5 No regressions in existing features
