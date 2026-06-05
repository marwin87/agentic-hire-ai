# Streaming Resilience Tests Implementation Plan

## Overview

Close the Phase 3 risk gap from `context/foundation/test-plan.md`: write an integration
test that proves no orphan evaluation write reaches the DB when an SSE client disconnects
mid-stream. Test-only scope — no production code changes.

## Current State Analysis

Phase 1 (data integrity) and Phase 2 (agent logic regression) are archived. The integration
test infrastructure they established is fully reusable here:

- `tests/integration/conftest.py` — `real_session` (SAVEPOINT isolation), `user_a`, `async_client_a`
- Streaming test pattern from `test_evaluation_persistence.py:87–159` — `async_client_a.stream()`
  + `fake_astream` + `patch("src.api.routes.workflows.build_graph")`
- `GET /api/jobs` as the DB-state assertion (LEFT JOIN evaluations — `match_score` is None if no eval row)

### Key Discoveries

- `src/api/routes/workflows.py:518` — `asyncio.create_task(run_graph())` spawns the graph task
- `src/api/routes/workflows.py:542–548` — disconnect cleanup: `task.cancel()` + `asyncio.shield(task)`
- `src/api/routes/workflows.py:417–451` — persistence block runs AFTER `async for event in graph.astream(...)` loop ends
- `src/agents/scout.py:174,259,300,333` — four `except Exception` blocks absorb `CancelledError` during Scout phase (known limitation — test bypasses by stalling AFTER all node events)
- `src/db/repositories.py:294–326` — `EvaluationRepository.upsert()` with `ON CONFLICT DO UPDATE` on `(user_id, job_id)` — retry idempotent, no duplicate rows

## Desired End State

`uv run pytest tests/integration/test_streaming_resilience.py -v` passes green.

The single test proves: after an SSE client disconnects (breaks the stream after the tailor
node event, before `workflow_complete`), no evaluation row exists in the DB for the test
job_id — even though `shortlisted_jobs` was fully populated before the disconnect.

If the cancel+shield cleanup ever regresses (e.g., persistence reaches the commit before the
task is cancelled), the test fails with a non-None `match_score` — the correct failure signal.

### Key Discoveries (test-plan alignment)

- Anti-pattern avoided for Risk #3: testing only successful stream completion. This test
  deliberately never consumes `workflow_complete`.
- The stalling `fake_astream` yields all three node events (so `shortlisted_jobs` IS populated),
  then blocks at `await gate.wait()`. `run_graph()` is stuck awaiting the next astream event —
  not inside a scout broad-catch block — so `task.cancel()` reliably reaches that await.
- The scout-phase CancelledError-swallowing gap (scout.py lines 174, 259, 300, 333) is
  documented as a known limitation in the test module docstring.

## What We're NOT Doing

- Not testing the retry/competing-write scenario (idempotency is proven by the upsert
  constraint in the model — not a test scenario here)
- Not fixing scout.py `except Exception` blocks (production-code change, separate concern)
- Not testing mid-persistence-block cancellation (requires patching `session.commit()`,
  adds brittleness without proportional risk coverage)
- Not testing the non-streaming `POST /api/workflows/search-jobs` endpoint (disconnect is
  irrelevant there — it's a plain `await`, not SSE)
- Not updating CI configuration (planned but out of scope per test-plan §5)
- Not covering Risk #7 (secret leak) — that is Phase 4

## Implementation Approach

Single new test file following the established integration test pattern. The disconnect is
simulated by breaking the SSE consumer loop after receiving the tailor node event — at which
point `run_graph()` is blocked awaiting the next `astream` event (the gate). The generator's
`finally` fires on stream close, calls `task.cancel()`, and `asyncio.shield(task)` awaits the
task's terminal state before the generator exits. DB state is asserted via `GET /api/jobs`.

---

## Phase 1: SSE disconnect test — no orphan evaluation write

### Overview

Create `tests/integration/test_streaming_resilience.py`. One test function proves that when
the SSE client disconnects after the tailor node event (but before `workflow_complete`), no
evaluation row is written for the test job.

### Changes Required

#### 1. New integration test file

**File**: `tests/integration/test_streaming_resilience.py`

**Intent**: Prove Risk #3: the cancel+shield cleanup path in `event_generator()` correctly
terminates `run_graph()` before the persistence block, leaving no evaluation row in the DB.

**Contract**:

Use the same fixture set as `test_evaluation_persistence.py`: `async_client_a`, `real_session`,
`user_a`. Apply the same three patches: `AgentFactory`, `get_cv_context_async`,
`build_graph`. The mock graph's `astream` must be `fake_astream_stalling` — an async generator
that yields all three node events (validate_jobs, orchestrator, tailor), then blocks at
`await gate.wait()` where `gate = asyncio.Event()` is created in the test and never set. This
ensures `run_graph()` is suspended inside the `async for event in graph.astream(...)` loop
(not the persistence block) when the disconnect fires.

The test consumes the SSE stream until the tailor `node_complete` event is received, then
breaks — exiting `async with async_client_a.stream(...)`. After the `async with` exits,
yield control to the event loop with `await asyncio.sleep(0.05)` to allow the generator's
`finally` block (`task.cancel()` + `asyncio.shield(task)`) to run to completion. Then
assert via `GET /api/jobs` that no entry for the test job_id carries a non-null
`match_score`.

The module docstring must state:
- Which risk this covers (Risk #3, test-plan Phase 3)
- The known limitation: `task.cancel()` during the Scout phase is absorbed by four
  `except Exception` blocks in `src/agents/scout.py` (lines 174, 259, 300, 333) and by
  `src/tools/job_validator.py:177`. This test bypasses that gap by stalling the mock graph
  after all three node events — at that point `run_graph()` is awaiting the next astream
  event, not inside a scout broad-catch block.
- The failure signal: if the cancel+shield cleanup regresses and persistence runs before
  cancellation, this test will fail with a non-None `match_score` for the test job.

The assert message must name the job_id and the actual `match_score` so a failure is
immediately diagnostic.

The `gate` event is intentionally never set. If somehow the `async with` exit does not
trigger cleanup (a httpx/ASGITransport behavioral edge), the `gate.wait()` will block
indefinitely inside the still-running task. To prevent test hangs, wrap the whole test
body in `async with asyncio.timeout(10.0):` — a 10-second ceiling is generous for a
mocked test; if it's ever hit, the failure message "timed out" surfaces the hang.

### Success Criteria

#### Automated Verification

- Integration test passes: `uv run pytest tests/integration/test_streaming_resilience.py -v`
- Full integration suite still passes: `uv run pytest tests/integration/ -v`
- Black formatting: `uv run black tests/integration/test_streaming_resilience.py --check`

#### Manual Verification

- Temporarily remove the `await gate.wait()` line from `fake_astream_stalling` so the
  graph completes naturally and persistence runs. Confirm the test now FAILS with a
  non-None `match_score` assertion error — this verifies the test has genuine signal
  and would catch a regression in the cancel mechanism. Restore the line after confirming.

**Implementation Note**: Pause after Phase 1 for manual confirmation before proceeding.

---

## Phase 2: Test-plan and lessons update

### Overview

Update `context/foundation/test-plan.md` to reflect Phase 3 status. Add the
scout-phase CancelledError-swallowing pattern to `context/foundation/lessons.md`
as a named known limitation so future contributors see it before touching `scout.py`
or the streaming endpoint.

### Changes Required

#### 1. Test-plan Phase 3 status

**File**: `context/foundation/test-plan.md`

**Intent**: Mark Phase 3 row as "change opened" and add the change folder reference.

**Contract**: In the `## 3. Phased Rollout` table, update Phase 3's Status cell from
`not started` to `change opened` and add `context/changes/testing-streaming-resilience/`
in the Change folder cell. Also update the `> Last updated:` line at the top of the file.

#### 2. Lessons entry — scout.py CancelledError swallowing

**File**: `context/foundation/lessons.md`

**Intent**: Capture the scout broad-catch pattern as a named recurring rule so it's
visible before any future changes to `scout.py` or `job_validator.py` exception handling.

**Contract**: Append a new `##` section. Content:

- **Context**: `src/agents/scout.py` + `src/tools/job_validator.py` retry loop
- **Problem**: `except Exception` blocks at scout.py:174, 259, 300, 333 and job_validator.py:177
  absorb `asyncio.CancelledError`. In Python 3.8+, `CancelledError` is a `BaseException`
  subclass (not `Exception`), so it should propagate — but wrapping broad `await` calls in
  `except Exception` prevents it. A cancelled background task in the Scout phase will
  continue running to completion as an orphan rather than terminating on `task.cancel()`.
- **Rule**: Never wrap an `await` call to an external service in bare `except Exception:` when
  the caller needs reliable cancellation. Either use `except Exception as e: raise` to re-raise
  `CancelledError`, or enumerate specific exception types. For agent code that must degrade
  gracefully on tool failure, catch the tool-specific exception and let all others propagate.
- **Applies to**: `src/agents/scout.py`, `src/tools/job_validator.py`, any future agent that
  wraps LLM or external-API `await` calls in broad exception blocks.

### Success Criteria

#### Automated Verification

- All existing tests still pass: `uv run pytest tests/ -v` (doc-only changes, no regressions)

#### Manual Verification

- Confirm Phase 3 row in test-plan.md reads `change opened` with the correct folder path.
- Confirm lessons.md has the new scout CancelledError entry.

**Implementation Note**: Pause after Phase 2 for final confirmation.

---

## Testing Strategy

### Integration Tests

- Risk #3: one integration test against the real test DB using the SAVEPOINT fixture pattern.
  The test uses a mock graph (no real LangGraph execution, no LLM calls, no OrioSearch).

### Manual Testing Steps

1. After Phase 1: run `uv run pytest tests/integration/test_streaming_resilience.py -v` and
   confirm the test passes and its name appears unambiguously in output.
2. After Phase 1: verify failure signal by removing `await gate.wait()` and confirming the
   test fails with a meaningful error message that includes the job_id and match_score value.
   Restore the line.
3. After Phase 2: confirm test-plan.md Phase 3 row and lessons.md entry look correct.

## References

- Research doc: `context/changes/testing-streaming-resilience/research.md`
- Test-plan Risk #3: `context/foundation/test-plan.md §2`
- Cancel+shield code: `src/api/routes/workflows.py:542–548`
- Known limitation locations: `src/agents/scout.py:174,259,300,333`, `src/tools/job_validator.py:177`
- Existing streaming test pattern: `tests/integration/test_evaluation_persistence.py:87–159`
- SAVEPOINT fixture: `tests/integration/conftest.py`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: SSE disconnect test — no orphan evaluation write

#### Automated

- [x] 1.1 Integration test passes: `uv run pytest tests/integration/test_streaming_resilience.py -v`
- [x] 1.2 Full integration suite passes: `uv run pytest tests/integration/ -v`
- [x] 1.3 Black formatting: `uv run black tests/integration/test_streaming_resilience.py --check`

#### Manual

- [ ] 1.4 Test fails (correctly) when gate.wait() is removed and persistence runs — failure message names job_id and match_score

### Phase 2: Test-plan and lessons update

#### Automated

- [x] 2.1 All existing tests pass with doc-only changes: `uv run pytest tests/ -v`

#### Manual

- [ ] 2.2 Phase 3 row in test-plan.md reads "change opened" with correct folder path
- [ ] 2.3 lessons.md has the new scout CancelledError entry
