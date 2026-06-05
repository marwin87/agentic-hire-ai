# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Exception Handling: Distinguish Recoverable from Critical Errors

**Context**: When handling external service failures (API calls, database, file I/O)

**Problem**: Broad `except Exception:` catches all errors equally — database timeouts, network failures, missing resources. This causes critical failures to silently degrade with logging-only recovery, hiding real bugs. Example: CV context retrieval fails due to database down, but endpoint continues with empty CV context instead of surfacing the database error.

**Rule**: Never use bare `except Exception:`. Narrow to specific exception types or error conditions. Distinguish:
- Recoverable errors (resource not found, optional data missing) → log and continue
- Critical errors (connectivity, auth, system state) → log, rollback, and re-raise

**Applies to**: Any endpoint that calls external services (LLM, database, vector store, job search APIs). Prevents masking real infrastructure failures as graceful degradation.

## Scout-phase CancelledError swallowing — unreliable task cancellation

**Context**: `src/agents/scout.py` + `src/tools/job_validator.py` retry loop

**Problem**: `except Exception` blocks at scout.py:174, 259, 300, 333 and job_validator.py:177 absorb `asyncio.CancelledError`. In Python 3.8+, `CancelledError` is a `BaseException` subclass (not `Exception`), so it should propagate — but wrapping broad `await` calls in `except Exception` prevents it. A cancelled background task in the Scout phase will continue running to completion as an orphan rather than terminating on `task.cancel()`.

**Rule**: Never wrap an `await` call to an external service in bare `except Exception:` when the caller needs reliable cancellation. Either enumerate specific exception types, or use a narrow `except SomeToolError` and let all others (including `CancelledError`) propagate. For agent code that must degrade gracefully on tool failure, catch the tool-specific exception only.

**Applies to**: `src/agents/scout.py`, `src/tools/job_validator.py`, any future agent or tool that wraps LLM or external-API `await` calls in broad exception blocks.

## ContextVar propagation through async coroutine chains vs. spawned tasks

**Context**: `src/utils/progress.py` + streaming endpoint in `src/api/routes/workflows.py`

**Problem**: When using Python `ContextVar` to propagate state (e.g., a shared progress queue) to code running inside a framework like LangGraph, there's uncertainty about whether the framework dispatches work via direct `await` (inherits context) or `asyncio.create_task()` (copies context at creation time, safe if set before `create_task`) or a thread pool (loses context entirely).

**Rule**: ContextVar values propagate correctly to any coroutine that is `await`-ed in the same task, and to tasks spawned with `asyncio.create_task()` IF the var was set before the task was created. They do NOT propagate across thread boundaries (e.g., `loop.run_in_executor`). Verify empirically when integrating with a new async framework.

**Applies to**: Any module using ContextVar for implicit state propagation — logging context, progress queues, request IDs, tracing spans.
