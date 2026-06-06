---
date: 2026-06-05T20:56:49+00:00
researcher: Claude Sonnet 4.6
git_commit: fa0b41bafca290550bb823c0c9a470ecaad671df
branch: master
repository: agentic-hire-ai
topic: "Security gate — JWT/API key leakage into error responses and loguru log entries (Risk #7)"
tags: [research, security, error-handling, loguru, jwt, api-key, pydantic]
status: complete
last_updated: 2026-06-05
last_updated_by: Claude Sonnet 4.6
---

# Research: Security Gate — Secret Leakage into Error Responses and Logs

**Date**: 2026-06-05T20:56:49+00:00
**Researcher**: Claude Sonnet 4.6
**Git Commit**: fa0b41bafca290550bb823c0c9a470ecaad671df
**Branch**: master
**Repository**: agentic-hire-ai

## Research Question

Phase 4 of the test plan (Risk #7): prove no JWT tokens, OpenRouter API keys, or raw Python
tracebacks escape into HTTP error response bodies or loguru log entries. Ground the test design in:
- All exception handlers (custom + FastAPI defaults) and what they serialize into responses
- All loguru call-sites at ERROR/WARNING level — do `repr(e)` patterns on LLM/auth exceptions carry secrets?
- Whether Pydantic validation errors echo sensitive field values (password, refresh_token)

---

## Summary

**Phase 4 is not just a test-writing exercise — it is also a bug-fix phase.** Research uncovered
confirmed leaks in the current production code that must be fixed before tests can assert protection:

1. **`workflows.py:144,269,513`** — `str(e)` from any graph exception is placed unconditionally into
   the HTTP response body (as `OrchestrateResponse.status` or SSE `data.message`). If OpenRouter
   raises an `AuthenticationError` whose message contains the key, it flows to the client.
2. **`main.py:31`** — `config.database_url` (including password `dev_password`) is logged on every
   startup unconditionally. Always present in stdout/JSON log sinks.
3. **Multiple `repr(e)` log call-sites** in `workflows.py` and `scout.py` with `exc_info=True` —
   `repr()` of HTTP client exceptions may embed request headers (Authorization), and the traceback
   exposes call-stack context. Without `diagnose=True` local variable values are NOT auto-injected,
   but the exception message itself is a risk.

**What is already safe:**
- All `HTTPException.detail` strings are static/generic — no JWT echoed, no API key in detail.
- JWT decode failures in `dependencies.py` catch exceptions and return only `"Invalid or expired token"`.
- The OpenRouter API key IS wrapped in `SecretStr` at the point of construction (`agents.py:31`,
  `cv.py:207`, `utils/__init__.py`) so `repr()` of the ChatOpenAI client object is safe. Whether
  `openai.AuthenticationError.__str__()` still includes the key prefix is an open question (see §OQ3).
- Loguru's `diagnose=False` (default) means local variable values are NOT in tracebacks.
- No Authorization header is logged anywhere.

**Phase 4 scope conclusion**: Fix the three confirmed leak surfaces first, then write tests that
assert the fixed behavior. The test layer is unit-style (mock graph errors, trigger 422/500, capture
loguru output) — no real LLM calls needed.

---

## Detailed Findings

### 1. Exception Handlers — Response Body Surfaces

#### 1.1 Custom global handler (`main.py:78–96`)

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception in {request.method} {request.url.path}: {exc}", exc_info=exc)
    detail = "Internal server error"
    if config.debug_mode:
        detail = str(exc)           # ← debug-only leak
    return JSONResponse(status_code=500, content={"detail": detail, "status_code": 500})
```

- **Production (debug_mode=False)**: response is `{"detail": "Internal server error"}` — safe.
- **Debug mode**: response is `{"detail": str(exc)}` — full exception message in body.
- The logger call on line 81 uses `str(exc)` + `exc_info=exc` — traceback in logs always, regardless
  of debug_mode. If any unhandled exception from an OpenRouter call bubbles here, the key could be
  in both the log and (in debug mode) the response.

#### 1.2 No custom `RequestValidationError` handler registered

FastAPI's built-in 422 handler echoes the field `"input"` value for fields that fail validation.
Current request schemas with sensitive fields:
- `SignupRequest.password` / `password_confirm` (`src/api/schemas.py:88–89`)
- `LoginRequest.password` (`src/api/schemas.py:98`)
- `RefreshRequest.refresh_token` (`src/api/schemas.py:104`)

All three are currently plain `str` with no type constraints — so type validation never fires
and the 422 path is not triggered in practice. This is a **latent risk**: if a constraint is
added to `refresh_token` (e.g. min_length) without a custom validation handler, the submitted
token value would appear verbatim in the 422 body.

#### 1.3 Confirmed leaks — `str(e)` in 200-OK response body (non-debug)

These three are the most critical findings: they leak unconditionally regardless of debug_mode.

| Location | Code | Vector | Debug-only? |
|---|---|---|---|
| `src/api/routes/workflows.py:144` | `status=f"Graph execution failed: {str(e)}"` | `OrchestrateResponse.status` in 200 JSON | **No — always** |
| `src/api/routes/workflows.py:269` | `status=f"Workflow failed: {str(e)}"` | `OrchestrateResponse.status` in 200 JSON | **No — always** |
| `src/api/routes/workflows.py:513` | `{"type":"error","data":{"message": str(e)}}` | SSE error event `data.message` | **No — always** |

Additionally:
- `src/api/routes/cv.py:55`: `cv_file.ingestion_error = str(e)` — persisted to DB, returned via
  `GET /api/cv/status` response field `ingestion_error`. CV ingestion uses OpenRouter Vision LLM;
  an API auth failure's message would be stored and served to the authenticated user. **Medium risk.**

---

### 2. Loguru Configuration

**File**: `src/config/logging.py`

- `backtrace=False`, `diagnose=False` (Loguru defaults) — local variable values are NOT in tracebacks.
- `serialize=True` available when `AGENTIC_HIRE_JSON_LOGS=true` — JSON sink includes `exception.value`
  field verbatim. Intended for Datadog/Splunk/Loki. Any secret in an exception message is fully
  preserved in JSON and shipped to the log aggregator.
- Sinks: stdout (plain text, always), stderr (JSON, opt-in). No file sink. **No redaction filters.**

#### 2.1 Confirmed HIGH: `config.database_url` logged unconditionally

```python
# src/api/main.py:31
logger.info(f"Database initialized: {config.database_url}")
```

The default value of `database_url` is `postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire`.
This logs the credentials on every startup. Present in both plain-text and JSON sinks.

#### 2.2 `repr(e)` call-sites with `exc_info=True`

These log `repr(e)` AND the full traceback for exceptions that may originate from LLM HTTP calls:

| File | Line | Exception source | Risk |
|---|---|---|---|
| `src/api/routes/workflows.py` | 87–89 | OpenRouter embedding call | HIGH |
| `src/api/routes/workflows.py` | 136–138 | Entire graph (scout/orchestrator/tailor) | HIGH |
| `src/api/routes/workflows.py` | 261–263 | Entire graph catch-all | HIGH |
| `src/api/routes/workflows.py` | 349–351 | Streaming OpenRouter embedding | HIGH |
| `src/api/routes/workflows.py` | 508–510 | Streaming graph catch-all | HIGH |
| `src/api/routes/search.py` | 71–73 | OpenRouter embedding | HIGH |
| `src/agents/scout.py` | 260–262 | Tool calls (job_search_tool + scrape) | HIGH |
| `src/agents/scout.py` | 334–336 | Fallback tool calls | HIGH |
| `src/api/routes/jobs.py` | 65–67 | asyncpg DB error (may include DSN fragment) | MEDIUM |

Whether `repr(openai.AuthenticationError(...))` for the OpenRouter SDK actually contains the key
prefix in practice is tested in §OQ3 below. If it does, all HIGH-severity log sites above are
confirmed leaks.

#### 2.3 `str(e)` + `exc_info=e` call-sites (lower risk)

These log `str(e)` (not `repr`) and the traceback:
- `src/api/routes/auth.py:71,85,131` — DB exceptions (no key material expected)
- `src/api/routes/cv.py:64,152,180,194,202` — CV ingestion; line 64 uses OpenRouter Vision LLM

#### 2.4 `settings.py` — No `SecretStr` on top-level secrets

```python
# src/config/settings.py
openrouter_api_key: Optional[str] = Field(None, ...)
jwt_secret_key: str = Field(..., ...)
database_url: str = Field("postgresql+asyncpg://agentic_hire:...", ...)
```

None of the three critical secrets use `pydantic.SecretStr`. Pydantic v2's default `__repr__`
for `BaseSettings` prints all field values. If `config` is ever passed to a logger (even accidentally
via `{config!r}`), all three secrets are exposed. Currently no such call exists, but this is a
structural risk.

---

### 3. What Is Already Safe

- **All `HTTPException.detail` strings are static**: `"Invalid or expired token"`, `"User not found"`,
  `"Internal server error"`, etc. No raw exception, JWT, or key echoed in any HTTP exception detail.
- **JWT decode path** (`src/api/dependencies.py:70–73`): catches `ExpiredSignatureError`,
  `DecodeError`, `InvalidTokenError` — returns only generic 401 detail. No token echoed.
- **OpenRouter API key wrapped in `SecretStr`** at construction (`agents.py:31`, `cv.py:207`,
  `utils/__init__.py`) — so `repr(chat_openai_instance)` will not print the raw key. Whether
  `AuthenticationError.__str__()` includes it is separate (§OQ3).
- **No Authorization header logged anywhere**: `logging_middleware` logs only method/path/status/IP.
- **`backtrace=False`, `diagnose=False`**: loguru does not auto-inject local variable values.
- **`RequestTimingMiddleware`** (`src/api/middleware.py`) is defined but **never registered** in
  `main.py` — it is dead code.

---

### 4. Test Design Grounding

Phase 4 breaks into two sub-phases:

**Sub-phase A — Fix the confirmed leaks** (production code changes):
1. `workflows.py:144,269`: replace `str(e)` in `OrchestrateResponse.status` with a generic message
   (`"Graph execution failed"`) and keep `str(e)` only in the loguru call.
2. `workflows.py:513`: replace `str(e)` in the SSE error event `data.message` with a generic string.
3. `main.py:31`: replace `config.database_url` with `config.database_url.split("@")[-1]` (host/db
   only) or a structured log with credentials redacted.
4. `cv.py:55`: sanitize `ingestion_error` before DB write — log the full error internally, store
   only a generic message.

**Sub-phase B — Unit tests asserting the fixed behavior** (tests/unit/test_security_gate.py):

| Test | Trigger | Assert |
|---|---|---|
| `test_workflow_error_does_not_leak_exception_string` | Patch `build_graph` to raise `Exception("sk-or-fake-key-in-error")`, call `POST /api/workflows/search-jobs` | Response body does NOT contain `"sk-or-fake-key-in-error"` |
| `test_streaming_error_does_not_leak_exception_string` | Same but `POST /api/workflows/search-jobs/stream`, consume SSE until error event | SSE error event `data.message` does NOT contain the fake key string |
| `test_500_handler_hides_exception_in_production` | Patch a route to raise an `Exception("sk-or-secret-value")`, ensure `debug_mode=False` | 500 response `detail` is `"Internal server error"`, not the exception string |
| `test_422_password_field_not_echoed_in_response` | POST `/api/auth/signup` with `password=123` (invalid type or future constraint) | 422 body does NOT contain the submitted password value |
| `test_loguru_does_not_capture_database_url` (or fix sub-phase A.3 first) | Capture loguru output at startup | Log output does NOT contain the password portion of database_url |

**Implementation approach**: Use `unittest.mock.patch` for graph errors. Capture loguru output
with `loguru`'s `add(sink, ...)` with a `StringIO` sink in the test. Use `httpx.AsyncClient` +
`ASGITransport` with the existing integration test pattern where the DB is needed, or plain
TestClient where it is not.

---

## Code References

- `src/api/main.py:31` — `config.database_url` logged unconditionally
- `src/api/main.py:78–96` — global `Exception` handler; `str(exc)` in detail (debug only)
- `src/api/main.py:81–83` — `str(exc)` + `exc_info=exc` in log (always)
- `src/api/dependencies.py:70–73` — JWT decode failure → safe 401, no token echoed
- `src/api/routes/workflows.py:144` — `str(e)` in 200 response body (confirmed leak)
- `src/api/routes/workflows.py:269` — `str(e)` in 200 response body (confirmed leak)
- `src/api/routes/workflows.py:513` — `str(e)` in SSE error event (confirmed leak)
- `src/api/routes/cv.py:55` — `str(e)` stored in DB + returned via `/api/cv/status` (medium leak)
- `src/api/routes/workflows.py:87–89,136–138,261–263,349–351,508–510` — `repr(e)` + `exc_info=True`
- `src/agents/scout.py:260–262,334–336` — `repr(e)` + `exc_info=True` on tool calls
- `src/api/routes/search.py:71–73` — `repr(e)` + `exc_info=True` on embedding call
- `src/api/routes/jobs.py:65–67` — `repr(e)` + `exc_info=True` on DB call
- `src/config/settings.py:74–76,111,117` — `database_url`, `jwt_secret_key`, `openrouter_api_key` as plain `str`
- `src/api/schemas.py:88–89,98,104` — `password`, `refresh_token` fields in request models (latent 422 risk)
- `src/agents/agents.py:31` — OpenRouter key wrapped in `SecretStr` ✓
- `src/config/logging.py` — `backtrace=False`, `diagnose=False`, no redaction filter

---

## Architecture Insights

**The `str(e)` in 200-OK body is the most important finding.** It bypasses the `debug_mode`
guard entirely — it was introduced as "non-critical error info in the workflow response" but
creates an unconditional secret-leak path. The fix is simple (replace with a generic string)
and does not affect the `log` call that correctly records the exception internally.

**The `repr(e)` + `exc_info=True` pattern** in log call-sites is correct *if* the exception
objects from the OpenRouter SDK do not include the key in their `repr()`. The `SecretStr` wrapping
in `agents.py:31` protects the `ChatOpenAI` client repr, but an `AuthenticationError` raised
*inside* the SDK and propagated outward may construct its message string from the raw key before
`SecretStr` can mask it. This needs empirical verification (§OQ3).

**`diagnose=False` is the structural safeguard** that prevents loguru from auto-injecting local
variable values into tracebacks. If anyone ever adds `diagnose=True` to `logging.py`, every
`logger.error(..., exc_info=True)` call with a local variable holding `config.openrouter_api_key`
would produce a traceback that leaks the key. This is a configuration-level risk worth asserting.

---

## Historical Context

- `context/archive/2026-06-05-testing-streaming-resilience/research.md` — established the pattern of
  calling route handlers directly (bypassing httpx transport) for in-process testing. The same
  technique applies here: trigger errors by patching, capture responses directly.
- `context/archive/2026-06-01-testing-data-integrity/` — `AsyncClient + ASGITransport` pattern and
  SAVEPOINT fixture. Security gate tests may not need the real DB at all (unit-style).
- `context/archive/2026-06-05-testing-agent-logic-regression/` — established that LLM calls are
  always mocked in tests; the security gate tests follow the same mock-everything approach.

---

## Open Questions

1. **Does OpenRouter's SDK `AuthenticationError.__str__()` include the key string?** The key is
   wrapped in `SecretStr` at `agents.py:31`, but the SDK's internal HTTP client (httpx or requests)
   might include the `Authorization: Bearer sk-or-...` header in the error message before
   `SecretStr` can intercept. Needs empirical check: `str(openai.AuthenticationError(...))` with a
   real (invalid) key. If yes, all `repr(e)` log sites are confirmed HIGH-severity key leaks.

2. **Does `cv_file.ingestion_error` need sanitization before DB write, or before API response?**
   Storing the raw error in the DB is an internal audit trail; returning it to the user via
   `/api/cv/status` is the exposure. The fix could be in the route serializer (strip the field in
   the response) rather than in the DB write.

3. **Should the `repr(e)` → `type(e).__name__` fix be applied in Phase 4, or is that a separate
   hardening change?** The test plan scopes Phase 4 to "no secrets in error responses or logs" —
   the `repr(e)` log pattern is a log-side risk, not a response-side risk. If the test only asserts
   the response body, the log-side issues remain untested. Recommended: include at least one
   loguru-capture test to cover OQ1.

4. **`RequestValidationError` custom handler**: the 422 body currently never echoes `password`
   or `refresh_token` values because no type constraint fails for plain `str` fields. Should Phase 4
   add a custom handler that strips `input` from 422 errors for fields named `password`, `token`,
   `secret`, `key`? This is a defensive-coding improvement; test-plan §3 says "unit (trigger
   validation errors)" which implies yes.
