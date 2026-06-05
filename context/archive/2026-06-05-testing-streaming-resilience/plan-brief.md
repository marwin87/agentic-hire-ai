# Streaming Resilience Tests — Plan Brief

> Full plan: `context/changes/testing-streaming-resilience/plan.md`
> Research: `context/changes/testing-streaming-resilience/research.md`

## What & Why

Adds an integration test for Risk #3 from the test-plan: a disconnecting SSE client must
not leave an orphan `run_graph()` task that writes evaluation rows after the stream closes.
Without this test, the cancel+shield cleanup path (`workflows.py:542–548`) is untested and
a regression would silently produce stale or competing writes.

## Starting Point

Phases 1 and 2 (data integrity + agent logic regression) are archived. The streaming test
pattern, SAVEPOINT fixture, and `GET /api/jobs` DB-assertion pattern are all established in
`tests/integration/test_evaluation_persistence.py` and `tests/integration/conftest.py`.
No new infrastructure is needed — only a new test file.

## Desired End State

`tests/integration/test_streaming_resilience.py` passes green. It proves: after breaking
the SSE stream following the tailor node event (before `workflow_complete`), no evaluation
row exists in the DB for the test job — even though `shortlisted_jobs` was populated.
Test-plan Phase 3 is marked "change opened" and lessons.md carries the scout
CancelledError-swallowing gap as a named rule.

## Key Decisions Made

| Decision | Choice | Why | Source |
|---|---|---|---|
| Scope | Test-only; no scout.py fix | Fixing broad `except Exception` in agents needs its own production-code review | Plan |
| Disconnect timing | Post-tailor, pre-persistence | Shortlisted_jobs IS populated → strong signal; run_graph() is at anext() not in a broad-catch | Research |
| Retry scenario | Excluded | Upsert idempotency is structural (ON CONFLICT), not worth a second workflow invocation | Plan |
| Stall mechanism | `asyncio.Event().wait()` inside fake_astream | Reliable cancel window without real sleeps; cancelled on task.cancel() | Research |
| Scout-phase gap | Document via code comment + lessons entry | Not exercisable via this test (absorbed by 4 except Exception blocks); named limitation is sufficient | Research |
| Hang guard | `asyncio.timeout(10.0)` | Prevents test hang if httpx/ASGITransport early-close doesn't trigger generator cleanup | Research OQ#1 |

## Scope

**In scope:** `tests/integration/test_streaming_resilience.py` (new), test-plan Phase 3
status update, lessons.md entry for scout CancelledError swallowing.

**Out of scope:** scout.py broad-catch fix, retry/competing-write test, mid-persistence
cancellation, CI configuration, Risk #7 (secret leak — Phase 4).

## Architecture / Approach

Mock `build_graph()` with a graph whose `astream` yields all three node events (validate_jobs,
orchestrator, tailor) then blocks at `await asyncio.Event().wait()`. The test consumes the
stream until tailor's `node_complete`, then exits `async with`. Generator `finally` fires:
`task.cancel()` → task gets CancelledError at `gate.wait()` → persistence skipped. Assert
via `GET /api/jobs` that `match_score` is None (no evaluation committed).

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Disconnect test | `test_streaming_resilience.py` green + failure-signal verified | httpx/ASGITransport may not trigger generator finally synchronously — mitigated by `asyncio.sleep(0.05)` + 10s timeout |
| 2. Docs update | test-plan Phase 3 status + lessons.md scout entry | Trivial doc edits — no technical risk |

**Prerequisites:** Real test DB running (`.env.test` configured), same as Phases 1 and 2.
**Estimated effort:** ~1 session across 2 phases.

## Open Risks & Assumptions

- httpx's `ASGITransport` may not synchronously signal generator cleanup when `async with stream_response:` exits early. Mitigated by `await asyncio.sleep(0.05)` after exit + `asyncio.timeout(10.0)` guard. If this proves insufficient, the implementation should add explicit task-reference tracking or test the internals differently.
- `task.cancel()` during Scout phase is unreliable (4 broad-catch absorptions in scout.py). This test avoids that window entirely — it does not prove Scout-phase cancellation works.

## Success Criteria (Summary)

- `uv run pytest tests/integration/test_streaming_resilience.py -v` passes green
- Test fails with a meaningful error when `gate.wait()` is removed (genuine signal verified)
- test-plan.md Phase 3 row and lessons.md entry updated
