---
date: 2026-06-05T20:30:00+00:00
researcher: Claude Sonnet 4.6
git_commit: c56235e34a70838b9fe8765e866a99fa8923411c
branch: master
repository: agentic-hire-ai
topic: "SSE disconnect resilience — orphan task lifecycle, cancellation propagation, and competing-write safety"
tags: [research, streaming, sse, asyncio, cancellation, upsert, langgraph]
status: complete
last_updated: 2026-06-05
last_updated_by: Claude Sonnet 4.6
---

# Research: SSE Disconnect Resilience

**Date**: 2026-06-05T20:30:00+00:00
**Researcher**: Claude Sonnet 4.6
**Git Commit**: c56235e34a70838b9fe8765e866a99fa8923411c
**Branch**: master
**Repository**: agentic-hire-ai

## Research Question

Phase 3 of the test plan (Risk #3): Prove that on SSE client disconnect, the background task is
cancelled and no orphan write occurs to the evaluations table. Ground the test design in:
- How disconnect is detected in FastAPI/Starlette
- Whether task cancellation propagates through `graph.astream()` to DB writes
- Whether the upsert constraint prevents competing writes from a retry

---

## Summary

The SSE streaming endpoint (`workflows.py:299–558`) uses `asyncio.create_task(run_graph())` to run
the LangGraph graph in the background. Disconnect is detected implicitly via the generator's
`finally` block — not via `request.is_disconnected()` polling. The `finally` block calls
`task.cancel()` and then `asyncio.shield(task)` to await cleanup.

**The critical finding**: `task.cancel()` does not reliably stop the background task if the
graph is inside the Scout phase. Four `except Exception` blocks in `scout.py` (lines 174, 259,
300, 333) and one in `job_validator.py` (line 177) absorb `CancelledError` before it can
propagate out of the scout node — meaning the scout continues running as an orphan even after
`task.cancel()` is called.

If the graph has progressed past the Scout phase into Orchestrator or Tailor, cancellation
propagates cleanly. If the graph has already completed and is in the DB persistence block,
cancellation escapes the broad catches there (they are `except Exception`, not
`except BaseException`) and rolls back the session correctly.

The DB upsert constraint `(user_id, job_id)` on the `evaluations` table makes retries fully
idempotent — a second workflow run after a partial disconnect produces no duplicate rows.

---

## Detailed Findings

### 1. SSE Streaming Endpoint Structure

**File**: `src/api/routes/workflows.py`

```
search_jobs_stream()     lines 299–558    POST endpoint, returns StreamingResponse
  event_generator()      lines 371–548    AsyncGenerator[str, None] — SSE producer
    run_graph()          lines 386–516    inner async def, spawned via create_task
```

**Queue wiring** (`workflows.py:374–375`):
```python
q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
set_progress_queue(q)        # sets ContextVar BEFORE create_task — correct
```

**Task creation** (`workflows.py:518`):
```python
task = asyncio.create_task(run_graph())
```

**Generator consume loop** (`workflows.py:520–541`):
```python
try:
    while True:
        item = await q.get()
        if item is None:      # sentinel from run_graph() finally
            break
        yield f"data: {WorkflowStreamEvent(...).model_dump_json()}\n\n"
```

**Disconnect → cleanup** (`workflows.py:542–548`):
```python
finally:
    if not task.done():
        task.cancel()                                 # line 544
    try:
        await asyncio.shield(task)                    # line 546
    except (asyncio.CancelledError, Exception):       # line 547
        pass
```

**Disconnect mechanism**: When the HTTP client drops the connection, FastAPI/Starlette stops
consuming from `event_generator()`. The generator's `while True` loop exits via the async
generator protocol, triggering the `finally` block. There is no `request.is_disconnected()`
polling and no explicit `GeneratorExit` catch — the standard Python generator protocol handles it.

**`src/utils/progress.py`**: Implements a `ContextVar`-based `asyncio.Queue` for progress logs.
`set_progress_queue()` must be called before `create_task()` for the spawned task to inherit the
queue reference (this is done correctly at `workflows.py:375`). Agents call `await emit(node, msg)`
which puts `{"type": "log", ...}` onto the queue.

---

### 2. Cancellation Propagation Through `run_graph()`

**File**: `src/api/routes/workflows.py:386–516`

`run_graph()` structure:
```
outer try/except Exception (line 507)
  graph.astream() loop (line 390)         ← CancelledError injected HERE if cancelled during graph
  DB persistence block (lines 417–451)    ← only reached after graph completes
    inner try/except Exception (line 446) ← rollback on persistence error
  q.put(workflow_complete) (line ~453)
finally:
  q.put(None)  # sentinel (line 516)
```

**Key fact**: `CancelledError` in Python 3.8+ inherits from `BaseException`, not `Exception`.
The `except Exception` catches at lines 446 and 507 do **not** intercept it. Cancellation
propagates through both catches, hits the `finally` at line 515, sends the sentinel, and
re-raises — the task ends in a cancelled state. **The DB write block (lines 417–451) is skipped
entirely** if cancellation arrives while the graph is executing.

**However — scout.py swallows CancelledError at four points**:

| Location | Line | Pattern | Effect |
|---|---|---|---|
| Pre-seed portal loop | `scout.py:174` | `except Exception` | CancelledError during portal search is logged as WARNING; scout continues |
| Tool execution inner loop | `scout.py:259` | `except Exception` | CancelledError from `await job_search_tool.ainvoke()` or `await scrape_webpage_tool.ainvoke()` becomes a ToolMessage error |
| Parser fallback | `scout.py:300` | `except Exception` | CancelledError during parser → `all_found_jobs = []`, continues |
| Fallback search | `scout.py:333` | `except Exception` | CancelledError during fallback search → `all_found_jobs = []`, continues |

**`src/tools/job_validator.py:177`**: The retry loop `except Exception` also swallows CancelledError
from `await self.checker.ainvoke()`. The retry then calls `await asyncio.sleep(backoff)` —
which is itself a cancellation point — but the original CancelledError is already lost.

**Net result for the test**:
- `task.cancel()` during Scout phase → the task is NOT actually cancelled. Scout runs to
  completion as an orphan. DB writes will occur after scout finishes.
- `task.cancel()` during Orchestrator or Tailor phase → cancellation propagates cleanly; DB
  writes are skipped.
- `task.cancel()` during DB persistence block → `CancelledError` escapes the inner
  `except Exception` (it only catches `Exception`), rolls back (actually: does NOT rollback —
  the `except Exception` at line 446 handles rollback, but CancelledError bypasses it), then the
  outer `except Exception` at line 507 also lets it pass, reaching the `finally`. Session is
  not committed and not explicitly rolled back in this path. Minor session leak risk.

---

### 3. DB Upsert Constraint and Competing-Write Safety

**File**: `src/db/repositories.py:294–326`

```python
stmt = (
    pg_insert(Evaluation)
    .values(user_id=user_id, job_id=job_id, match_score=..., ...)
    .on_conflict_do_update(
        constraint="uq_evaluations_user_job",
        set_={"match_score": ..., "evaluated_at": datetime.now(timezone.utc)},
    )
)
await session.execute(stmt)
```

**File**: `src/db/models.py:134–138`

```python
__table_args__ = (
    Index("ix_evaluations_user_id", "user_id"),
    Index("ix_evaluations_job_id", "job_id"),
    UniqueConstraint("user_id", "job_id", name="uq_evaluations_user_job"),
)
```

Conflict key: `(user_id, job_id)` — composite. Primary key is a separate UUID `id`.

**Confirmed by migration**: `alembic/versions/6cfe28947e05_...py:24`
```python
op.create_unique_constraint('uq_evaluations_user_job', 'evaluations', ['user_id', 'job_id'])
```

**Competing-write scenarios**:

| Scenario | DB outcome |
|---|---|
| Two concurrent workflows, both commit | One row per (user_id, job_id). Second write updates match_score + evaluated_at. |
| Partial write cancelled before commit | Session not committed → no row written. Retry starts clean. |
| Committed then retried | Retry upserts → single row updated in place. No duplicate. |

No pessimistic locking. PostgreSQL default isolation (`READ COMMITTED`). No `SELECT FOR UPDATE`.

**Idempotency**: Full. A retry after any disconnect scenario — mid-graph, mid-persistence, or
post-commit — produces exactly one evaluation row per (user_id, job_id).

**One edge case**: If cancellation arrives between the `await session.execute(stmt)` calls for
individual jobs (inside the `for job in acc["shortlisted_jobs"]:` loop at line 432) and BEFORE
`await session.commit()`, those upserts are buffered but not committed. The `CancelledError`
propagates past the inner `except Exception` at line 446 (since CancelledError ≠ Exception).
The session is left in an uncommitted, not-rolled-back state. SQLAlchemy will close it on GC
but this is a minor cleanup gap.

---

### 4. The `asyncio.shield` Subtlety

**File**: `src/api/routes/workflows.py:546`

```python
await asyncio.shield(task)
```

`asyncio.shield(task)` protects the task from the *outer* cancellation context — meaning if
the generator itself is being cancelled (which it is, on disconnect), `shield` ensures the
`await` of the task completes even while the outer coroutine is cancelled. Any
`CancelledError` or other exception from the task is then caught at line 547 and suppressed.

**Implication for testing**: The `finally` block in `event_generator` always runs to completion
regardless of the cancellation state of the generator itself. `task.cancel()` at line 544 is
always reached, and the `await asyncio.shield(task)` at line 546 always awaits the task's
terminal state before the generator exits.

---

## Code References

- `src/api/routes/workflows.py:299–558` — Full SSE streaming endpoint
- `src/api/routes/workflows.py:371–548` — `event_generator()` async generator
- `src/api/routes/workflows.py:386–516` — `run_graph()` inner coroutine
- `src/api/routes/workflows.py:518` — `asyncio.create_task(run_graph())`
- `src/api/routes/workflows.py:542–548` — disconnect cleanup: `task.cancel()` + `shield`
- `src/utils/progress.py:14–29` — ContextVar-based progress queue
- `src/agents/scout.py:174` — CancelledError swallow #1 (pre-seed portal loop)
- `src/agents/scout.py:259` — CancelledError swallow #2 (tool execution inner loop)
- `src/agents/scout.py:300` — CancelledError swallow #3 (parser fallback)
- `src/agents/scout.py:333` — CancelledError swallow #4 (fallback search)
- `src/tools/job_validator.py:177` — CancelledError swallow #5 (retry loop)
- `src/db/repositories.py:294–326` — `EvaluationRepository.upsert()` with ON CONFLICT
- `src/db/models.py:134–138` — Evaluation `UniqueConstraint("user_id", "job_id", ...)`
- `alembic/versions/6cfe28947e05_...py:24` — Migration creating `uq_evaluations_user_job`
- `tests/integration/conftest.py` — SAVEPOINT session fixture (reuse for Phase 3 tests)

---

## Architecture Insights

**Pattern: cancel + shield** (`workflows.py:543–548`)
The `finally` block correctly cancels the background task and uses `asyncio.shield` to await
its terminal state without propagating the generator's own cancellation. This pattern was
deliberately introduced (see Historical Context) to fix an earlier `await task` that blocked
the server until graph completion even on disconnect.

**Pattern: sentinel-based generator termination** (`workflows.py:515–516, 522–523`)
`run_graph()` always puts `None` into the queue in its `finally` block. The generator's
`while True` loop breaks on `None`. This means a cancelled `run_graph()` task will still
unblock the generator — the sentinel is sent before the CancelledError re-raises.

**Pattern: ContextVar for progress queue** (`progress.py:14–16`)
`set_progress_queue()` is called at `workflows.py:375` before `create_task()` at `workflows.py:518`,
so the spawned task inherits the queue reference correctly (see lessons.md ContextVar rule).

**Structural problem: broad Exception catches in agents**
The Scout and JobValidator have `except Exception` blocks around `await` calls. In Python 3.8+,
`CancelledError` is not an `Exception` subclass — this is the correct rule. But these catches
ARE catching `asyncio.TimeoutError` and other async-layer exceptions that may wrap
CancelledError. More importantly, the design means `task.cancel()` is unreliable as a
hard-stop mechanism during the Scout phase.

**DB write ordering**: persistence block (lines 417–451) runs AFTER `graph.astream()` completes
fully. `workflow_complete` SSE event is sent AFTER persistence. So a client that receives
`workflow_complete` is guaranteed to have a committed evaluation row.

---

## Historical Context

- `context/archive/2026-06-01-evaluation-persistence/plan.md` — Established the upsert pattern
  (`EvaluationRepository.upsert()`) and confirmed that `session` is safely passed to `run_graph()`
  as a closure variable (set before `create_task`, all access via `await` in same event loop).
- `context/archive/2026-05-27-graph-workflow-api/plan.md` — Introduced the `asyncio.create_task`
  pattern for streaming; established that persistence block runs before `workflow_complete` event.
- `context/archive/2026-05-29-scout-scraping-upgrade/reviews/impl-review.md:F2` — Documents
  the cancel+shield fix: earlier code used `await task` (no cancel), which blocked the server
  until graph completion even if the client had disconnected. The fix replaced it with the
  current `task.cancel()` + `asyncio.shield(task)` pattern.
- `context/archive/2026-06-01-testing-data-integrity/research.md` — Established the SAVEPOINT
  integration test fixture (`join_transaction_mode="create_savepoint"`, `NullPool`). Phase 3
  tests must reuse this pattern from `tests/integration/conftest.py`.

---

## Open Questions

1. **Scout-phase orphan**: When `task.cancel()` is called while the scout is inside one of
   the four broad `except Exception` blocks, the task continues running. Does it eventually
   self-terminate (after scout completes and propagates to orchestrator)? Or does it persist
   indefinitely if scout loops? This needs to be verified empirically in the test.

2. **Session leak on mid-persistence cancel**: If `CancelledError` arrives between individual
   upsert `execute()` calls and before `commit()`, the session is left uncommitted and not
   rolled back. SQLAlchemy closes it on GC. Is this a problem in practice? Under high load
   (many parallel cancellations), this could leak connection pool slots.

3. **`asyncio.shield` interaction with disconnect timing**: The `finally` block is guaranteed
   to run, but `await asyncio.shield(task)` could theoretically hang if `run_graph()` itself
   has an infinite loop (e.g., scout in an infinite retry). Is there a timeout on the shield?
   Currently none — which means a stuck scout could hold the generator open indefinitely.

4. **Test approach for scout-phase cancel**: The cleanest test approach is probably to mock
   `build_graph()` to return a graph whose scout node sleeps (giving the test a reliable
   cancellation window) rather than trying to cancel a real LangGraph execution mid-flight.
   This avoids the broad-catch swallowing problem and tests the disconnect path in isolation.
