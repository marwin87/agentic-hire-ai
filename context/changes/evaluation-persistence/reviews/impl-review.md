<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Evaluation Persistence

- **Plan**: context/changes/evaluation-persistence/plan.md
- **Scope**: All 3 phases
- **Date**: 2026-06-01
- **Verdict**: APPROVED (post-triage)
- **Findings**: 0 critical · 2 warnings · 2 observations (1 skipped)

## Verdicts

| Dimension | Verdict |
|---|---|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS (fixed) |
| Architecture | PASS |
| Pattern Consistency | PASS (fixed) |
| Success Criteria | PASS |

## Findings

### F1 — Missing session.rollback() on persistence failure

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/workflows.py (both persistence except blocks)
- **Detail**: Both except blocks logged and continued without calling session.rollback(). Session left dirty on commit failure — next SQLAlchemy op could raise InvalidRequestError. Violates lessons.md rule and search.py reference pattern.
- **Fix**: Added `await session.rollback()` as first line of each persistence except block (sync + streaming).
- **Decision**: FIXED

### F2 — datetime.utcnow() in EvaluationRepository.upsert()

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/db/repositories.py:308
- **Detail**: New upsert() used datetime.utcnow() (deprecated Python 3.12+, naive datetime). Project tests use datetime.now(UTC) consistently.
- **Fix**: Replaced with `datetime.now(timezone.utc)`, added `timezone` to imports.
- **Decision**: FIXED

### F3 — No test coverage for streaming endpoint persistence

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: tests/test_routes_workflows.py
- **Detail**: Two new tests covered only the sync endpoint. Streaming run_graph() inner function had same persistence logic but zero test coverage — it's the path the frontend actually uses.
- **Fix**: Added test_stream_endpoint_persists_evaluations_for_shortlisted_jobs using httpx.AsyncClient + ASGITransport + async mock_astream generator. Asserts upsert.call_count == 2 after consuming full SSE stream.
- **Decision**: FIXED

### F4 — Migration has no deduplication guard

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: alembic/versions/6cfe28947e05_...py:24
- **Detail**: Migration adds unique constraint with no pre-dedup DELETE. Documented in plan Migration Notes. Low risk for fresh dev DB.
- **Decision**: SKIPPED (plan note sufficient)
