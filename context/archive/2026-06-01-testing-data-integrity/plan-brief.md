# Data Integrity Integration Tests — Plan Brief

> Full plan: `context/changes/testing-data-integrity/plan.md`
> Research: `context/changes/testing-data-integrity/research.md`

## What & Why

Add the first real-DB integration test layer to the project, covering test-plan.md Phase 1 (Risks #1 and #2). The existing test suite is 100% `AsyncMock` — no SQL ever runs — which means evaluation persistence failures and user isolation gaps are invisible to the test runner. This change makes them visible.

## Starting Point

Both workflow endpoints already persist evaluations but swallow all DB exceptions silently; the API returns HTTP 200 with scores even when the write fails. Three repository methods have no user_id isolation: one is actively exploitable today (`create_or_update`), two are latent structural gaps.

## Desired End State

Four green integration tests run against a real PostgreSQL connection. `GET /api/jobs` after a workflow run returns a non-null `match_score` (proving the DB write, not the API response). A request authenticated as user B cannot list or overwrite user A's job rows. The three repository gaps are fixed. The full suite stays green.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Gap 1 fix scope | Fix `create_or_update` + test together | "Prove protection" requires the fix to exist before the test can pass | Plan |
| Latent gaps | Fix all three repository methods | Close structural issues in one pass while we're touching the file | Plan |
| Test DB | Separate `agentic_hire_test` database | Complete isolation — SAVEPOINT fixture bug cannot corrupt dev data | Plan |
| asyncio_mode | `"auto"` + `asyncio_default_fixture_loop_scope = "session"` | Cleaner test code; required for session-scoped async engine fixture | Plan |
| Session isolation | `join_transaction_mode="create_savepoint"` | Allows production `session.commit()` to commit to a savepoint so the outer rollback is preserved | Research |
| Risk #1 endpoint coverage | Both sync + streaming endpoints | Streaming has a unique double-masking risk; both paths share the same upsert but differ in task/lifecycle | Plan |
| Risk #1 assertion target | `GET /api/jobs` after workflow (not the workflow response JSON) | API swallows all persistence exceptions — response JSON cannot detect a failed write | Research |
| Risk #2 write test layer | Repository layer (not HTTP) | The isolation fix is in the repository; repository-level test is the right assertion layer and avoids mocking the full workflow for the write test | Plan |

## Scope

**In scope:**
- `pyproject.toml` asyncio config changes
- `.env.test` + test DB setup instructions
- `tests/integration/conftest.py` — full fixture stack (engine, SAVEPOINT session, two users, two HTTP clients)
- `src/db/repositories.py` — three repository fixes (`create_or_update`, `get_by_id`, `get_by_job_id`)
- `tests/integration/test_evaluation_persistence.py` — 2 tests (sync + streaming)
- `tests/integration/test_user_isolation.py` — 2 tests (list isolation + write protection)

**Out of scope:**
- Risk #3 (streaming zombie disconnect) — Phase 3 of the rollout
- Risk #4 (secrets in error responses) — Phase 4
- Testing LangGraph execution — `build_graph` is mocked in all integration tests
- Adding a `GET /api/jobs/{id}` route — latent gaps are fixed defensively; no new route is created

## Architecture / Approach

All integration tests share a single SAVEPOINT-backed session per test. The `test_engine` fixture (session-scoped) creates the test DB schema once; the `real_session` fixture (function-scoped) wraps each test in an outer transaction with `join_transaction_mode="create_savepoint"` so that production `session.commit()` calls commit to a savepoint. `await conn.rollback()` in fixture teardown undoes all test inserts without truncating tables.

HTTP-layer tests override `get_current_user` and `get_db` via FastAPI's `dependency_overrides`. `build_graph` is patched to return a canned state so no LLM call is made.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Infrastructure | pytest config, test DB, SAVEPOINT session, two-user HTTP client fixtures | `asyncio_default_fixture_loop_scope` misconfiguration breaks session-scoped async fixtures |
| 2. Repository fixes | User_id ownership check on `create_or_update`; scoped signatures on `get_by_id` / `get_by_job_id` | Adding `user_id` param to `get_by_id` may reveal a hidden caller not caught by mypy |
| 3. Risk #1 tests | Sync + streaming persistence tests asserting `match_score` non-null in DB | Streaming async generator mock is easy to get wrong — `mock.return_value` won't work for `astream` |
| 4. Risk #2 tests | List isolation + write protection regression guard | Cross-user write test must be verified red before Phase 2 to confirm test quality |

**Prerequisites:** PostgreSQL running (`docker-compose up`); test DB created (`CREATE DATABASE agentic_hire_test;`); `AGENTIC_HIRE_DATABASE_URL` env var set to the test DB URL.  
**Estimated effort:** ~1 session across 4 phases

## Open Risks & Assumptions

- `UserRepository.create` takes `email` and `password_hash` (as stated in research). If the signature differs, adjust the `user_a`/`user_b` fixtures accordingly.
- The `WorkflowRequest` schema for `POST /api/workflows/search-jobs` has required fields that must be supplied in the integration test POST body. Implementer should check the schema before writing the test.
- If `Job.id` has a globally-unique DB constraint (primary key), the cross-user write test will produce a constraint error (not a silent overwrite) against the unfixed `create_or_update`. The test should still catch this as a "test would fail without fix" signal.

## Success Criteria (Summary)

- `uv run pytest tests/integration/ -v` → 4 green tests with real PostgreSQL connections
- `GET /api/jobs` after workflow returns `match_score` ≠ null for shortlisted jobs
- User B's `GET /api/jobs` returns an empty list when only user A has seeded jobs
