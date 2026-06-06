# Security Gate Implementation Plan

## Overview

Fix three confirmed `str(e)` secret-leak surfaces in the production API response bodies,
migrate three sensitive `AppConfig` fields to `pydantic.SecretStr` (plus a startup log
redaction), and add unit tests that regression-guard all four surfaces.

This is Phase 4 of the test-plan rollout (`context/foundation/test-plan.md`). It covers
Risk #7: JWT/OpenRouter key leakage into HTTP error response bodies or loguru log entries.

## Current State Analysis

Three response-body leaks are confirmed active (no debug-mode gate):

| Location | Leak | Trigger |
|---|---|---|
| `workflows.py:144` | `status=f"Graph execution failed: {str(e)}"` | Any `Exception` from `graph.ainvoke()` |
| `workflows.py:269` | `status=f"Workflow failed: {str(e)}"` | Outer catch-all in the sync endpoint |
| `workflows.py:513` | `{"data": {"message": str(e)}}` in SSE error event | Any `Exception` in `run_graph()` |

One log leak is confirmed always-active:
- `main.py:31` — `logger.info(f"Database initialized: {config.database_url}")` logs the full DSN
  (including password `dev_password`) unconditionally on every startup.

Three structural secrets are plain `str` in `AppConfig`:
- `openrouter_api_key: Optional[str]` → used in `agents.py:30`, `utils/__init__.py:22`, `cv.py:206`
- `jwt_secret_key: str` → used in `auth/utils.py:70,91`
- `database_url: str` → used in `db/database.py:22` and `main.py:31`

What is already safe and NOT changing:
- All `HTTPException.detail` strings are static — no JWT or key echoed.
- JWT decode path returns only `"Invalid or expired token"` (generic).
- The `debug_mode=True` path in `main.py:88` is debug-only; production is already safe.
- `cv.py:55` `ValueError` path stores the LLM rejection reason — benign user-facing text, not a secret.
- The `repr(e)` + `exc_info=True` log call-sites are deferred to a separate hardening pass.

## Desired End State

After this plan:
1. `OrchestrateResponse.status` and SSE `data.message` never contain raw exception strings.
2. The startup log contains only `host:port/dbname`, not the password.
3. `config.openrouter_api_key`, `config.jwt_secret_key`, and `config.database_url` are
   `SecretStr` — their `repr()` shows `'**********'`, not the raw value.
4. Four tests in `tests/unit/test_security_gate.py` assert each surface independently,
   providing regression guards for future changes.

### Key Discoveries

- All three response-body leaks are in `workflows.py` — no other route files affected.
- `openrouter_api_key` call-sites already follow the `api_key_value = config.openrouter_api_key`
  pattern; adding `.get_secret_value()` is a mechanical one-liner change at each.
- `jwt_secret_key` is used in two adjacent lines (`auth/utils.py:70,91`) — single file.
- `database_url` is used in `db/database.py:22` (engine creation) and `main.py:31` (log).
- `SecretStr` default values work in pydantic-settings v2: a plain-string default is coerced
  to `SecretStr` automatically.

## What We're NOT Doing

- **No `repr(e)` → `type(e).__name__` in log call-sites** — deferred; whether the OpenRouter
  SDK embeds the key in `AuthenticationError.__str__()` needs empirical verification first.
- **No custom `RequestValidationError` 422 handler** — the latent `password`/`refresh_token`
  risk is speculative; no constraints exist today that trigger 422.
- **No test for `cv.py:55`** — the `ValueError` stores LLM rejection reasons, not secrets.
- **No fix for `main.py:88` debug-mode `str(exc)` in 500 response** — debug mode is
  treated as a trusted-internal surface; production `debug_mode=False` is already safe.

## Implementation Approach

Phase-by-phase to keep each diff independently reviewable:
1. Narrowest change first — fix the three `str(e)` substitutions in `workflows.py` only.
   No settings, no tests. Verifiable by reading the diff alone.
2. Settings migration — change three `AppConfig` fields to `SecretStr` and update all
   7 call-sites. Also fix `main.py:31` log line (requires `SecretStr` access pattern).
3. Tests — `tests/unit/test_security_gate.py` with four assertions. Uses
   `app.dependency_overrides` to mock auth/DB, no real PostgreSQL needed.

---

## Phase 1: Fix str(e) in response bodies

### Overview

Replace three `str(e)` interpolations in `workflows.py` with static generic strings. The
`str(e)` value already appears in the `logger.error()` call one or two lines above each
site — the internal log is unchanged; only the external response body is sanitized.

### Changes Required

#### 1. Sync endpoint — inner graph exception (`workflows.py:144`)

**File**: `src/api/routes/workflows.py`

**Intent**: The `except Exception` block at line 135 already logs `str(e)` via `logger.error`.
The `OrchestrateResponse.status` field on line 144 also embeds it, exposing it in the 200 OK
JSON body. Replace the status string with a static generic message so the internal detail
stays in logs only.

**Contract**: Change `status=f"Graph execution failed: {str(e)}"` → `status="Graph execution failed"`.

#### 2. Sync endpoint — outer catch-all (`workflows.py:269`)

**File**: `src/api/routes/workflows.py`

**Intent**: The outer `except Exception` block at line 260 catches all remaining exceptions
(including those from CV context retrieval). Same pattern — `logger.error` already records
the detail; the `status` field on line 269 must not echo it.

**Contract**: Change `status=f"Workflow failed: {str(e)}"` → `status="Workflow failed"`.

#### 3. Streaming endpoint — SSE error event (`workflows.py:513`)

**File**: `src/api/routes/workflows.py`

**Intent**: Inside `run_graph()`, the `except Exception` block at line 507 puts the error
event into the SSE queue. The `data.message` key on line 513 contains `str(e)`, which the
generator yields as a `data: {...}` SSE line read directly by the client.

**Contract**: Change `{"type": "error", "node": "workflow", "data": {"message": str(e)}}`
→ `{"type": "error", "node": "workflow", "data": {"message": "Workflow error"}}`.

### Success Criteria

#### Automated Verification

- Type check passes: `uv run mypy src/`
- All existing tests pass: `uv run pytest`

#### Manual Verification

- Confirm the three changed lines no longer interpolate `str(e)`.
  Read `src/api/routes/workflows.py` around lines 144, 269, 513 and verify the static
  strings are in place.

---

## Phase 2: SecretStr migration + startup log redaction

### Overview

Change three `AppConfig` fields to `pydantic.SecretStr` and update all 7 call-sites that
access the raw value. Also fix `main.py:31` to log only the host/db portion of the DSN.

### Changes Required

#### 1. `AppConfig` — add `SecretStr` and change three field types

**File**: `src/config/settings.py`

**Intent**: Three fields currently typed as plain `str` (or `Optional[str]`) expose their
values in any `repr(config)` call. Change them to `SecretStr` so loguru, pydantic's own
repr, and any accidental `f"{config!r}"` in future code shows `'**********'` instead.

**Contract**: 
- Add `SecretStr` to the pydantic import line alongside `Field`.
- Change `openrouter_api_key: Optional[str] = None` → `openrouter_api_key: Optional[SecretStr] = None`
- Change `jwt_secret_key: str = Field(...)` → `jwt_secret_key: SecretStr = Field(...)`
- Change `database_url: str = Field("postgresql+asyncpg://...")` → `database_url: SecretStr = Field("postgresql+asyncpg://...")`

pydantic-settings v2 coerces the plain-string default value to `SecretStr` automatically.

#### 2. `agents.py` — unwrap openrouter_api_key

**File**: `src/agents/agents.py`

**Intent**: Line 30 assigns `api_key_value = config.openrouter_api_key`. After the `SecretStr`
migration, this holds a `SecretStr` object. The downstream call passes it as a string to the
`ChatOpenAI` client — it must be unwrapped first.

**Contract**: 
```python
api_key_value = (
    config.openrouter_api_key.get_secret_value() if config.openrouter_api_key else None
)
```

#### 3. `utils/__init__.py` — unwrap openrouter_api_key

**File**: `src/utils/__init__.py`

**Intent**: Same pattern as `agents.py:30` — `api_key_value = config.openrouter_api_key`
at line 22 must unwrap the `SecretStr`.

**Contract**: Same one-liner as Change 2 above.

#### 4. `cv.py` — unwrap openrouter_api_key

**File**: `src/api/routes/cv.py`

**Intent**: `api_key_value = config.openrouter_api_key` at line 206. Same pattern.

**Contract**: Same one-liner as Change 2.

#### 5. `auth/utils.py` — unwrap jwt_secret_key

**File**: `src/auth/utils.py`

**Intent**: Lines 70 and 91 pass `config.jwt_secret_key` as the `key` argument to
`jwt.encode()` and `jwt.decode()`. Both expect a plain `str`.

**Contract**: Change both occurrences of `config.jwt_secret_key` → `config.jwt_secret_key.get_secret_value()`.

#### 6. `db/database.py` — unwrap database_url

**File**: `src/db/database.py`

**Intent**: Line 22 passes `config.database_url` to `create_async_engine()`. SQLAlchemy
expects a plain string.

**Contract**: Change `config.database_url` → `config.database_url.get_secret_value()` in
the `create_async_engine(...)` call.

#### 7. `main.py` — redact startup log

**File**: `src/api/main.py`

**Intent**: Line 31 logs the full DSN including password. Now that `database_url` is
`SecretStr`, access the raw value explicitly and strip credentials before logging.

**Contract**: Change the log line to:
```python
logger.info(
    f"Database initialized: {config.database_url.get_secret_value().split('@')[-1]}"
)
```
This logs only `host:port/dbname` — the password before `@` is dropped.

### Success Criteria

#### Automated Verification

- Type check passes: `uv run mypy src/`
- All existing tests pass: `uv run pytest`

#### Manual Verification

- `repr(config)` in a REPL or test does not print the raw value of `openrouter_api_key`,
  `jwt_secret_key`, or `database_url` — each shows `SecretStr('**********')`.
- App starts without error: `uv run python -c "from src.api.main import app"` (import-time).

---

## Phase 3: Unit tests

### Overview

Create `tests/unit/test_security_gate.py` with four tests. No real DB required — auth and
DB dependencies are overridden via `app.dependency_overrides`. Graph calls are mocked.
A loguru sink captures log output for the startup-log test.

### Changes Required

#### 1. New unit test file

**File**: `tests/unit/test_security_gate.py` (new file; also create `tests/unit/__init__.py`)

**Intent**: Assert that after the Phase 1 and 2 fixes, none of the four surfaces leaks a
raw exception string containing a fake secret to external consumers.

**Contract**: Four async test functions:

1. **`test_workflow_error_does_not_leak_exception_in_response`**  
   Patch `build_graph` to make `ainvoke` raise `Exception` whose message contains a
   recognizable fake key string (e.g., `"sk-or-v1-FAKE-SECRET"`). Call
   `POST /api/workflows/search-jobs` via `AsyncClient + ASGITransport`. Assert the full
   response body text does not contain the fake key string.

2. **`test_streaming_error_does_not_leak_exception_in_sse`**  
   Patch `build_graph` to return a mock graph whose `astream` raises the same fake key
   exception. Call `search_jobs_stream()` route handler directly (same pattern as
   `test_streaming_resilience.py`), iterate `body_iterator` to completion, assert no
   yielded chunk contains the fake key string.

3. **`test_500_handler_hides_exception_in_production_mode`**  
   Temporarily set `config.debug_mode = False` (or patch it). Add a route that raises
   `Exception("sk-or-v1-FAKE-SECRET")` and is wired to hit the global exception handler.
   Assert the 500 response body does not contain the fake key string. (This documents that
   the existing handler is already safe in production mode — regression guard.)

4. **`test_startup_log_does_not_contain_database_password`**  
   Add a loguru string sink before running the lifespan. Patch `init_db` and
   `get_agent_factory` to no-op. Spin up the app lifespan via
   `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` context manager.
   Remove the sink. Assert `"dev_password"` (the default DSN password) is not present in
   the captured log output.

The fixture setup for tests 1–3 uses `app.dependency_overrides` to replace `get_current_user`
with a lambda returning a minimal `User` object, and `get_db` with an `AsyncMock`. The
overrides are cleared in a `finally` block (or `autouse` teardown fixture). The `AsyncClient`
wraps `ASGITransport(app=app)` — no real HTTP stack needed.

### Success Criteria

#### Automated Verification

- New test file runs and all four tests pass: `uv run pytest tests/unit/test_security_gate.py -v`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run mypy src/`

#### Manual Verification

- Read test output — confirm each test name is visible and passes independently when run
  with `-v`.
- Introduce a deliberate regression: temporarily revert `workflows.py:144` to `str(e)`,
  run `test_workflow_error_does_not_leak_exception_in_response` — it must fail. Then
  restore and re-run — it must pass. This confirms the test is not vacuously passing.

---

## Testing Strategy

### Unit Tests

`tests/unit/test_security_gate.py` covers all four surfaces described in Phase 3.
`app.dependency_overrides` eliminates the DB dependency; all external calls are mocked.

### Integration Tests

None added in this phase — the existing integration suite already covers the workflow
endpoints' happy paths; Phase 4 adds only the error-path security assertion.

### Manual Testing Steps

1. Start the app and POST a workflow request to `/api/workflows/search-jobs` with a real
   OpenRouter key but invalid criteria (to trigger an error). Confirm the response
   `status` field says `"Graph execution failed"` and does not contain any exception text.
2. Check startup logs — confirm the log line after `"Database initialized:"` shows only
   `host:port/dbname`, not `agentic_hire:dev_password@...`.
3. In a Python REPL: `from src.config.settings import config; print(repr(config.openrouter_api_key))`
   — should print `SecretStr('**********')`.

## References

- Research: `context/changes/testing-security-gate/research.md`
- Test-plan Phase 4 row: `context/foundation/test-plan.md` §3
- Prior integration test pattern: `tests/integration/test_streaming_resilience.py`
- `app.dependency_overrides` pattern: FastAPI docs (standard testing pattern)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. See `references/progress-format.md`.

### Phase 1: Fix str(e) in response bodies

#### Automated

- [x] 1.1 Type check passes: `uv run mypy src/`
- [x] 1.2 All existing tests pass: `uv run pytest`

#### Manual

- [x] 1.3 Confirm lines 144, 269, 513 in workflows.py use static strings (no str(e))

### Phase 2: SecretStr migration + startup log redaction

#### Automated

- [x] 2.1 Type check passes: `uv run mypy src/`
- [x] 2.2 All existing tests pass: `uv run pytest`

#### Manual

- [x] 2.3 `repr(config.openrouter_api_key)` shows `SecretStr('**********')` in REPL
- [x] 2.4 Startup log shows `host:port/dbname` only (no password)

### Phase 3: Unit tests

#### Automated

- [x] 3.1 Four new tests pass: `uv run pytest tests/unit/test_security_gate.py -v`
- [x] 3.2 Full suite passes: `uv run pytest`
- [x] 3.3 Type check passes: `uv run mypy src/`

#### Manual

- [x] 3.4 Deliberate regression confirms test_workflow_error_does_not_leak_exception_in_response catches the leak when str(e) is re-introduced
