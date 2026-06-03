import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",

  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },

  projects: [
    // Setup project: runs before any test that depends on authenticated state.
    // Tests that need auth declare: test.use({ storageState: 'playwright/.auth/user.json' })
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
      dependencies: ["setup"],
    },
  ],

  // Start both servers before running tests.
  // Adjust commands to match your local dev setup.
  webServer: [
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "docker-compose up api",
      cwd: "..",
      url: "http://localhost:8001/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
