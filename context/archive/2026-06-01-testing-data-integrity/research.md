---
date: 2026-06-01T00:00:00+00:00
researcher: mariusz
git_commit: 4812f44608d50f5fb130e16365de2e69d194d9c5
branch: master
repository: agentic-hire-ai
topic: "Data integrity integration tests — evaluation persistence and user isolation"
tags: [research, integration-tests, evaluation-persistence, user-isolation, async-db, pytest]
status: complete
last_updated: 2026-06-01
last_updated_by: mariusz
---

# Research: Data integrity integration tests — evaluation persistence and user isolation

**Date**: 2026-06-01  
**Researcher**: mariusz  
**Git Commit**: 4812f44608d50f5fb130e16365de2e69d194d9c5  
**Branch**: master  
**Repository**: agentic-hire-ai

## Research Question

Ground the Phase 1 integration tests for test-plan.md Risks #1 and #2:

- **Risk #1**: Evaluation persistence write fails silently — prove every shortlisted job has a non-null `match_score` in the DB after workflow completes, surviving a page reload (not just asserting the API response JSON).
- **Risk #2**: User data isolation missing — prove a request authenticated as user A cannot retrieve or modify user B's jobs, CVs, or evaluations.

---

## Summary

1. **Evaluation persistence is fully wired** in both workflow endpoints. Both paths have a single `session.commit()` after the upsert loop. Both silently swallow **all** exceptions via bare `except Exception` — meaning a DB failure never surfaces to the caller. This is the correct design intent but it means an integration test that only checks the 200 response cannot detect a persistence failure.

2. **Three user_id isolation gaps exist** in the repository layer. One is actively exploitable today (`JobRepository.create_or_update` — no user ownership check on the job lookup). Two are latent (repository methods exposed without user scope: `get_by_id`, `EvaluationRepository.get_by_job_id`). All three are callable through current routes.

3. **The entire test suite uses mocked sessions** — `AsyncMock(spec=AsyncSession)` everywhere. There is zero real-DB test coverage. The integration tests we are about to write are the first to ever hit a real PostgreSQL connection.

4. **Infrastructure gap is significant** but well-understood. The required additions: a test DB URL, a real async engine/session fixture with SAVEPOINT-based rollback, and the pgvector extension on the test DB. The patterns (dependency_overrides for auth, `@pytest.mark.asyncio`, `AsyncClient` + `ASGITransport`) already exist in the codebase.

---

## Detailed Findings

### Risk #1 — Evaluation persistence write path

#### Upsert implementation

**File**: `src/db/repositories.py:280–312`

`EvaluationRepository.upsert()` issues a PostgreSQL `INSERT ... ON CONFLICT ON CONSTRAINT uq_evaluations_user_job DO UPDATE SET`. On conflict the SET clause updates exactly four columns: `match_score`, `orchestrator_reasoning`, `tailor_summary`, `evaluated_at`. The primary key, `user_id`, and `job_id` are never overwritten. The method calls `await session.execute(stmt)` only — no `session.flush()`, no commit. The caller is responsible for committing.

#### Non-streaming endpoint persistence block

**File**: `src/api/routes/workflows.py` (approx. lines 159–193)

After `graph.ainvoke()` returns and results are extracted, a `try` block iterates `shortlisted_jobs`:
1. For each job: calls `JobRepository.create_or_update(session, job_db)` then `await session.flush()`.
2. Then a second loop: calls `await EvaluationRepository.upsert(session, user_id=user.id, job_id=job.id, ...)`.
3. A **single `await session.commit()`** at line ~183 follows both loops.

The `tailor_summary` is extracted with `eval_data.get("founded_job_offer") or None` (line ~174). The key `"founded_job_offer"` is correct — it is the actual dict key that `TailorAgent` puts in the `applications` dict. If the value is an empty string, `or None` coerces it to `None` (correct — the column is nullable).

The `except Exception` block at line ~188:
```python
except Exception as e:
    await session.rollback()
    logger.error(
        f"Persistence failed (non-critical): {type(e).__name__}: {repr(e)}",
        exc_info=True,
    )
```
Catches ALL exceptions (no filtering), rolls back, logs, and continues. The endpoint still returns the graph result as JSON. **There is no way to detect persistence failure from the API response status or body.**

#### Streaming endpoint persistence block

**File**: `src/api/routes/workflows.py` (approx. lines 416–450)

`run_graph()` is an inner coroutine launched via `asyncio.create_task(run_graph())` at line ~517. Inside `run_graph()`:

1. `graph.astream()` loop runs, emitting `node_complete` SSE events into a queue.
2. After the `astream()` loop completes, the persistence block executes synchronously (lines ~416–450) — **before the `workflow_complete` SSE frame is enqueued**.
3. Same `try/except Exception` structure — rollback, log, continue.
4. After persistence, `OrchestrateResponse` is built and enqueued as `{"type": "workflow_complete", ...}`.

**Double-masking risk in streaming path**: The `event_generator()`'s `finally` block (lines ~541–547) calls `asyncio.shield(task)` inside a bare `except (asyncio.CancelledError, Exception): pass`. If the client disconnects while `run_graph()` is in the persistence block, the task is cancelled — and any unhandled exception from `run_graph()` is silently eaten by this shield. However, the inner persistence `except` already catches everything, so in practice the outer shield only matters for `BaseException` subclasses (e.g., `KeyboardInterrupt`, `asyncio.CancelledError` in Python 3.8+).

#### Jobs list endpoint (the "page reload" assertion target)

**File**: `src/db/repositories.py:179–201`, `src/api/routes/jobs.py:25–90`

`JobRepository.get_jobs_with_scores()` uses:
```python
select(Job, Evaluation).outerjoin(
    Evaluation,
    (Evaluation.job_id == Job.id) & (Evaluation.user_id == user_id)
)
```
Returns `List[tuple[Job, Optional[float]]]`. When no evaluation row exists for a `(user_id, job_id)` pair, `match_score` in the response is `None`. The `Evaluation.match_score` column is `nullable=False` in the model — so a non-null score guarantees a real evaluation row was written.

**Assertion target for Risk #1 integration test**:
1. Trigger workflow (POST to either endpoint).
2. Call `GET /api/jobs` with the same user's auth token.
3. Find the shortlisted job in the response.
4. Assert `match_score is not None` and matches the value from the workflow response JSON.

This proves persistence survived — not just that the API returned scores in the workflow response.

---

### Risk #2 — User isolation gaps

#### Auth dependency

**File**: `src/api/dependencies.py:50`

`get_current_user` extracts the Bearer token, decodes the JWT, fetches the `User` ORM row from DB by `user_id`, and returns the full `User` object. All protected routes use `Depends(get_current_user)`. Routes access the UUID via `cast(UUID, user.id)`.

**All routes requiring auth** (via `Depends(get_current_user)`):
- `GET /api/jobs` (`routes/jobs.py:25`)
- `DELETE /api/jobs/{job_id}` (`routes/jobs.py:97`)
- `DELETE /api/jobs` (`routes/jobs.py:113`)
- `GET /api/cv/status` (`routes/cv.py:37`)
- `POST /api/upload_cv` (`routes/cv.py:51`)
- `POST /api/scout` (`routes/search.py:27`)
- `POST /api/validate_jobs` (`routes/validation.py:70`)
- `POST /api/workflows/search-jobs` (`routes/workflows.py:34`)
- `POST /api/workflows/search-jobs/stream` (`routes/workflows.py:302`)
- `POST /api/logout` (`routes/auth.py:214`)

Public (unauthenticated) routes are auth endpoints only (`/signup`, `/login`, `/refresh`) — correct by design.

#### Gap 1 — `JobRepository.create_or_update` (actively exploitable)

**File**: `src/db/repositories.py:130–148`

```python
existing = await session.execute(select(Job).where(Job.id == job.id))
```

The lookup is `WHERE id = job.id` only — no `AND user_id = expected_user`. If user B submits a POST to `/api/scout` or `/api/workflows/search-jobs` with a `job.id` that matches an existing job belonging to user A, `create_or_update` will overwrite user A's `title`, `company`, `description`, `url`, `salary_range` with user B's data. The `user_id` column is not updated (only the listed fields), but the data integrity of user A's row is broken.

Requires knowing a valid job UUID owned by another user. Not trivially discoverable, but the method is structurally incorrect.

#### Gap 2 — `JobRepository.get_by_id` (latent)

**File**: `src/db/repositories.py:151–154`

`WHERE id = job_id` only. Not called by any current route directly, but is a public method that any future `GET /api/jobs/{id}` would naturally reach for — without realizing it returns any user's job.

#### Gap 3 — `EvaluationRepository.get_by_job_id` (latent)

**File**: `src/db/repositories.py:252–257`

`WHERE job_id = job_id` only — no user_id filter. Would return another user's evaluation data for a known `job_id`. Not called from any current route.

#### Well-isolated repository methods

All list/read operations used in current routes are correctly scoped:
- `JobRepository.get_jobs_with_scores(user_id, ...)` — `WHERE Job.user_id = user_id`
- `JobRepository.get_by_user(user_id)` — `WHERE user_id = user_id`
- `JobRepository.delete_by_id(job_id, user_id)` — `WHERE id = job_id AND user_id = user_id`
- `EvaluationRepository.get_by_user(user_id)` — `WHERE user_id = user_id`
- `CVFileRepository.get_latest_by_user(user_id)` — `WHERE user_id = user_id`

**Assertion targets for Risk #2 integration test**:
1. **List isolation**: Create jobs for user A. Authenticate as user B. `GET /api/jobs` must return zero results.
2. **Cross-user write via scout/workflow**: User A has a job row with known `job_id`. User B POSTs to `/api/scout` with `job.id = user_A_job_id`. Assert user A's job row in DB is unchanged afterward (title, company, etc.).
3. **Latent gap regression**: Confirm `get_by_id` and `get_by_job_id` are not reachable through any route — document the pattern any future route must follow.

---

### Test infrastructure — current state and gaps

#### What exists

- `asyncio_mode`: NOT configured in `pyproject.toml` — defaults to `strict`. Every async test/fixture needs explicit `@pytest.mark.asyncio` / `@pytest_asyncio.fixture`.
- Session pattern: 100% `AsyncMock(spec=AsyncSession)` — no real DB in any test.
- Auth override pattern: `app.dependency_overrides[get_current_user] = lambda: mock_user` — already established in `tests/test_routes_workflows.py:203`.
- HTTP client: `httpx.AsyncClient` with `ASGITransport(app=app)` — used in `test_routes_workflows.py`.
- User fixtures: `conftest.py:27–48` has `test_user` and `test_user_2` — real `User(...)` ORM objects but never persisted to a DB.
- Plugins already available: `pytest>=9.0.3`, `pytest-asyncio>=0.24.0`, `pytest-mock>=3.14.0`, `httpx>=0.28.0`, `asyncpg>=0.30.0`, `sqlalchemy[asyncio]>=2.0.25`.

#### What is missing

| Gap | Required for Phase 1 |
|---|---|
| Test database URL | Yes — no `TEST_DATABASE_URL`, no `.env.test`; `AppConfig.database_url` defaults to the dev DB |
| Real async engine + session fixture | Yes — zero infrastructure for a real `AsyncEngine` / `AsyncSession` in tests |
| pgvector extension on test DB | Yes — `CVEmbedding.embedding` is `Vector(1536)`; `CREATE EXTENSION IF NOT EXISTS vector` must run before `create_all` |
| SAVEPOINT-based per-test rollback | Yes — needed to isolate tests without truncating tables after each test |
| Schema setup/teardown | Yes — no `Base.metadata.create_all` in any fixture |
| `tests/integration/conftest.py` | Yes — `tests/integration/` exists but has no conftest; a scoped conftest cleanly separates real-DB fixtures from mocked ones |
| `asyncio_mode = "auto"` | Optional — saves decorating every integration test, but not strictly required |

#### Recommended fixture architecture for Phase 1

```python
# tests/integration/conftest.py

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def real_session(test_engine):
    async with test_engine.connect() as conn:
        await conn.begin_nested()          # SAVEPOINT
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.rollback()           # rolls back to SAVEPOINT

@pytest_asyncio.fixture
async def user_a(real_session):
    user = await UserRepository.create(real_session, email="a@test.com", password_hash="...")
    await real_session.flush()
    return user

@pytest_asyncio.fixture
async def user_b(real_session):
    user = await UserRepository.create(real_session, email="b@test.com", password_hash="...")
    await real_session.flush()
    return user

@pytest.fixture
def app_as_user_a(user_a):
    app.dependency_overrides[get_current_user] = lambda: user_a
    app.dependency_overrides[get_db] = lambda: real_session   # inject real session
    yield app
    app.dependency_overrides.clear()
```

**Note on `get_db` override**: `src/api/dependencies.py:33–44` shows `get_db` is not a generator — it calls `factory()` and returns a session. For the HTTP-layer integration tests, overriding `get_db` to return the SAVEPOINT-backed `real_session` is the cleanest path. The SAVEPOINT rollback after each test means the DB is always clean without truncating tables.

---

## Code References

- `src/db/repositories.py:130–148` — `JobRepository.create_or_update` — no user_id ownership check (Gap 1)
- `src/db/repositories.py:151–154` — `JobRepository.get_by_id` — no user_id filter (Gap 2)
- `src/db/repositories.py:179–201` — `JobRepository.get_jobs_with_scores` — correctly scoped
- `src/db/repositories.py:252–257` — `EvaluationRepository.get_by_job_id` — no user_id filter (Gap 3)
- `src/db/repositories.py:280–312` — `EvaluationRepository.upsert` — the upsert implementation
- `src/api/routes/workflows.py:159–193` — non-streaming persistence block (try/except, single commit)
- `src/api/routes/workflows.py:416–450` — streaming persistence block (inside `run_graph()`)
- `src/api/routes/workflows.py:517` — `asyncio.create_task(run_graph())` launch point
- `src/api/routes/workflows.py:541–547` — streaming `finally` block with `asyncio.shield`
- `src/api/routes/jobs.py:25–90` — `GET /api/jobs` route — calls `get_jobs_with_scores`
- `src/api/dependencies.py:50` — `get_current_user` definition
- `src/db/models.py:116–119` — `Evaluation.__table_args__` — `UniqueConstraint("uq_evaluations_user_job")`
- `tests/conftest.py:14–24` — `db_session` fixture — `AsyncMock(spec=AsyncSession)`
- `tests/conftest.py:27–48` — `test_user` / `test_user_2` — ORM objects, not persisted
- `tests/test_routes_workflows.py:203` — established auth override pattern
- `pyproject.toml:38–40` — `[tool.pytest.ini_options]` — no asyncio_mode set

---

## Architecture Insights

### Silent persistence failure is a feature, not a bug

Both endpoints deliberately swallow all persistence exceptions so that a DB blip never breaks the user-facing workflow response. The API will return HTTP 200 with correct JSON scores even if the DB write fails. **This is why the integration test must query the DB directly** — the API response cannot distinguish between "persisted" and "returned from memory only."

### SAVEPOINT strategy is the right isolation primitive here

Full `create_all` / `drop_all` per test would be painfully slow with pgvector tables. SAVEPOINT rollback is fast (no DDL round-trip) and handles concurrent test parallelism correctly since each test gets its own nested transaction.

### `create_or_update` ownership gap is a structural issue, not just a test target

The gap in `JobRepository.create_or_update` should be fixed (add `AND user_id = job.user_id` to the lookup) in addition to being tested. The integration test catches it; the fix closes it. Both should happen in this phase.

### The streaming path is tested last

The persistence block in `run_graph()` runs before the `workflow_complete` SSE frame is sent. This means an integration test that awaits the full SSE response can rely on persistence being complete (or rolled back) when the stream closes. No special timing is needed.

---

## Historical Context

- `context/archive/2026-06-01-evaluation-persistence/plan.md` — Full evaluation-persistence implementation plan. All three phases completed. Establishes the write path, the upsert SQL, the `founded_job_offer` key, and the exception-swallowing posture. The tests added there (`tests/test_routes_workflows.py`) are **unit tests with mocked sessions** — they assert `upsert.call_count == 2` but never touch a real DB row.
- `context/archive/2026-06-01-evaluation-persistence/plan-brief.md` — Summary of key decisions: upsert for duplicate handling, log-and-swallow for persistence failure, fix both sync and streaming paths.
- `context/foundation/lessons.md` — "Exception Handling: Distinguish Recoverable from Critical Errors" — the bare `except Exception` in the persistence blocks is a known pattern the team has flagged as risky. The integration test will confirm whether a real DB failure surfaces anywhere.
- `context/foundation/lessons.md` — "ContextVar propagation through async coroutine chains vs. spawned tasks" — relevant to the `asyncio.create_task(run_graph())` pattern; the lesson confirms that `session` (set before `create_task`) is safely accessible via closure in `run_graph()`.

## Related Research

No other research artifacts exist yet for this change folder.

---

## Open Questions

1. **`create_or_update` fix scope**: Should the user_id ownership check be added to `JobRepository.create_or_update` as part of this phase (fixing the gap), or should the integration test only document the gap and the fix land in a separate change? The test plan says "prove protection" — proving protection requires the fix to exist before the test can pass.

2. **Test DB provisioning**: Is a test PostgreSQL instance expected to be running locally (e.g., via `docker-compose up` with a second DB service) or should the integration tests target the same dev DB with test-scoped data? The SAVEPOINT strategy works against either, but a separate `agentic_hire_test` database is cleaner.

3. **`asyncio_mode = "auto"`**: Should this be enabled globally in `pyproject.toml` to avoid decorating every integration test, or kept at `strict` to preserve the existing convention? Existing tests all use explicit `@pytest.mark.asyncio` — switching to `auto` would be consistent with the new direction but changes the convention for all tests.

4. **`founded_job_offer` key stability**: The `tailor_summary` extraction uses `applications[job.id].get("founded_job_offer")`. This key is set by `TailorAgent`. If the agent ever renames the key, `tailor_summary` is silently `None`. Is there a test for the key name, or should one be added here?
