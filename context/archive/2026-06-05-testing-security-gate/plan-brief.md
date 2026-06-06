# Security Gate — Plan Brief

> Full plan: `context/changes/testing-security-gate/plan.md`
> Research: `context/changes/testing-security-gate/research.md`

## What & Why

Three confirmed surfaces in the production API embed raw exception strings (`str(e)`) directly
into HTTP response bodies — unconditionally, without any debug-mode gate. If the underlying
exception originates from an OpenRouter authentication failure, its message can contain
API key material. Phase 4 of the test-plan rollout fixes these surfaces, hardens the settings
layer against accidental secret repr exposure, and adds regression tests.

## Starting Point

`workflows.py:144,269` place `str(e)` into `OrchestrateResponse.status` (200 OK JSON);
`workflows.py:513` places `str(e)` into an SSE error event's `data.message`. All three
fire on any unhandled exception — no debug-mode guard. Additionally, `main.py:31` logs
the full `database_url` (including password) on every startup, and `openrouter_api_key`,
`jwt_secret_key`, and `database_url` are plain `str` fields in `AppConfig` with no repr
masking.

## Desired End State

Error responses return only static generic strings (`"Graph execution failed"`,
`"Workflow failed"`, `"Workflow error"`). The startup log shows only `host:port/dbname`.
The three sensitive `AppConfig` fields are `pydantic.SecretStr` — their `repr()` shows
`'**********'`. Four unit tests assert each surface independently, catching regressions
automatically.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| `repr(e)` log call-sites | Defer to follow-up change | Need empirical confirmation that OpenRouter SDK embeds key in AuthenticationError.__str__() before fixing | Plan |
| SecretStr migration scope | Include all three fields | Closes structural repr-exposure risk in the same pass; only 2–3 files touched | Plan |
| 422 custom handler | Skip | No constraints on sensitive fields today; risk is speculative | Plan |
| `cv.py:55` ValueError | Leave as-is | LLM rejection reason is user-relevant content, not a secret | Plan |
| Test location | `tests/unit/` subfolder | Matches test-plan taxonomy (unit vs integration split) | Plan |
| Startup log test | Include loguru sink capture | Regression-guards the fix against future log calls that re-add the full URL | Plan |

## Scope

**In scope:**
- Fix `str(e)` in `OrchestrateResponse.status` (x2) and SSE error event `data.message` (x1)
- Migrate `openrouter_api_key`, `jwt_secret_key`, `database_url` to `SecretStr` in settings.py
- Update all 7 call-sites that unwrap these fields as raw strings
- Redact `database_url` in `main.py:31` startup log
- Four unit tests in `tests/unit/test_security_gate.py`

**Out of scope:**
- `repr(e)` → `type(e).__name__` in log call-sites
- Custom 422 handler for `password`/`refresh_token` fields
- `cv.py:55` `ValueError` path (LLM rejection reasons are benign)
- `debug_mode=True` 500 handler (trusted-internal surface only)

## Architecture / Approach

Three independent phases ordered by increasing blast radius: (1) narrowest change —
substitute static strings for `str(e)` in `workflows.py` only; (2) settings layer —
`SecretStr` migration touching 6 files; (3) tests — `app.dependency_overrides` eliminates
the DB dependency, loguru sink captures startup log output.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Fix response-body leaks | `str(e)` removed from all 3 external response surfaces | Missing a fourth `str(e)` site in another endpoint |
| 2. SecretStr migration | Three AppConfig fields masked; startup log redacted | Call-site missed (grep will catch it; mypy will confirm) |
| 3. Unit tests | Four regression guards; `tests/unit/` subfolder created | Test vacuously passes if mock is misconfigured |

**Prerequisites:** Phases 1–2 must complete before Phase 3 (tests assert fixed behavior).
**Estimated effort:** ~1–2 sessions across 3 phases.

## Open Risks & Assumptions

- Whether `openai.AuthenticationError.__str__()` embeds the key prefix is still unverified;
  if it does, the `repr(e)` log sites remain HIGH severity and will need a follow-up pass.
- `pydantic-settings v2` coerces plain-string defaults to `SecretStr` automatically — this
  is documented behavior but should be verified during Phase 2 implementation.

## Success Criteria (Summary)

- POST `/api/workflows/search-jobs` with a mocked exception containing a fake key string
  returns a response body with no trace of that string.
- App startup log shows `host:port/dbname` only — no DSN password.
- `repr(config.openrouter_api_key)` prints `SecretStr('**********')`.
