<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Data Integrity Integration Tests

- **Plan**: `context/changes/testing-data-integrity/plan.md`
- **Scope**: All 4 phases
- **Date**: 2026-06-01
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 4 observations

## Verdicts

| Dimension | Verdict |
|---|---|
| Plan Adherence | WARNING |
| Scope Discipline | WARNING |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — asyncio_default_fixture_loop_scope missing from pyproject.toml

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `pyproject.toml:38–40`
- **Detail**: The plan's Critical Implementation Details specified both `asyncio_mode = "auto"` AND `asyncio_default_fixture_loop_scope = "session"`. Only the first was added. The key was dropped when the fixture architecture switched to sync `asyncio.run()` for schema setup. Tests pass without it, but pytest-asyncio 0.24+ emits a deprecation warning about the default loop scope not being explicitly configured.
- **Fix**: Add `asyncio_default_fixture_loop_scope = "function"` (matching actual runtime behaviour — each test uses its own function-scoped loop) to silence the deprecation warning.
- **Decision**: PENDING

### F2 — Unplanned model + migration changes not documented in plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Scope Discipline
- **Location**: `src/db/models.py`, `alembic/versions/a1b2c3d4e5f6_*.py`
- **Detail**: Three unplanned changes landed in `src/db/models.py`: (a) removal of duplicate `index=True` flags where `__table_args__` already declared the same index; (b) all `DateTime` columns changed to `DateTime(timezone=True)`; (c) defaults changed from `datetime.utcnow` to `lambda: datetime.now(timezone.utc)`. A new Alembic migration was also added. These changes are correct and necessary (asyncpg 0.31.0 rejects timezone-aware datetimes for `TIMESTAMP WITHOUT TIME ZONE` columns — fixing a production silent persistence failure) but are not described in the plan. Migration coverage is complete (all 9 DateTime columns across 6 tables), revision chain is correct, USING AT TIME ZONE 'UTC' cast is safe.
- **Fix A ⭐ Recommended**: Add a short addendum to `plan.md` noting the three model changes and migration as a discovered-scope addition, so future reviewers understand the divergence.
  - Strength: Source of truth reflects what shipped; plan addendum is the established pattern here.
  - Tradeoff: Minor — plan was already approved.
  - Confidence: HIGH
  - Blind spot: None significant; migration is self-documenting.
- **Fix B**: Leave as-is — migration docstring is sufficient.
  - Strength: No extra writing.
  - Tradeoff: Documentation debt; future reviewers miss the model change context.
  - Confidence: LOW
  - Blind spot: None.
- **Decision**: PENDING

### F3 — async_client_a/b fixtures use dependency_overrides.clear() in teardown

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/integration/conftest.py:167, 180`
- **Detail**: Both `async_client_a` and `async_client_b` call `app.dependency_overrides.clear()` in teardown. No current test uses both fixtures simultaneously (isolation tests use the `_get_jobs()` helper instead), so this is not a live failure. But if a future test declares both as parameters, the second fixture's teardown wipes the first fixture's still-active overrides mid-test, causing hard-to-diagnose auth failures.
- **Fix**: Replace `app.dependency_overrides.clear()` with `app.dependency_overrides.pop(get_current_user, None)` and `app.dependency_overrides.pop(get_db, None)` in each fixture's teardown so each only removes the keys it owns.
- **Decision**: PENDING

### F4 — Cross-user job ID collision has no log visibility

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `src/db/repositories.py:139`
- **Detail**: The ownership check in `create_or_update` returns early when `existing_job.user_id != job.user_id`, silently discarding the write. Correct behaviour, but cross-user ID collisions are invisible in production logs.
- **Fix**: Add `logger.warning(f"create_or_update: job {job.id} already owned by a different user; ignoring write from user {job.user_id}")` before the early return.
- **Decision**: PENDING

### F5 — _get_jobs helper's non-context-manager aclose() needs a clarifying comment

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `tests/integration/test_user_isolation.py:38–47`
- **Detail**: `AsyncClient` is created without `async with` (intentional — avoids triggering FastAPI lifespan) and `aclose()` is called manually. The pattern is safe (response is fully awaited before `aclose()`), but future readers familiar with httpx best practice may flag it as a resource leak.
- **Fix**: Add a comment above the `AsyncClient(...)` line: `# not used as context manager — avoids triggering FastAPI lifespan (init_db) which would connect to the dev DB`.
- **Decision**: PENDING

### F6 — Fixture decorator style inconsistency (integration vs root conftest)

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/integration/conftest.py` vs `tests/conftest.py`
- **Detail**: Root conftest uses `@pytest_asyncio.fixture`; integration conftest uses bare `@pytest.fixture`. Both are valid with `asyncio_mode = "auto"` but look inconsistent.
- **Fix**: Add a one-line header comment in the integration conftest noting `# asyncio_mode = "auto": bare @pytest.fixture works for async fixtures`, or align all fixtures to `@pytest.fixture`.
- **Decision**: PENDING

### F7 — Migration upgrade/downgrade functions lack docstrings

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `alembic/versions/a1b2c3d4e5f6_*.py:28, 60`
- **Detail**: Prior migration (`6cfe28947e05`) has `"""Upgrade schema."""` / `"""Downgrade schema."""` docstrings; new migration omits them.
- **Fix**: Add matching docstrings to `upgrade()` and `downgrade()`.
- **Decision**: PENDING
