<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Validate jobs endpoint

- **Plan**: context/changes/validate-jobs-endpoint/plan.md
- **Scope**: All Phases (1–3 of 3)
- **Date**: 2026-05-26
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical  6 warnings  4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — No upper bound on `jobs` list

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/schemas.py:63
- **Detail**: ValidateJobsRequest.jobs has no max_length. A caller can submit thousands of jobs; each triggers one HTTP GET + one LLM retry loop. Sequential processing means this could run for hours and exhaust LLM quota or file descriptors.
- **Fix**: Add max_length to the Field (e.g. max_length=50). The plan already states "typically 5–10 MAX". Enforce that as a schema constraint so the endpoint rejects oversized payloads with 422.
- **Decision**: PENDING

### F2 — Sequential validation loop blocks throughput

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/validation.py:99–104
- **Detail**: Jobs are validated one-at-a-time via a serial for-loop. Total latency = sum of all per-job latencies. With 10 jobs × 25 s each, the endpoint takes ~250 s.
- **Fix A ⭐ Recommended**: Use asyncio.gather with a semaphore
  - Strength: Cuts wall-clock time from sum to max, without changing synchronous response contract.
  - Tradeoff: Slightly harder to test ordering; semaphore adds 3 lines.
  - Confidence: HIGH — asyncio.gather is idiomatic; existing tests pass with minor result unpacking.
  - Blind spot: None significant.
- **Fix B**: Leave sequential, add comment + config-driven max_jobs
  - Strength: Zero regression risk; acceptable if Orchestrator always sends ≤5 jobs.
  - Tradeoff: Latency stays proportional to job count.
  - Confidence: MEDIUM — depends on Orchestrator usage patterns.
  - Blind spot: Orchestrator max-jobs limit not yet enforced anywhere.
- **Decision**: PENDING

### F3 — `reason_code or HTTP_ERROR` silently mis-labels future rejects

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/validation.py:63
- **Detail**: result.reason_code is Optional. The `or HTTP_ERROR` fallback means any future code path returning is_valid=False with reason_code=None silently emits HTTP_ERROR, misleading the Orchestrator.
- **Fix**: Add explicit logger.error before the fallback when reason_code is None. Keeps current behavior but makes the gap visible.
- **Decision**: PENDING

### F4 — `_invoke_llm_with_retry` uses bare `except Exception` (lessons.md violation)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/tools/job_validator.py:171–179
- **Detail**: Retry loop catches bare Exception, violating the project's lessons.md rule. A TypeError from a misconfigured checker is silently retried then returns None, making a broken config look like a normally-expired job.
- **Fix A ⭐ Recommended**: Split into retryable vs. non-retryable exceptions
  - Strength: Aligns with lessons.md; lets misconfiguration surface immediately.
  - Tradeoff: Need to identify which LangChain/OpenRouter exceptions are transient.
  - Confidence: HIGH — pattern already used elsewhere in repo for network errors.
  - Blind spot: OpenRouter-specific rate-limit exceptions not mapped yet.
- **Fix B**: Keep broad catch but add exc_info and a type-check comment
  - Strength: Zero regression risk; improves observability immediately.
  - Tradeoff: Does not fix the lessons.md violation in spirit.
  - Confidence: HIGH — trivial change.
  - Blind spot: Future maintainers may still add bad code here.
- **Decision**: PENDING

### F5 — Timeout test uses 0.01 s — risk of CI flake

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_validate_jobs_endpoint.py:165
- **Detail**: patch("...._PER_JOB_TIMEOUT_S", 0.01) — 10 ms may not reliably cancel a mock dispatched through Starlette's TestClient thread + event loop on slow CI runners.
- **Fix**: Change 0.01 to 0.1 (100 ms). Add comment: "# Short enough to timeout, long enough for slow CI"
- **Decision**: PENDING

### F6 — No test for unexpected exception from validator (→ unhandled 500)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: tests/test_validate_jobs_endpoint.py (missing)
- **Detail**: validate_job_with_reason() intentionally does not catch bare Exception. A RuntimeError propagates through _validate_single_job uncaught and FastAPI returns 500. This may be correct for visibility but is undocumented and untested.
- **Fix A ⭐ Recommended**: Add a test that documents the 500 behavior
  - Strength: Makes the intentional "let it crash" contract explicit; prevents accidental swallowing later.
  - Tradeoff: Codifies 500-on-unexpected as the designed behavior.
  - Confidence: HIGH — test is trivial; just needs a decision.
  - Blind spot: None significant.
- **Fix B**: Catch Exception in _validate_single_job, map to rejected job with UNKNOWN code
  - Strength: Never returns 500; consistent "always-200" promise.
  - Tradeoff: Hides infrastructure failures; violates lessons.md bare-except rule.
  - Confidence: MEDIUM — depends on Orchestrator's tolerance for 500s.
  - Blind spot: Would need a new INTERNAL_ERROR reason code.
- **Decision**: PENDING

### F7 — Magic timeout buffer (+15 s) not derived from config

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/validation.py:23
- **Detail**: +15 s is not derived from validator_max_retries. With 2 retries × 25 s LLM the real max is ~61 s; the 25 s total can under-budget.
- **Fix**: Add a comment explaining the arithmetic, or expose as its own config field `validator_job_timeout_s` in AppConfig.
- **Decision**: PENDING

### F8 — is_job_valid broad except undocumented deviation from lessons.md

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/tools/job_validator.py:144–149
- **Detail**: is_job_valid() uses bare except Exception for backward-compat. The docstring explains the purpose but doesn't cite the lessons.md deviation. Future reviewers won't know this is an approved exception.
- **Fix**: Add inline comment: `# Backward-compat shim: graph node expects bool, not exception. New callers use validate_job_with_reason() directly.`
- **Decision**: PENDING

### F9 — Cached rejections always surface as HTTP_ERROR (loses original reason code)

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/tools/job_validator.py:59–63
- **Detail**: Cache stores Dict[str, bool]. A job originally rejected as JOB_EXPIRED returns HTTP_ERROR from cache on the second request. Inconsistent reason codes may confuse Orchestrator.
- **Fix**: Extend cache to store Optional[ValidationFailureReason] alongside the bool.
- **Decision**: PENDING

### F10 — SSRF: no validation blocks internal IPs in job URLs

- **Severity**: OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/schema/state.py (JobOffer.url), src/api/schemas.py:63
- **Detail**: JobOffer.url is a plain str with only a startswith("http") check. A caller can submit http://169.254.169.254/ or http://localhost:5432/ and the validator will make an outbound GET — classic SSRF. The API requires JWT so risk is limited to compromised accounts.
- **Fix**: Use pydantic's AnyHttpUrl type for url in JobOffer, or add a validator that rejects RFC-1918/loopback addresses. At minimum document the trust assumption in the endpoint docstring.
- **Decision**: PENDING
