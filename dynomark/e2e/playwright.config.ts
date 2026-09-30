// playwright.config.ts -- the integration e2e: the built extension in
// Chromium, the real native host and the real daemon (fake models), one
// scenario at a time (each owns a browser, a daemon and a socket). The global
// setup builds the extension and syncs the daemon first.

import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  globalSetup: './global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: 'list',
  outputDir: 'test-results',
});
