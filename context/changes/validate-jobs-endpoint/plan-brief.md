# Validation Endpoint Refactor — Plan Brief

> Full plan: `context/changes/validate-jobs-endpoint/plan.md`

## What & Why

Refactor the job validation endpoint to properly integrate with Scout agent output in the new FastAPI workflow. Currently, validation logic exists but isn't triggered when Scout returns jobs. The Orchestrator agent will orchestrate the flow: Scout returns raw jobs → Orchestrator calls the validation endpoint → receives structured results (valid jobs + detailed rejection reasons) → proceeds to scoring.

## Starting Point

The codebase already has:
- A `JobValidator` tool with proven validation logic (URL check, HTTP accessibility, LLM expiration detection)
- A `POST /api/validate_jobs` endpoint that doesn't properly integrate with Scout
- A LangGraph workflow where validation is a separate node but not triggered on Scout results
- Configuration and caching for validation

What's missing: proper endpoint contract (structured failure reasons, timeout flags, clear response schema) and integration so Orchestrator can call it reliably.

## Desired End State

The validation endpoint:
1. Accepts jobs from Scout (via Orchestrator coordination) in a structured request
2. Validates each job with per-job timeout handling (10s per job configurable)
3. Returns `200 OK` with `{valid_jobs: [...], rejected_jobs: [{id, reason_code, reason_text}]}`
4. Assigns specific failure codes: `URL_INVALID`, `HTTP_ERROR`, `JOB_EXPIRED`, `VALIDATION_TIMEOUT`
5. Handles partial results gracefully (if some jobs timeout, others are still returned)
6. Logs only a summary line ("Validated 10 jobs: 7 passed, 3 rejected")
7. Is ready for Orchestrator to parse and handle results

## Key Decisions Made

| Decision | Choice | Why |
|----------|--------|-----|
| Endpoint style | Synchronous (not async) | 5-10 jobs max, in-memory, simple flow; no job queuing needed |
| Integration | Orchestrator orchestrates the flow | Clean separation: Scout provides jobs, Validate is standalone, Orchestrator coordinates |
| Response on all-fail | Return empty valid_jobs list | Simple, clear signal; rejected_jobs contains all failures with reasons |
| Error communication | Always 200 OK + error details in response | Separates job validation failures from system errors; caller can handle both |
| Failure info returned | Reason code + human-readable text | Programmatic handling for Orchestrator + readability for debugging |
| Timeout handling | Partial results + timeout flag | Don't block on slow jobs; mark them and continue validating others |
| Validation rules | Keep existing (Phase 1) | URL check, HTTP accessibility, LLM expiration already proven; no new rules yet |
| Logging | Minimal summary only | Keeps output clean; no per-job spam |

## Scope

**In scope:**
- Refactor endpoint request/response schemas with structured failure reasons
- Implement per-job timeout handling (catch timeouts, mark as rejected)
- Add validation failure reason enum (URL_INVALID, HTTP_ERROR, JOB_EXPIRED, VALIDATION_TIMEOUT)
- Update logging to summary only
- Comprehensive test coverage for mixed results, timeouts, edge cases
- OpenAPI documentation for the endpoint

**Out of scope:**
- Async/background job queue (synchronous only)
- New validation rules (Phase 1 sticks with existing: URL + HTTP + expiration)
- Backwards compatibility with old CLI flow (full refactor)
- Real-time status updates during validation

## Architecture / Approach

**Endpoint flow:**
```
POST /api/validate_jobs ← Orchestrator calls with Scout jobs
  ↓
For each job (with 10s timeout per job):
  - URL format check
  - HTTP GET request (reject if 400+)
  - LLM expiration detection
  If timeout: mark VALIDATION_TIMEOUT, continue
  If passed: add to valid_jobs
  If failed: add to rejected_jobs with reason_code
  ↓
Return 200 OK: {valid_jobs, rejected_jobs with reason codes}
  ↓
Orchestrator parses response, proceeds to scoring
```

**Reason codes:**
- `URL_INVALID`: URL format check failed
- `HTTP_ERROR`: HTTP GET returned 400+ (job page not accessible)
- `JOB_EXPIRED`: LLM detected expiration signals in page text
- `VALIDATION_TIMEOUT`: Job validation exceeded 10s timeout

## Phases at a Glance

| Phase | What it delivers | Key risk |
|-------|------------------|----------|
| 1. Refactor | New request/response schemas, reason codes, timeout handling, logging | Getting the schema right and timeout edge cases |
| 2. Integration & Testing | Comprehensive tests for all scenarios (pass, fail, mixed, timeout), type safety | Edge cases with mixed results and timeout timing |
| 3. Documentation | OpenAPI docs, verification script, end-to-end validation | Making sure Orchestrator can actually call it without issues |

**Prerequisites:** FastAPI server running, `JobValidator` tests passing (proven validation logic)
**Estimated effort:** ~2-3 sessions across 3 phases; Phase 1 is heaviest (schemas + timeout logic), Phases 2-3 lighter

## Open Risks & Assumptions

- **Timeout duration**: Assumed 10s per job is acceptable. If Scout returns many slow jobs, endpoint could take minutes. Monitor in production.
- **Partial results**: Assuming Orchestrator can handle "some jobs validated, some timed out" response. If Orchestrator requires all-or-nothing, this needs adjustment.
- **LLM availability**: Expiration detection relies on LLM calls. If LLM is slow/unavailable, jobs time out. No fallback strategy yet.
- **Caching behavior**: In-memory cache means results are lost on process restart. Fine for now, but consider persistence later if needed.

## Success Criteria (Summary)

- Orchestrator can call `POST /api/validate_jobs` with Scout output and receive a valid response with proper status codes
- Endpoint handles mixed scenarios: some jobs pass, some fail with specific reason codes
- Timeout jobs are rejected gracefully without blocking others
- Logs show clean summary, no spam or missing details
- All automated tests pass; type checking strict; no regressions
