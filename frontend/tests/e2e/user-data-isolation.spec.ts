/**
 * Risk: user data isolation (test-plan.md §2 Risk #2)
 * Scope: rendered UI — User B's authenticated session must not display
 * User A's jobs list or CV status, even when User A has real DB rows.
 *
 * Seed: frontend/seed.spec.ts
 * Rules: frontend/tests/e2e/e2e-rules.md
 *
 * Auth pattern: beforeAll creates storageState for User B, each test loads
 * it via browser.newContext() — avoids the test.use() ordering constraint
 * (test.use is evaluated before beforeAll writes the file).
 */

import fs from "fs";
import { test, expect } from "@playwright/test";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";
const STORAGE_STATE = "playwright/.auth/user-b.json";

test.describe("user data isolation — jobs and CV surfaces", () => {
  test.describe.configure({ mode: "serial" });

  let userAEmail: string;
  let userBEmail: string;
  const PASSWORD = "IsoTest1!";

  test.beforeAll(async ({ browser, request }) => {
    // Unique suffix: prevents unique-constraint collisions in parallel runs
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 5)}`;
    userAEmail = `iso-a-${suffix}@example.com`;
    userBEmail = `iso-b-${suffix}@example.com`;

    // Create User A
    const resA = await request.post(`${BACKEND_URL}/api/signup`, {
      data: { email: userAEmail, password: PASSWORD, password_confirm: PASSWORD },
    });
    expect(resA.status()).toBe(200);

    // Create User B and capture token
    const resB = await request.post(`${BACKEND_URL}/api/signup`, {
      data: { email: userBEmail, password: PASSWORD, password_confirm: PASSWORD },
    });
    expect(resB.status()).toBe(200);
    const { access_token: userBToken } = (await resB.json()) as {
      access_token: string;
    };

    // Seed User A's data — job + CV file (no workflow needed)
    await request.post(`${BACKEND_URL}/api/internal/test-jobs`, {
      data: { email: userAEmail },
    });
    await request.post(`${BACKEND_URL}/api/internal/test-cv-file`, {
      data: { email: userAEmail },
    });

    // Persist User B's auth cookie as storageState
    // Tests load this via browser.newContext() at run time, after this file exists
    fs.mkdirSync("playwright/.auth", { recursive: true });
    const ctx = await browser.newContext();
    await ctx.addCookies([
      {
        name: "access_token",
        value: userBToken,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    await ctx.storageState({ path: STORAGE_STATE });
    await ctx.close();
  });

  test.afterAll(async ({ request }) => {
    // Hard-delete both users; ON DELETE CASCADE removes all seeded rows
    await request.delete(`${BACKEND_URL}/api/internal/test-users`, {
      data: { email: userAEmail },
    });
    await request.delete(`${BACKEND_URL}/api/internal/test-users`, {
      data: { email: userBEmail },
    });
  });

  test("User B's jobs page shows no jobs when only User A has jobs", async ({
    browser,
  }) => {
    // Load User B's auth state at test-run time (file exists after beforeAll)
    const ctx = await browser.newContext({ storageState: STORAGE_STATE });
    const page = await ctx.newPage();

    // Wait for the data fetch, not a timeout
    const [response] = await Promise.all([
      page.waitForResponse("**/api/jobs**"),
      page.goto("/dashboard/jobs"),
    ]);
    expect(response.status()).toBe(200);

    // Business outcome: User B sees empty state — not User A's job title
    await expect(page.getByText("No jobs yet")).toBeVisible();
    await ctx.close();
  });

  test("User B's dashboard shows no CV when only User A has a CV", async ({
    browser,
  }) => {
    const ctx = await browser.newContext({ storageState: STORAGE_STATE });
    const page = await ctx.newPage();

    // Wait for CV status response, not a timeout
    const [response] = await Promise.all([
      page.waitForResponse("**/api/cv/status**"),
      page.goto("/dashboard"),
    ]);
    expect(response.status()).toBe(200);

    // Business outcome: upload drop zone visible — not User A's CV filename
    await expect(page.getByText(/drop your pdf here/i)).toBeVisible();
    await ctx.close();
  });
});