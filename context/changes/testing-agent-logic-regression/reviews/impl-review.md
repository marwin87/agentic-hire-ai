<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Agent Logic Regression Tests

- **Plan**: context/changes/testing-agent-logic-regression/plan.md
- **Scope**: All Phases (1–3)
- **Date**: 2026-06-05
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical  3 warnings  4 observations

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

### F1 — Off-by-one test doesn't isolate what it claims

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: tests/test_graph.py:109-126
- **Detail**: test_should_rescout_one_below_max_valid_jobs sets scout_runs=0. should_rescout has an "OR scout_runs == 0" branch that returns "rescout" regardless of valid_jobs count — so the test passes due to that independent branch, not the valid_jobs off-by-one boundary it claims to verify. A regression in the valid_jobs comparison (< → <=) would not be caught.
- **Fix**: Change scout_runs=0 to scout_runs=1 so the scout_runs==0 short-circuit is inactive and valid_jobs count drives the result. Matches the boundary isolation used in test_should_rescout_one_below_max_scout_runs (scout_runs=2, not 0).
  - Strength: One-line change; directly isolates the condition under test.
  - Tradeoff: None significant.
  - Confidence: HIGH — should_rescout logic is fully readable.
  - Blind spot: None significant.
- **Decision**: PENDING

### F2 — Retry exhaustion test missing no-raise contract assertion

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_validator_async.py:308-335
- **Detail**: Docstring says "must not raise" but there is no pytest.raises guard or assertion enforcing this. If validate_job_with_reason starts raising on exhaustion, pytest reports it as ERROR rather than FAILURE — the no-raise contract is implicit, not explicit.
- **Fix**: Wrap the call in `pytest.does_not_raise()` or add a comment clarifying that pytest itself is the no-raise guard.
- **Decision**: PENDING

### F3 — Redundant @pytest.mark.asyncio decorators on new tests

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_validator_async.py:269, 308 / tests/integration/test_rag_retrieval.py:29
- **Detail**: pyproject.toml sets asyncio_mode = "auto"; decorators are harmless but mislead readers into thinking they're required. Pre-existing tests also carry this pattern; the new tests continue the inconsistency.
- **Fix**: Remove @pytest.mark.asyncio from the three new tests.
- **Decision**: PENDING

### F4 — Vacuous duration_ms assertion (pre-existing)

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_validator_async.py:207
- **Detail**: assert result.duration_ms >= 0 is always true. Pre-existing code, not introduced in this change.
- **Decision**: PENDING

### F5 — Deferred imports inside async test functions (pre-existing)

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_graph.py:159, 225
- **Detail**: from unittest.mock import AsyncMock inside test bodies rather than at file top. Pre-existing pattern.
- **Decision**: PENDING

### F6 — Redundant flush after bulk_insert (new code)

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/integration/test_rag_retrieval.py:53
- **Detail**: CVEmbeddingRepository.bulk_insert internally calls flush(), so the explicit await real_session.flush() on line 54 is a no-op. Harmless noise.
- **Decision**: PENDING

### F7 — type: ignore[attr-defined] on user_a.id

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/integration/test_rag_retrieval.py:39
- **Detail**: Suppressed with type: ignore[attr-defined]. Check test_user_isolation.py — if they use the same suppression, this is consistent; if not, the User.id type annotation may be fixable upstream.
- **Decision**: PENDING
