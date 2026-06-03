/**
 * seed.spec.ts — exemplar E2E test for this codebase.
 *
 * Risk: user data isolation (test-plan.md §2 Risk #2)
 * Scope: authentication boundary — a user who cannot authenticate as another
 * cannot reach their evaluation data. Crosses: Next.js routing, cookie auth,
 * FastAPI session validation.
 *
 * Copy this file when adding a new E2E test. Adapt:
 *   – test name  → name it after the risk, not the action
 *   – assertions → assert the business outcome, not the DOM shape
 *   – mocked boundaries → mock at the network layer (page.route) for
 *     external APIs (LLMs, OrioSearch); keep auth/routing/DB real
 */

import { test, expect } from "@playwright/test";

// Backend URL used only for API-level setup/teardown (not the frontend proxy)
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

test.describe("user data isolation — authentication boundary", () => {
  let testEmail: string;
  const PASSWORD = "Seed1234!";

  test.beforeEach(async ({ request }) => {
    // Unique suffix: prevents unique-constraint violations in parallel runs
    testEmail = `seed-${Date.now()}@example.com`;
    const res = await request.post(`${BACKEND_URL}/api/signup`, {
      data: { email: testEmail, password: PASSWORD, password_confirm: PASSWORD },
    });
    expect(res.status()).toBe(201);
  });

  test.afterEach(async ({ request }) => {
    // Hard-delete the test user so the next run never hits a unique-constraint error.
    // Requires: DELETE /api/internal/test-users (test-support endpoint — not yet implemented;
    // add it before wiring this suite into CI).
    await request.delete(`${BACKEND_URL}/api/internal/test-users`, {
      data: { email: testEmail },
    });
  });

  test("unauthenticated request to /dashboard is redirected to /login", async ({ page }) => {
    // Cold start: no cookies, no stored auth state
    await page.goto("/dashboard");

    // Wait for the redirect to complete — never waitForTimeout
    await page.waitForURL("**/login");

    // Business outcome: unauthenticated users cannot reach evaluation data
    await expect(
      page.getByRole("heading", { name: /agentichire ai/i })
    ).toBeVisible();
  });

  test("valid credentials grant access to the job-search dashboard", async ({ page }) => {
    await page.goto("/login");

    // Primary locators: getByRole + accessible name; no CSS selectors
    await page.getByRole("textbox", { name: /email/i }).fill(testEmail);
    await page.getByRole("textbox", { name: /password/i }).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();

    // Wait for navigation — not a timeout
    await page.waitForURL("**/dashboard");

    // Business outcome: authenticated user sees their own workflow entry point
    await expect(
      page.getByRole("button", { name: /search/i })
    ).toBeVisible();

    // Persist auth state — tests that need an authenticated context load
    // playwright/.auth/user.json via storageState in playwright.config.ts
    // instead of going through the login UI in each test.
    await page.context().storageState({ path: "playwright/.auth/user.json" });
  });
});
