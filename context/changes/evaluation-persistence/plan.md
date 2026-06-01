# Evaluation Persistence Implementation Plan

## Overview

After the LangGraph workflow completes, persist each shortlisted job's match score, orchestrator reasoning, and tailor summary into the `evaluations` table. This closes the gap between the live API response (which already carries the data) and the database (which never receives it), enabling the "Discovered Jobs" frontend page to display scores from the DB.

## Current State Analysis

The `evaluations` table, `EvaluationRepository`, and the frontend display logic all exist. The only missing piece is the write path. Both workflow endpoints (`/api/workflows/search-jobs` and `/api/workflows/search-jobs/stream`) already have a `session: AsyncSession` dependency injected; neither calls `EvaluationRepository` after graph execution.

Additionally, the `evaluations` table has no unique constraint on `(user_id, job_id)`, so re-running the workflow creates duplicate rows — the first evaluation becomes permanently stale in the jobs list (`JobRepository.get_jobs_with_scores` uses a LEFT OUTER JOIN that returns the first match).

### Key Discoveries

- `src/db/models.py:116-119` — `__table_args__` contains two separate indexes; no `UniqueConstraint` on `(user_id, job_id)`
- `src/db/repositories.py:224-274` — `EvaluationRepository` has `create()` and `update_scores()` but no upsert
- `src/api/routes/workflows.py:34` — `session: AsyncSession = Depends(get_db)` already present
- `src/api/routes/workflows.py:149-152` — results extracted from graph; no persistence follows
- `src/api/routes/workflows.py:376-430` — streaming variant: `acc["shortlisted_jobs"]` and `acc["applications"]` populated after graph; same gap
- `src/api/routes/jobs.py:61-62` — `get_jobs_with_scores()` uses LEFT OUTER JOIN on `evaluations`; returns null scores until evaluations are written
- `alembic/versions/50932ab33e1b_add_searchsession_table.py` — latest migration; new migration chains from this revision

## Desired End State

After a user completes a workflow run, every shortlisted job has a row in the `evaluations` table with `match_score`, `orchestrator_reasoning`, and `tailor_summary` populated. Re-running the workflow updates those rows (upsert). The "Discovered Jobs" page displays non-null match scores. If DB persistence fails, the API still returns the workflow result.

### Key Discoveries

- `src/api/routes/search.py:105-133` — reference pattern: job persistence after scout agent (loop → `JobRepository.create_or_update` → `session.commit()`)
- `tests/test_repositories.py:1-60` — established pattern: `AsyncMock(spec=AsyncSession)` + `session.add.assert_called_once()`
- `tests/test_graph_workflow.py` — uses `@patch` + `cast(AgenticHireState, {...})` for state mocking

## What We're NOT Doing

- Persisting rejected jobs' evaluations (they have no tailor summary and scores below threshold)
- Adding observability/tracing for the persistence step
- Changing the API response schema
- Adding a separate endpoint to re-trigger persistence for past runs

## Implementation Approach

Three phases: (1) add the DB constraint and a single upsert method, (2) wire the write call into both endpoints, (3) unit tests. The upsert uses PostgreSQL's `INSERT ... ON CONFLICT DO UPDATE` — appropriate since pgvector already requires PostgreSQL.

## Critical Implementation Details

- **Streaming closure**: `run_graph()` is spawned via `asyncio.create_task(run_graph())`. The `session` object from the outer scope is accessible as a closure variable — this is safe because `session` is set before `create_task` and all access is via `await` within the same event loop. No ContextVar gymnastics required.
- **Upsert constraint name**: the Alembic migration and the `on_conflict_do_update` call in the repository must reference the same constraint name (`uq_evaluations_user_job`). The model's `UniqueConstraint` must also carry this name so SQLAlchemy's DDL and the migration stay in sync.
- **tailor_summary null vs empty string**: the `applications` dict may contain `""` for a job if Tailor ran but produced nothing. Store `None` when the string is empty or absent — the column is `nullable=True` and `null` is semantically distinct from an empty summary.

---

## Phase 1: Schema Constraint + Upsert Infrastructure

### Overview

Add a `UniqueConstraint(user_id, job_id)` to the `Evaluation` model, a `upsert()` method to `EvaluationRepository`, and an Alembic migration. No endpoint code changes yet.

### Changes Required

#### 1. Evaluation model — unique constraint

**File**: `src/db/models.py`

**Intent**: Add a named `UniqueConstraint` on `(user_id, job_id)` to `Evaluation.__table_args__` so the DB enforces one evaluation per user per job.

**Contract**: Add `UniqueConstraint("user_id", "job_id", name="uq_evaluations_user_job")` alongside the two existing `Index` entries in `__table_args__`. The constraint name must match what Phase 1.2 references.

#### 2. EvaluationRepository — upsert method

**File**: `src/db/repositories.py`

**Intent**: Add `EvaluationRepository.upsert()` that inserts a new evaluation or updates `match_score`, `orchestrator_reasoning`, `tailor_summary`, and `evaluated_at` if a row for `(user_id, job_id)` already exists.

**Contract**: Static async method with signature:

```python
@staticmethod
async def upsert(
    session: AsyncSession,
    user_id: UUID,
    job_id: str,
    match_score: float,
    orchestrator_reasoning: Optional[str],
    tailor_summary: Optional[str],
) -> None:
```

Uses `sqlalchemy.dialects.postgresql.insert` (alias `pg_insert`) to build an `INSERT ... ON CONFLICT ON CONSTRAINT uq_evaluations_user_job DO UPDATE SET ...` statement. Import `from sqlalchemy.dialects.postgresql import insert as pg_insert` at the top of the file. Call `await session.execute(stmt)` — no `session.flush()` needed (the caller commits).

#### 3. Alembic migration — add unique constraint

**File**: `alembic/versions/<hash>_add_unique_constraint_evaluations_user_job.py`  
(generate with `uv run alembic revision --autogenerate -m "add unique constraint evaluations user job"` then verify the generated file)

**Intent**: Apply the `uq_evaluations_user_job` constraint to the live schema and provide a clean downgrade.

**Contract**: `upgrade()` calls `op.create_unique_constraint("uq_evaluations_user_job", "evaluations", ["user_id", "job_id"])`. `downgrade()` calls `op.drop_constraint("uq_evaluations_user_job", "evaluations", type_="unique")`. Chain: `down_revision = "50932ab33e1b"`.

### Success Criteria

#### Automated Verification

- Migration applies cleanly: `uv run alembic upgrade head`
- Mypy passes: `uv run mypy src/`
- Full test suite passes: `uv run pytest`

#### Manual Verification

- `psql` (or any DB client): confirm `\d evaluations` shows the unique constraint `uq_evaluations_user_job`

**Implementation Note**: After automated verification passes, confirm the constraint appears in the DB before moving to Phase 2.

---

## Phase 2: Persistence in Both Endpoints

### Overview

Wire `EvaluationRepository.upsert()` into both `search_jobs_workflow` (non-streaming) and `run_graph()` (streaming inner function). Both already have `session` available.

### Changes Required

#### 1. Add imports to workflows module

**File**: `src/api/routes/workflows.py`

**Intent**: Import `EvaluationRepository` and `Evaluation` model so the route can call upsert.

**Contract**: Extend the existing `from src.db import User` line to also import `EvaluationRepository` and `Evaluation`.

#### 2. Non-streaming endpoint — persist after graph completes

**File**: `src/api/routes/workflows.py`

**Intent**: After extracting `shortlisted_jobs` and `applications` from the graph result (currently lines 149–152), iterate shortlisted jobs and upsert one evaluation row per job before building the response. Log and swallow DB errors so the response is always returned.

**Contract**: Insert a `try` block immediately after line 156 (the `logger.info` on graph results). Inside the try: iterate `shortlisted_jobs`, extract `tailor_summary = applications.get(job.id, {}).get("founded_job_offer") or None`, call `await EvaluationRepository.upsert(session, user_id=user.id, job_id=job.id, match_score=job.match_score, orchestrator_reasoning=job.analysis or None, tailor_summary=tailor_summary)`, then `await session.commit()`. In the `except Exception` handler: log with `logger.error(...)` (include `exc_info=True`) and continue — do not re-raise.

#### 3. Streaming endpoint — persist inside run_graph()

**File**: `src/api/routes/workflows.py`

**Intent**: After `graph.astream()` finishes (after the `for` loop at line ~374) and before building `final_response`, persist evaluations using the same upsert pattern. `session` is available from the outer `search_jobs_stream` scope via closure.

**Contract**: Same persistence block as Phase 2.2, placed immediately after the existing `logger.info("[STREAM] Graph complete; building final response")` log line (line ~376), before iterating `acc["shortlisted_jobs"]` to build `shortlisted_results`. Same `try/except` error handling — log, don't re-raise (the `except Exception` block in `run_graph` already emits an SSE error event; persistence failures must not trigger it).

### Success Criteria

#### Automated Verification

- Mypy passes: `uv run mypy src/`
- Full test suite passes: `uv run pytest`

#### Manual Verification

- Run the full workflow via `POST /api/workflows/search-jobs` (or via the Streamlit UI for streaming). After completion, query `SELECT * FROM evaluations;` in the DB — confirm rows exist with non-null `match_score`, `orchestrator_reasoning`, `tailor_summary`
- Navigate to the "Discovered Jobs" page in the frontend — confirm match score badges show percentages instead of "—"
- Run the workflow a second time with the same jobs — confirm the rows are updated, not duplicated (row count stays the same)

**Implementation Note**: Verify both the sync and streaming paths manually — they share the same DB outcome but different code paths.

---

## Phase 3: Unit Tests

### Overview

Add unit tests covering: (a) upsert is called for each shortlisted job, (b) a DB commit failure does not prevent the workflow response from being returned.

### Changes Required

#### 1. Tests for non-streaming endpoint persistence

**File**: `tests/test_routes_workflows.py` (new file, or append to `tests/test_graph_workflow.py`)

**Intent**: Verify that `EvaluationRepository.upsert` is called once per shortlisted job, and that a `session.commit()` failure is caught and the response still returns.

**Contract**: Two `@pytest.mark.asyncio` tests:
- `test_workflow_persists_evaluations_for_shortlisted_jobs`: patch `build_graph` to return an `AsyncMock` whose `ainvoke` returns a state with 2 shortlisted jobs and a matching `applications` dict. Patch `EvaluationRepository.upsert` as `AsyncMock`. Assert `upsert.call_count == 2` and `session.commit.call_count == 1`.
- `test_workflow_returns_response_on_persistence_failure`: same setup but `session.commit` raises `Exception("DB down")`. Assert the returned `OrchestrateResponse` still has `shortlisted_jobs` populated (not empty) and `error_count == 0`.

Follow the `AsyncMock(spec=AsyncSession)` pattern from `tests/test_repositories.py`.

### Success Criteria

#### Automated Verification

- New tests pass: `uv run pytest tests/test_routes_workflows.py -v` (or equivalent path)
- Full suite still passes: `uv run pytest`
- Mypy passes: `uv run mypy src/`

#### Manual Verification

- No tests are skipped or marked xfail

---

## Testing Strategy

### Unit Tests

- `EvaluationRepository.upsert` called once per shortlisted job (both with and without tailor summary)
- `session.commit` failure → response still returned, error logged

### Integration Tests

- (Covered by manual steps in Phase 2 — no automated integration test added in this change)

### Manual Testing Steps

1. Start the full stack: `docker-compose up`
2. Authenticate and run a workflow via `POST /api/workflows/search-jobs`
3. Query `SELECT job_id, match_score, tailor_summary FROM evaluations WHERE user_id = '<your-id>';` — rows must exist
4. Open the frontend "Discovered Jobs" page — score badges must show percentages
5. Re-run the same workflow — row count in `evaluations` must not increase; scores must reflect latest run

## Migration Notes

The unique constraint is applied with `CREATE UNIQUE INDEX` semantics. Existing duplicate rows (if any exist in a dev DB) will cause `alembic upgrade head` to fail. Resolution: `DELETE FROM evaluations WHERE id NOT IN (SELECT MIN(id) FROM evaluations GROUP BY user_id, job_id);` before running the migration.

## References

- Roadmap parked item: `context/foundation/roadmap.md` § Parked — "Evaluation persistence gap"
- Job persistence reference pattern: `src/api/routes/search.py:105-133`
- EvaluationRepository: `src/db/repositories.py:224-275`
- Evaluation model: `src/db/models.py:112-139`
- Latest migration: `alembic/versions/50932ab33e1b_add_searchsession_table.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Schema Constraint + Upsert Infrastructure

#### Automated

- [x] 1.1 Migration applies cleanly: `uv run alembic upgrade head`
- [x] 1.2 Mypy passes: `uv run mypy src/`
- [x] 1.3 Full test suite passes: `uv run pytest`

#### Manual

- [x] 1.4 `\d evaluations` shows constraint `uq_evaluations_user_job`

### Phase 2: Persistence in Both Endpoints

#### Automated

- [x] 2.1 Mypy passes: `uv run mypy src/`
- [x] 2.2 Full test suite passes: `uv run pytest`

#### Manual

- [x] 2.3 Non-streaming: evaluation rows appear in DB after workflow run
- [x] 2.4 Frontend "Discovered Jobs" page shows match score percentages
- [x] 2.5 Re-run: row count unchanged, scores updated (upsert confirmed)
- [x] 2.6 Streaming: same DB outcome via `/stream` endpoint

### Phase 3: Unit Tests

#### Automated

- [x] 3.1 New tests pass: `uv run pytest tests/test_routes_workflows.py -v`
- [x] 3.2 Full suite passes: `uv run pytest`
- [x] 3.3 Mypy passes: `uv run mypy src/`

#### Manual

- [ ] 3.4 No tests skipped or xfail
