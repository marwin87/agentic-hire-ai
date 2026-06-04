# E2E Auth Isolation Implementation Plan

## Overview

Browser-level E2E coverage for **test-plan.md Risk #2** (user data isolation). Two phases: extend the test-support API with job and CV seeding endpoints; write the user-data-isolation spec that proves User B's authenticated browser session cannot see User A's jobs or CV in the rendered UI.

## Current State Analysis

- `seed.spec.ts`: exists, green. Covers the auth boundary (login redirect + dashboard access for a single user).
- `playwright.config.ts`: configured — `baseURL=http://localhost:3000`, backend at port 8001.
- `src/api/routes/testing.py`: has `DELETE /api/internal/test-users` (debug_mode-guarded). No seeding endpoints yet.
- `frontend/app/dashboard/jobs/page.tsx`: renders `GET /api/jobs` list filtered per authenticated user. Shows "No jobs yet" (text) when the list is empty.
- `frontend/app/dashboard/page.tsx`: CV upload panel calls `GET /api/cv/status → {has_cv, filename}`. When `has_cv: false` it renders an idle/upload button; when `has_cv: true` it renders the filename and a "Replace CV" button.
- `Job` model (DB): `id` (String 255, PK — caller-supplied), `user_id` (FK, NOT NULL), `title`, `company`, `url` (all NOT NULL), `description`/`salary_range` optional, `discovered_at`/`created_at` auto.
- `CVFile` model (DB): `id` (UUID, auto), `user_id` (FK, NOT NULL), `file_path` (String 512, NOT NULL), `file_hash` (String 64, NOT NULL), `ingested_at`/`updated_at` auto.
- Auth cookie: `access_token` (httpOnly, path="/") — set by backend signup/login, read by Next.js middleware. Constant defined in `frontend/lib/api.ts:5`.

## Desired End State

`POST /api/internal/test-jobs` and `POST /api/internal/test-cv-file` exist and are debug_mode-guarded identically to the delete endpoint. A green E2E spec (`user-data-isolation.spec.ts`) creates two real users, seeds User A's data, and proves via the rendered browser UI that User B's session shows an empty jobs list and a no-CV (upload) state. The spec cleans up after itself via `afterAll`.

### Key Discoveries

- `Job.id` is a caller-supplied `String(255)` primary key (not a UUID default). The seeding endpoint must generate a synthetic id (e.g., `f"test-job-{uuid4().hex}"`).
- `CVFile.file_hash` is NOT NULL and has no default — the seeding endpoint must supply a synthetic value.
- The dashboard's CV panel uses `has_cv: false` to decide which branch to render. Seeding a `CVFile` row for User A (with any synthetic path/hash) is sufficient to flip that flag in the backend's status check, without needing a real embedding.
- `playwright/.auth/` is already in `.gitignore` (added when Playwright was set up).
- `debug_mode` is confirmed `true` in the running dev Docker stack.

## What We're NOT Doing

- Running the full LangGraph workflow in any test — too slow and non-deterministic.
- Testing job deletion cross-user isolation — API-level; covered by archived integration tests.
- Testing CV embedding quality or chunk retrieval — that is Phase 2 (agent-logic regression) in test-plan.md.
- Testing the `/dashboard/cv/page.tsx` page separately — we verify isolation via the CV panel embedded in `/dashboard`.

## Implementation Approach

Phase 1 extends `testing.py` with two minimal seeding endpoints that resolve a user by email and insert a synthetic row. Phase 2 writes the isolation spec: `beforeAll` creates both users, seeds User A, saves User B's `storageState` by constructing a browser context with the `access_token` cookie; two tests load that state and assert the empty-state UIs; `afterAll` cleans up.

---

## Phase 1: Test-support seeding endpoints

### Overview

Extend `src/api/routes/testing.py` with two new debug-only endpoints that let E2E tests insert minimal Job and CVFile rows for a given user. No workflow execution required.

### Changes Required

#### 1. Two new endpoints in `testing.py`

**File**: `src/api/routes/testing.py`

**Intent**: Add `POST /api/internal/test-jobs` and `POST /api/internal/test-cv-file`. Each resolves the target user by email (same pattern as the delete endpoint), inserts one synthetic row, and returns 204. Both are guarded by `_require_debug()`.

**Contract**:

`POST /api/internal/test-jobs` — request body `{ "email": str }`. Look up user by email (404 if absent). Insert one `Job` row:
- `id = f"test-job-{uuid4().hex}"` (synthetic, no real Scout id)
- `user_id = user.id`
- `title = "Test Job (E2E seed)"`, `company = "Test Corp"`, `url = "https://example.com/test-job"`
- all other fields nullable/auto

`POST /api/internal/test-cv-file` — request body `{ "email": str }`. Look up user by email (404 if absent). Insert one `CVFile` row:
- `file_path = "test/synthetic-cv.pdf"`
- `file_hash = f"test-{uuid4().hex[:8]}"` (must be unique to avoid hash collisions across parallel test runs)

Both use `uuid4` from Python's `uuid` module (already available). Import `CVFile` and `Job` from `src.db`.

### Success Criteria

#### Automated Verification

- `uv run mypy src/api/routes/testing.py --no-error-summary` exits 0
- `uv run black --quiet src/api/routes/testing.py` exits 0
- `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8001/api/internal/test-jobs -H "Content-Type: application/json" -d '{"email":"probe-test@example.com"}'` returns `204`
- `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8001/api/internal/test-cv-file -H "Content-Type: application/json" -d '{"email":"probe-test@example.com"}'` returns `204`

#### Manual Verification

- Confirm the `Job` row is visible in the DB for the probe user's `user_id` after the curl above.
- Confirm the `CVFile` row is visible in the DB for the probe user after the second curl.

**After this phase passes automated + manual verification, pause for confirmation before committing.**

---

## Phase 2: E2E user-data-isolation spec

### Overview

Write the isolation spec that proves Risk #2 is protected in the rendered UI. User B's authenticated browser session must not expose User A's jobs or CV filename, even when User A has real DB rows.

### Changes Required

#### 1. E2E rules file (quality lever)

**File**: `frontend/tests/e2e/e2e-rules.md`

**Intent**: The rules file the agent reads automatically before generating E2E code. Constrains locators, wait strategy, auth pattern, data isolation, and cleanup. Copied verbatim from the `/10x-e2e/references/e2e-quality-rules.md` rules block.

**Contract**: Contains the Playwright rules block (getByRole/getByLabel/getByText first, no CSS selectors/XPath, independent tests, no waitForTimeout, storageState for auth, unique ids + cleanup, risk-named tests).

#### 2. User-data-isolation spec

**File**: `frontend/tests/e2e/user-data-isolation.spec.ts`

**Intent**: Two-user isolation test for test-plan.md Risk #2. User B's authenticated session must render the empty-state UIs for both the jobs list and the CV panel when only User A has data.

**Contract**:

`beforeAll({ browser, request })`:
1. Generate unique email pair with timestamp + random suffix (same pattern as `seed.spec.ts`).
2. Create both users via `POST http://localhost:8001/api/signup`. Extract `access_token` from each response (signup also returns the token).
3. Seed User A's data:
   - `POST http://localhost:8001/api/internal/test-jobs` body `{ email: userAEmail }`
   - `POST http://localhost:8001/api/internal/test-cv-file` body `{ email: userAEmail }`
4. Build User B's browser context: `browser.newContext()`, inject the `access_token` cookie via `context.addCookies([{ name: "access_token", value: userBToken, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax" }])`, save storageState to `playwright/.auth/user-b.json`, close context.

`test.use({ storageState: "playwright/.auth/user-b.json" })` at describe-level — all tests run as User B.

`afterAll({ request })`:
- `DELETE http://localhost:8001/api/internal/test-users` body `{ email: userAEmail }`
- `DELETE http://localhost:8001/api/internal/test-users` body `{ email: userBEmail }`
- Both cascade-delete all seeded rows.

**Test 1**: `"User B's jobs page shows no jobs when only User A has jobs"`
- Navigate to `/dashboard/jobs`
- `waitForResponse("**/api/jobs**")` (wait for the data fetch, not a timeout)
- Assert: `expect(page.getByText("No jobs yet")).toBeVisible()`
- Control question: would this fail if isolation broke? Yes — User A's job title would render instead of the empty state.

**Test 2**: `"User B's dashboard shows no CV when only User A has a CV"`
- Navigate to `/dashboard`
- `waitForResponse("**/api/cv/status**")`
- Assert: the CV panel is in idle/upload state. The upload drop zone is rendered only when `has_cv: false`.
  Use: `expect(page.getByText(/drop your pdf here/i)).toBeVisible()`
- Control question: would this fail if isolation broke? Yes — User A's CV filename would render and the drop zone would be hidden.

### Success Criteria

#### Automated Verification

- `npx playwright test tests/e2e/user-data-isolation.spec.ts` exits 0 (both tests green)
- After run: a second `DELETE /api/internal/test-users` for each email returns 404 (users are gone)

#### Manual Verification

- Deliberate-break check (Test 1): temporarily comment out the `user_id` filter in `JobRepository.get_jobs_with_scores` and re-run. Test must go RED. Revert immediately.
- Deliberate-break check (Test 2): temporarily comment out the `user_id` filter in the CV status lookup (`CVFileRepository.get_latest_by_user`). Re-run. Test must go RED. Revert immediately.
- Confirm `playwright/.auth/user-b.json` is not staged or tracked by git.

**After this phase passes automated + manual verification, pause for confirmation before committing.**

---

## Testing Strategy

### Automated
- `npx playwright test tests/e2e/user-data-isolation.spec.ts` — full isolation spec (2 tests)
- mypy + black on `testing.py` (Phase 1)

### Manual
- Deliberate-break checks per test (described in Phase 2 manual criteria)

## References

- Risk: `context/foundation/test-plan.md` §2 Risk #2 (user data isolation)
- Seed exemplar: `frontend/seed.spec.ts`
- Testing API: `src/api/routes/testing.py`
- DB models: `src/db/models.py` (Job lines 100–139, CVFile lines 51–75)
- Auth cookie: `frontend/lib/api.ts:5` (`"access_token"`)
- E2E rules source: `/Users/mariusz/.claude/skills/10x-e2e/references/e2e-quality-rules.md`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Test-support seeding endpoints

#### Automated

- [x] 1.1 mypy and black pass on testing.py after additions
- [x] 1.2 POST /api/internal/test-jobs returns 204 for existing user email
- [x] 1.3 POST /api/internal/test-cv-file returns 204 for existing user email

#### Manual

- [x] 1.4 Job row visible in DB for probe user after seeding
- [x] 1.5 CVFile row visible in DB for probe user after seeding

### Phase 2: E2E user-data-isolation spec

#### Automated

- [x] 2.1 npx playwright test tests/e2e/user-data-isolation.spec.ts passes green (2 tests)
- [x] 2.2 afterAll cleanup: re-delete of both test emails returns 404

#### Manual

- [x] 2.3 Deliberate-break Test 1 (jobs user_id filter): test goes red, revert restores green
- [x] 2.4 Deliberate-break Test 2 (CV status user_id filter): test goes red, revert restores green
- [x] 2.5 playwright/.auth/user-b.json not committed
