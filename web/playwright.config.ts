import { defineConfig } from "@playwright/test";

/**
 * End-to-end journey in a real browser: sign-in (API token or OIDC popup, depending on what the
 * backend announces in /v1/public-config), search, source, and a chat question when E2E_CHAT=1.
 * The backend (and the OIDC issuer, if any) run separately; Playwright only starts the front.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 900 },
    video: process.env.E2E_VIDEO ? { mode: "on", size: { width: 1440, height: 900 } } : "off",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    env: {
      VITE_API_URL: process.env.E2E_API ?? "http://127.0.0.1:8790",
    },
  },
});
