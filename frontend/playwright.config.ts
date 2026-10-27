import { defineConfig, devices } from "@playwright/test";

// The API must already be running at NEXT_PUBLIC_API_URL (default localhost:8000).
// With PLAYWRIGHT_BASE_URL set (CI starts the built server itself) no dev server is started.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const external = process.env.PLAYWRIGHT_BASE_URL;
const PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: external || `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: external
    ? undefined
    : {
        command: `npm run dev -- --port ${PORT} --hostname 127.0.0.1`,
        url: `http://127.0.0.1:${PORT}`,
        env: { NEXT_PUBLIC_API_URL: API_URL, API_URL },
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
});
