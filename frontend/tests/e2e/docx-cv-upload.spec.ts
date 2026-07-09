/**
 * Risk: DOCX CV upload (docx-cv-upload-support plan, Phase 3 — deferred E2E
 * follow-up; see plan.md "What We're NOT Doing").
 * Scope: rendered UI — the upload widget must accept a real .docx file and
 * carry it through a real multipart POST to the backend, which must persist
 * it and begin ingestion. Crosses: frontend upload widget (client-side MIME
 * gate), Next.js API proxy, FastAPI upload endpoint, DB (CVFile row).
 *
 * Does not wait for ingestion_status to reach "completed" — that requires a
 * real Vision-LLM call (non-deterministic, costs money) and is already
 * covered by this plan's manual verification. This test protects the
 * browser-level contract: DOCX is accepted end-to-end through to
 * "processing", not silently rejected by a client-side PDF-only check.
 *
 * Seed: frontend/seed.spec.ts
 * Rules: frontend/tests/e2e/e2e-rules.md
 *
 * Auth pattern: signup via API, cookie set directly (mirrors
 * user-data-isolation.spec.ts) — avoids going through the login UI.
 */

import path from "path";
import { test, expect } from "@playwright/test";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";
const FIXTURE_DOCX = path.join(__dirname, "fixtures", "sample-cv.docx");

test.describe("docx cv upload — browser-level acceptance", () => {
  let testEmail: string;
  const PASSWORD = "DocxTest1!";

  test.beforeEach(async ({ page, request }) => {
    // Timestamp + random hex: prevents collisions between parallel workers
    testEmail = `docx-e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`;
    const res = await request.post(`${BACKEND_URL}/api/signup`, {
      data: { email: testEmail, password: PASSWORD, password_confirm: PASSWORD },
    });
    expect(res.status()).toBe(200);
    const { access_token: accessToken } = (await res.json()) as {
      access_token: string;
    };

    await page.context().addCookies([
      {
        name: "access_token",
        value: accessToken,
        domain: "localhost",
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
  });

  test.afterEach(async ({ request }) => {
    // Hard-delete the test user so the next run never hits a unique-constraint error.
    await request.delete(`${BACKEND_URL}/api/internal/test-users`, {
      data: { email: testEmail },
    });
  });

  test("a real .docx CV is accepted by the upload widget and reaches processing", async ({
    page,
  }) => {
    await page.goto("/dashboard/cv");

    // Drive the upload through the accessible dropzone, not the raw <input>
    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page
        .getByRole("button", { name: /drag & drop your cv here/i })
        .click(),
    ]);

    // Trigger the file selection and the resulting upload POST together —
    // wait for the real network response, not a timeout.
    const [uploadResponse] = await Promise.all([
      page.waitForResponse("**/api/cv/upload"),
      fileChooser.setFiles(FIXTURE_DOCX),
    ]);

    // Business outcome #1: the backend accepted the real multipart upload.
    expect(uploadResponse.status()).toBe(202);

    // Business outcome #2: the UI reflects that ingestion has started — proof
    // the client-side MIME gate let a .docx through and the request round-tripped.
    await expect(page.getByText(/processing cv/i)).toBeVisible();
  });
});
