import { defineConfig, devices } from '@playwright/test';

// Two suites, each skipped unless its environment is configured:
// - `staging`: M0 OIDC acceptance against a deployed host (RADBRAIN_STAGING_*).
// - `e2e`: the synthetic study flow against the CI Compose stack (RADBRAIN_E2E_*).
// Traces, screenshots, and video stay off: no browser artifacts (ADR 0005).
export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  reporter: [['line']],
  use: {
    ...devices['Desktop Chrome'],
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off'
  },
  projects: [
    { name: 'staging', testMatch: 'm0-staging.spec.ts' },
    { name: 'e2e', testMatch: 'study-flow.spec.ts' }
  ]
});
