import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8787;
const WEB_PORT = 4173;
const chromium = process.env.PLAYWRIGHT_CHROMIUM_PATH;

/**
 * E2E runs against the production build (with the service worker) and the real
 * API process using in-memory storage. `npm run test:e2e` builds `dist-e2e` first.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    locale: "ru-RU",
    trace: "retain-on-failure",
    launchOptions: chromium ? { executablePath: chromium, args: ["--no-sandbox"] } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: "npx tsx apps/api/src/server.ts",
      url: `http://localhost:${API_PORT}/health`,
      env: { PORT: String(API_PORT), NODE_ENV: "test", DATABASE_URL: "" },
      reuseExistingServer: false,
    },
    {
      command: `npx vite preview --port ${WEB_PORT} --strictPort --outDir dist-e2e`,
      cwd: "apps/web",
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
    },
  ],
});
