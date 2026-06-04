# E2E Auth Isolation — Plan Brief

> Full plan: `context/changes/e2e-auth-isolation/plan.md`

## What & Why

Add browser-level E2E coverage for **test-plan.md Risk #2** — user data isolation. The integration layer (archived `testing-data-integrity`) proves the DB queries are scoped correctly; this plan proves the rendered UI respects those boundaries. If isolation broke, User B's browser session would display User A's job list and CV filename.

## Starting Point

`seed.spec.ts` is green and covers the auth boundary (login redirect + dashboard access). The test-support API has `DELETE /api/internal/test-users` but no seeding endpoints. The `/dashboard/jobs` page and the dashboard's CV panel are both live features that render user-scoped data.

## Desired End State

Two new debug-only backend endpoints seed synthetic Job and CVFile rows for any test user. A green two-test spec (`user-data-isolation.spec.ts`) creates real User A and User B, seeds User A's data, and asserts via User B's browser session that both `/dashboard/jobs` and `/dashboard` (CV panel) show their empty states. The spec cleans up both users after every run.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Test data strategy | Real DB rows via `POST /api/internal/test-jobs` and `/test-cv-file` | Mocking the API response tests only rendering, not the actual DB query isolation | Plan |
| Data surfaces | Jobs list + CV panel | User chose broader coverage; CV status is a lightweight check (just the `has_cv` flag) | Plan Q&A |
| Auth in tests | API login → cookie injection → storageState | Faster than UI login and avoids making the login form a dependency of isolation tests | Plan Q&A |
| Cleanup | `DELETE /api/internal/test-users` (cascade) | debug_mode confirmed true; cascade removes all seeded rows in one call | Plan Q&A |

## Scope

**In scope:**
- `POST /api/internal/test-jobs` (seed one Job row by email)
- `POST /api/internal/test-cv-file` (seed one CVFile row by email)
- E2E rules file (`tests/e2e/e2e-rules.md`) — missing quality lever
- `tests/e2e/user-data-isolation.spec.ts` — two-user isolation spec

**Out of scope:**
- Running the LangGraph workflow in any test
- CV embedding or chunk-level isolation (no real file or embedding needed)
- Job deletion cross-user isolation (covered by integration tests)
- Any page outside `/dashboard/jobs` and `/dashboard`

## Architecture / Approach

`beforeAll` creates both users via the backend signup API, seeds User A's data, then injects User B's `access_token` cookie into a headless browser context and saves it as `playwright/.auth/user-b.json`. Tests load that state and navigate to the two pages. `afterAll` deletes both users (cascade cleans all rows).

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Test-support seeding endpoints | `POST /api/internal/test-jobs` and `/test-cv-file`, mypy+black clean | CVFile `file_hash` NOT NULL — synthetic value must be unique per run to avoid hash collisions |
| 2. E2E user-data-isolation spec | Two green browser tests proving jobs + CV isolation in rendered UI | Cookie injection (`addCookies`) must match exact cookie attributes set by the backend |

**Prerequisites:** `debug_mode=true` in running stack (confirmed); `seed.spec.ts` green (confirmed); `DELETE /api/internal/test-users` working (confirmed)
**Estimated effort:** ~1 session across 2 phases

## Open Risks & Assumptions

- `addCookies` cookie attributes (`sameSite`, `httpOnly`, `domain`) must match what the backend sets — mismatch causes silent auth failure. Cross-check `AUTH_COOKIE_OPTIONS` in `frontend/lib/api.ts` when implementing.
- The CV panel's "drop zone" text (`"Drop your PDF here"`) is used as the assertion anchor — it breaks if that copy changes. The plan author accepted this as the most semantically stable locator available.

## Success Criteria (Summary)

- Both E2E tests pass green with real User A data seeded in the DB
- Deliberate-break checks (commenting out `user_id` filters) turn each test red
- `playwright/.auth/user-b.json` never committed
