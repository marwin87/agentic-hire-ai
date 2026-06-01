# Data Integrity Integration Tests Implementation Plan

## Overview

Add the first real-DB integration test layer this project has ever had. The change covers: async test infrastructure (SAVEPOINT-backed session, two-user fixtures), fixes for all three user_id isolation gaps in the repository layer, and four integration tests proving Risks #1 and #2 from `context/foundation/test-plan.md` Phase 1.

## Current State Analysis

The entire test suite uses `AsyncMock(spec=AsyncSession)` — zero SQL ever runs in any existing test. Both workflow endpoints persist evaluations but swallow all DB exceptions silently; the API response cannot distinguish "persisted" vs "returned from in-memory graph result." Three repository methods lack user_id isolation:

- `JobRepository.create_or_update` (`src/db/repositories.py:130–148`) — lookup is `WHERE Job.id == job.id` only; no ownership check. Actively exploitable via `/api/scout` and `/api/workflows/search-jobs`.
- `JobRepository.get_by_id` (`src/db/repositories.py:151–154`) — `WHERE id = job_id` only. Latent (no current route calls it).
- `EvaluationRepository.get_by_job_id` (`src/db/repositories.py:252–257`) — `WHERE job_id = job_id` only. Latent (no current route calls it).

Available infrastructure: `pytest-asyncio>=0.24.0`, `httpx>=0.28.0`, `asyncpg>=0.30.0`, `sqlalchemy[asyncio]>=2.0.25` all installed. Auth override pattern (`app.dependency_overrides[get_current_user]`) and `httpx.AsyncClient` with `ASGITransport` already used in `tests/test_routes_workflows.py:203`.

## Desired End State

- `uv run pytest tests/integration/ -v` runs 4 green integration tests with a real PostgreSQL connection.
- `JobRepository.create_or_update` refuses to overwrite another user's row; `get_by_id` and `get_by_job_id` require a `user_id` parameter.
- `GET /api/jobs` after a workflow run returns non-null `match_score` for each shortlisted job (proves DB write, not just API response JSON).
- A request authenticated as user B cannot see or modify user A's job rows.
- Full test suite (`uv run pytest`) stays green; mypy passes.

### Key Discoveries

- `src/api/routes/workflows.py:159–193` — non-streaming persistence block: single `await session.commit()` after both loops; bare `except Exception` swallows all failures
- `src/api/routes/workflows.py:416–450` — streaming persistence block: same pattern inside `run_graph()`; persistence completes before the `workflow_complete` SSE frame is enqueued
- `src/db/repositories.py:179–201` — `get_jobs_with_scores` is correctly scoped (`WHERE Job.user_id = user_id`) — this is the "page reload" assertion target
- `tests/test_routes_workflows.py:203` — established `dependency_overrides[get_current_user]` pattern to reuse
- `pyproject.toml:38–40` — `[tool.pytest.ini_options]` currently has only `pythonpath = ["."]`
- `tests/conftest.py:14–24` — existing `db_session` fixture returns `AsyncMock`, not a real session

## What We're NOT Doing

- Testing Risk #3 (streaming zombie on SSE disconnect) — that is Phase 3 of the test rollout
- Testing Risk #4 (secrets in error responses) — that is Phase 4
- Testing the LangGraph graph execution itself — `build_graph` is mocked in all integration tests; we are testing DB layer and HTTP isolation, not LLM behavior
- Replacing existing mocked unit tests — integration tests sit alongside them in `tests/integration/`
- Adding a dedicated "GET /api/jobs/{id}" route — Gaps 2 & 3 are fixed defensively, but no new route is added

## Implementation Approach

Four phases, each verifiable before the next begins:
1. **Infrastructure** — pytest config + test DB + `tests/integration/conftest.py` with SAVEPOINT-backed session and two-user HTTP client fixtures
2. **Repository fixes** — add user_id ownership checks to all three unscoped methods
3. **Risk #1 tests** — two tests (sync + streaming) proving evaluation rows exist in the DB after a workflow run
4. **Risk #2 tests** — two tests proving user B cannot list or corrupt user A's data

## Critical Implementation Details

- **`asyncio_default_fixture_loop_scope = "session"`** must be set alongside `asyncio_mode = "auto"` in `pyproject.toml`. Without it, pytest-asyncio 0.24 raises a deprecation error for session-scoped async fixtures that share the event loop.
- **`join_transaction_mode="create_savepoint"`** on `AsyncSession` is mandatory for the SAVEPOINT isolation strategy. With this parameter, `session.commit()` inside the production endpoint commits to a savepoint (not the outer connection transaction). After the test, `await conn.rollback()` rolls back the outer transaction, undoing all inserts from that test. Without this parameter, `session.commit()` commits the outer transaction and the rollback has no effect — the DB would accumulate test data.
- **`get_db` override shape**: the production `get_db` in `src/api/dependencies.py:33–44` is not a generator — it returns a session directly. The override is `app.dependency_overrides[get_db] = lambda: real_session`. If implementation reveals `get_db` is an async generator, use `async def override_get_db(): yield real_session` instead.
- **Streaming graph mock**: `graph.astream()` is an async generator. To mock it, assign an `async def` function (using `async def` + `yield`) directly to `mock_graph.astream` — do not use `AsyncMock.return_value` for async generators, as that produces an `AsyncMock` object rather than an async iterable.

---

## Phase 1: Test Infrastructure

### Overview

Configure pytest for async, create a separate test database, and build the `tests/integration/conftest.py` fixture stack: session-scoped engine (schema setup/teardown), function-scoped SAVEPOINT session (per-test rollback), persisted `user_a`/`user_b` fixtures, and two authenticated HTTP clients.

### Changes Required

#### 1. pytest configuration

**File**: `pyproject.toml`

**Intent**: Enable `asyncio_mode = "auto"` so async test functions and fixtures don't need `@pytest.mark.asyncio`, and set `asyncio_default_fixture_loop_scope = "session"` so the session-scoped engine fixture shares the event loop with function-scoped tests.

**Contract**: Add two keys under `[tool.pytest.ini_options]`:
```
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
```

#### 2. Test database environment variable

**File**: `.env.test` (new file, add to `.gitignore`)

**Intent**: Supply a separate `TEST_DATABASE_URL` pointing at `agentic_hire_test` so integration tests never touch the dev database. The database itself must be created manually once (`CREATE DATABASE agentic_hire_test;` on the same PostgreSQL instance as the dev DB).

**Contract**: One line: `AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire_test`. Conftest reads it via `os.environ` (caller exports `AGENTIC_HIRE_DATABASE_URL` before running integration tests, or the CI/CD pipeline sets it). Add `.env.test` to `.gitignore`.

#### 3. Integration test conftest

**File**: `tests/integration/conftest.py` (new file)

**Intent**: Build the entire fixture stack that integration tests depend on: a session-scoped engine that owns schema lifecycle, a function-scoped SAVEPOINT session that isolates each test, two user fixtures, and two HTTP client fixtures authenticated as each user.

**Contract**: Five fixtures, in dependency order:

**`test_engine`** — `scope="session"`, async. Creates `create_async_engine(TEST_DATABASE_URL)`. In setup: executes `CREATE EXTENSION IF NOT EXISTS vector` then `Base.metadata.create_all` on the engine. In teardown: `Base.metadata.drop_all`, then `await engine.dispose()`. Import `Base` from `src.db.models` (or wherever `declarative_base()` is defined) and `text` from `sqlalchemy`.

**`real_session`** — `scope="function"`, async. Opens a connection from `test_engine`, begins an outer transaction (`await conn.begin()`), then creates `AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")`. Yields the session. In teardown: `await session.close()`, then `await conn.rollback()` (rolls back the outer transaction, undoing all test inserts). The `join_transaction_mode` is load-bearing — see Critical Implementation Details.

**`user_a`** — `scope="function"`, async. Calls `UserRepository.create(real_session, email="integration_user_a@test.com", password_hash="<any_bcrypt_hash>")` then `await real_session.flush()`. Returns the `User` ORM object. The `password_hash` value is irrelevant — `get_current_user` is overridden in tests so the JWT is never decoded.

**`user_b`** — `scope="function"`, async. Same pattern with `email="integration_user_b@test.com"`.

**`async_client_a`** and **`async_client_b`** — `scope="function"`, async. Each fixture overrides `get_current_user` (returns the respective user) and `get_db` (returns `real_session`) on the FastAPI `app`. Creates an `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` as an async context manager and yields the client. In teardown: `app.dependency_overrides.clear()`. Import `app` from `src.main` (or wherever the FastAPI app is defined), `get_current_user` from `src.api.dependencies`, and `get_db` from `src.api.dependencies`.

### Success Criteria

#### Automated Verification

- `uv run pytest tests/integration/ -v` collects fixtures without error (even with no test files, just the conftest, running `pytest --collect-only` on the directory returns exit 0 or "no tests ran")
- Write one smoke test `tests/integration/test_smoke.py` with `async def test_db_connection(real_session): assert real_session is not None` — this test must pass, proving the test engine connects to the test DB
- `uv run pytest` (full suite) still passes — existing mocked tests are unaffected

#### Manual Verification

- Run `uv run pytest tests/integration/test_smoke.py -v -s` and confirm it prints a success line and the DB connection was real (add a `logger.info(await real_session.execute(text("SELECT 1")))` in the smoke test if needed)
- Confirm `agentic_hire_test` database exists and the tables were created (`\dt` in psql on the test DB)

**Implementation Note**: The test DB must exist before Phase 1 verification. One-time setup: `psql -U agentic_hire -c "CREATE DATABASE agentic_hire_test;"`. If psql credentials differ, adjust. Only proceed to Phase 2 after the smoke test is green.

---

## Phase 2: Repository Isolation Fixes

### Overview

Fix all three unscoped repository methods in `src/db/repositories.py`. No callers exist for Gaps 2 and 3, so signature changes are safe. The `create_or_update` fix changes behavior: if a job ID exists under a different user_id, the method no longer overwrites that row — it treats the lookup as a miss and inserts a new row for the correct user.

### Changes Required

#### 1. `JobRepository.create_or_update` — add user_id ownership check

**File**: `src/db/repositories.py:130–148`

**Intent**: Make the lookup check both `job.id` and `job.user_id` so that a job belonging to user A is never selected (and therefore never overwritten) when user B submits a job with the same external ID.

**Contract**: Change the `select(Job).where(...)` clause from `where(Job.id == job.id)` to `where(Job.id == job.id, Job.user_id == job.user_id)`. The update branch and insert branch remain unchanged — only the lookup predicate gains the ownership filter.

#### 2. `JobRepository.get_by_id` — add user_id parameter

**File**: `src/db/repositories.py:151–154`

**Intent**: Close the latent gap so that any future route using this method is forced to supply a user_id — preventing accidental cross-user data return.

**Contract**: Add a required `user_id: UUID` parameter to the method signature. Add `Job.user_id == user_id` to the `WHERE` clause. No existing callers — mypy will confirm this.

#### 3. `EvaluationRepository.get_by_job_id` — add user_id parameter

**File**: `src/db/repositories.py:252–257`

**Intent**: Same as above — close the latent gap before any route reaches for this method.

**Contract**: Add a required `user_id: UUID` parameter. Add `Evaluation.user_id == user_id` to the `WHERE` clause. No existing callers — mypy will confirm this.

### Success Criteria

#### Automated Verification

- Type checking passes: `uv run mypy src/`
- Full test suite passes: `uv run pytest` (no existing caller breaks)

#### Manual Verification

- No tests are skipped or marked xfail

**Implementation Note**: After mypy and the full suite pass, verify there are no callers of `get_by_id` or `get_by_job_id` elsewhere in the codebase (`grep -rn "get_by_id\|get_by_job_id" src/`). If any caller is found, update its call site to pass `user_id` before proceeding to Phase 3.

---

## Phase 3: Risk #1 Integration Tests — Evaluation Persistence

### Overview

Two tests in `tests/integration/test_evaluation_persistence.py`: one for the sync endpoint, one for the streaming endpoint. Each mocks `build_graph` to return a canned shortlisted job, calls the workflow endpoint, then queries `GET /api/jobs` as the same user and asserts `match_score` is non-null. This proves the DB write survived — not just that the API returned scores in the response JSON.

### Changes Required

#### 1. Sync endpoint persistence test

**File**: `tests/integration/test_evaluation_persistence.py` (new file)

**Intent**: Prove that after `POST /api/workflows/search-jobs` completes, the shortlisted job has a non-null `match_score` row in the `evaluations` table, visible via `GET /api/jobs`.

**Contract**: `async def test_sync_workflow_persists_match_score_to_db(async_client_a, real_session, user_a)`. Use `@patch("src.api.routes.workflows.build_graph")` to return an `AsyncMock` whose `ainvoke` resolves to a cast `AgenticHireState` dict containing:
- `shortlisted_jobs`: list with one `JobOffer` (set `id`, `match_score=0.85`, `analysis="test reasoning"`)
- `applications`: `{job.id: {"founded_job_offer": "test summary"}}`
- `valid_jobs`, `found_jobs`, `rejected_jobs`, `seen_jobs`, `scout_runs`, `status` filled with valid defaults

The `JobOffer.id` must be a string that doesn't already exist in the test DB (use a UUID or timestamp-based string). After calling `await async_client_a.post("/api/workflows/search-jobs", json={...})`, call `await async_client_a.get("/api/jobs")`. Find the job by `id` in the response JSON. Assert `match_score` is not `None` and equals `0.85` (within float tolerance).

The request body for `POST /api/workflows/search-jobs` must include whatever fields the `WorkflowRequest` schema requires (e.g., `initial_prompt`, `max_valid_offers`). Check the route's request model to confirm required fields.

#### 2. Streaming endpoint persistence test

**File**: `tests/integration/test_evaluation_persistence.py` (append to same file)

**Intent**: Prove the streaming endpoint's persistence block also commits — the persistence runs inside `run_graph()` before the `workflow_complete` SSE frame, so consuming the full SSE stream guarantees the DB write is complete before the test checks the DB.

**Contract**: `async def test_streaming_workflow_persists_match_score_to_db(async_client_a, real_session, user_a)`. Same `build_graph` patch, but mock `graph.astream` instead of `graph.ainvoke`. `graph.astream` is an async generator — assign a proper `async def` generator function to `mock_graph.astream` (do not use `AsyncMock.return_value`):

```python
async def fake_astream(*args, **kwargs):
    yield {"orchestrator": {/* node output matching the state schema */}}
    yield {"tailor": {/* node output */}}
```

The streamed node outputs must be valid enough for the route's accumulator logic to populate `acc["shortlisted_jobs"]` and `acc["applications"]`. Trace `src/api/routes/workflows.py:389–411` for the accumulator shape.

Consume the SSE stream using `async_client_a.stream("POST", "/api/workflows/search-jobs/stream", json={...})`. Iterate `response.aiter_lines()` until the line containing `"workflow_complete"` is seen, then break. After the stream completes, call `GET /api/jobs` and assert `match_score` is non-null — same assertion as the sync test.

### Success Criteria

#### Automated Verification

- New tests pass: `uv run pytest tests/integration/test_evaluation_persistence.py -v`
- Full suite passes: `uv run pytest`
- Type checking passes: `uv run mypy src/`

#### Manual Verification

- Both tests pass without `xfail` or `skip`
- Run with `-s` to confirm the test actually hits the DB (`uv run pytest tests/integration/test_evaluation_persistence.py -v -s`)

**Implementation Note**: If the streaming SSE accumulator logic in `workflows.py` is complex to replicate in the mock, consider adding a minimal helper in the test that constructs the expected state dict from the final `workflow_complete` event. The key invariant is that `acc["shortlisted_jobs"]` and `acc["applications"]` are populated before the persistence block runs.

---

## Phase 4: Risk #2 Integration Tests — User Isolation

### Overview

Two tests in `tests/integration/test_user_isolation.py`: one proving `GET /api/jobs` scopes results to the authenticated user, one proving `create_or_update` no longer overwrites another user's job. The second test exercises the repository directly (no HTTP mock needed) — the isolation fix is in the repository, so repository-level testing is the right assertion layer.

### Changes Required

#### 1. List isolation test

**File**: `tests/integration/test_user_isolation.py` (new file)

**Intent**: Prove that user B's `GET /api/jobs` returns zero results when only user A has jobs in the DB.

**Contract**: `async def test_job_list_scoped_to_authenticated_user(async_client_a, async_client_b, real_session, user_a, user_b)`. Seed one job for user A directly via `JobRepository.create_or_update(real_session, job_a)` where `job_a.user_id = user_a.id`. Call `await real_session.flush()`. Then call `await async_client_b.get("/api/jobs")`. Assert the response items list is empty (no jobs visible to user B). Also verify that `await async_client_a.get("/api/jobs")` returns exactly one item with the seeded job's ID — confirming user A's data is intact.

#### 2. Cross-user write protection test

**File**: `tests/integration/test_user_isolation.py` (append)

**Intent**: Prove that after the `create_or_update` fix, user B cannot overwrite user A's job row by submitting a job with the same external ID.

**Contract**: `async def test_create_or_update_cannot_overwrite_another_users_job(real_session, user_a, user_b)`. This test operates at the repository layer — no HTTP client needed.

Step 1: seed user A's job via `JobRepository.create_or_update(real_session, job_a)` where `job_a.user_id = user_a.id` and `job_a.title = "User A Original Title"`. Call `await real_session.flush()`.

Step 2: construct `job_b_attempt` — a `Job` ORM object with `id = job_a.id` (same external ID) but `user_id = user_b.id` and `title = "User B Attack Title"`. Call `JobRepository.create_or_update(real_session, job_b_attempt)`. Call `await real_session.flush()`.

Step 3: fetch user A's job: `result = await real_session.execute(select(Job).where(Job.id == job_a.id, Job.user_id == user_a.id))`. Assert `result.scalar_one().title == "User A Original Title"` — user A's row must be unchanged.

This test is red before Phase 2 (the old lookup overwrites user A's row) and green after Phase 2 (the new lookup misses user A's row).

### Success Criteria

#### Automated Verification

- New tests pass: `uv run pytest tests/integration/test_user_isolation.py -v`
- Full suite passes: `uv run pytest`
- Type checking passes: `uv run mypy src/`

#### Manual Verification

- Both tests pass without `xfail` or `skip`
- Confirm test 2 would fail against the unfixed `create_or_update` by temporarily reverting the Phase 2 change and re-running — then restore the fix

**Implementation Note**: The cross-user write protection test is a regression guard for the Phase 2 fix. Running it before Phase 2 (or after reverting Phase 2) should produce a red test, proving the test catches the gap. Document this in a comment inside the test.

---

## Testing Strategy

### Integration Tests

- `test_sync_workflow_persists_match_score_to_db` — Risk #1 (sync path); mocked graph, real DB assertion
- `test_streaming_workflow_persists_match_score_to_db` — Risk #1 (streaming path); mocked graph, real DB assertion
- `test_job_list_scoped_to_authenticated_user` — Risk #2 (list isolation); HTTP layer
- `test_create_or_update_cannot_overwrite_another_users_job` — Risk #2 (write protection); repository layer

### Manual Testing Steps

1. Create the test DB: `psql -U agentic_hire -c "CREATE DATABASE agentic_hire_test;"`
2. Export the env var: `export AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire_test`
3. Run Phase 1 smoke test: `uv run pytest tests/integration/test_smoke.py -v -s`
4. After Phase 2: run `uv run mypy src/` and `uv run pytest`
5. After Phase 3: run `uv run pytest tests/integration/test_evaluation_persistence.py -v`
6. After Phase 4: run `uv run pytest tests/integration/ -v` (all 4 integration tests green)
7. Run full suite: `uv run pytest` — confirm no regressions

## Migration Notes

The test database is ephemeral: `Base.metadata.create_all` at session start, `Base.metadata.drop_all` at teardown. No Alembic migrations are run against the test DB — the ORM models define the schema directly. If the ORM models and migrations diverge, the test DB schema will reflect the ORM, not the migration state. This is acceptable for integration tests targeting repository and route behavior (not migration correctness).

The pgvector extension must be present on the `agentic_hire_test` database. Verify with `SELECT * FROM pg_extension WHERE extname = 'vector';` after first run.

## References

- Research: `context/changes/testing-data-integrity/research.md`
- Test plan Phase 1: `context/foundation/test-plan.md:77`
- Evaluation persistence archive: `context/archive/2026-06-01-evaluation-persistence/plan.md`
- Established auth override pattern: `tests/test_routes_workflows.py:203`
- Repository under test: `src/db/repositories.py:130–312`
- Workflow routes: `src/api/routes/workflows.py:159–193` (sync) and `src/api/routes/workflows.py:416–450` (streaming)
- Jobs route (assertion target): `src/api/routes/jobs.py:25–90`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Test Infrastructure

#### Automated

- [x] 1.1 Smoke test passes: `uv run pytest tests/integration/test_smoke.py -v`
- [x] 1.2 Full suite still passes: `uv run pytest`

#### Manual

- [x] 1.3 Test DB `agentic_hire_test` exists; tables created; pgvector extension confirmed

### Phase 2: Repository Isolation Fixes

#### Automated

- [x] 2.1 Type checking passes: `uv run mypy src/`
- [x] 2.2 Full suite passes: `uv run pytest`

#### Manual

- [x] 2.3 No tests skipped or xfail
- [x] 2.4 No callers of `get_by_id` or `get_by_job_id` found without `user_id` argument (`grep` confirmed)

### Phase 3: Risk #1 Integration Tests — Evaluation Persistence

#### Automated

- [x] 3.1 Persistence tests pass: `uv run pytest tests/integration/test_evaluation_persistence.py -v`
- [x] 3.2 Full suite passes: `uv run pytest`
- [x] 3.3 Type checking passes: `uv run mypy src/`

#### Manual

- [x] 3.4 Both tests pass without `xfail` or `skip`

### Phase 4: Risk #2 Integration Tests — User Isolation

#### Automated

- [x] 4.1 Isolation tests pass: `uv run pytest tests/integration/test_user_isolation.py -v`
- [x] 4.2 Full suite passes: `uv run pytest`
- [x] 4.3 Type checking passes: `uv run mypy src/`

#### Manual

- [x] 4.4 Both tests pass without `xfail` or `skip`
- [x] 4.5 Cross-user write test is confirmed to fail when Phase 2 fix is reverted (regression guard verified)
