# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Exception Handling: Distinguish Recoverable from Critical Errors

**Context**: When handling external service failures (API calls, database, file I/O)

**Problem**: Broad `except Exception:` catches all errors equally — database timeouts, network failures, missing resources. This causes critical failures to silently degrade with logging-only recovery, hiding real bugs. Example: CV context retrieval fails due to database down, but endpoint continues with empty CV context instead of surfacing the database error.

**Rule**: Never use bare `except Exception:`. Narrow to specific exception types or error conditions. Distinguish:
- Recoverable errors (resource not found, optional data missing) → log and continue
- Critical errors (connectivity, auth, system state) → log, rollback, and re-raise

**Applies to**: Any endpoint that calls external services (LLM, database, vector store, job search APIs). Prevents masking real infrastructure failures as graceful degradation.
