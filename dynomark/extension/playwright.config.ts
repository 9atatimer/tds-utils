// playwright.config.ts -- the e2e suite: the built extension (dist/) loaded
// unpacked in a real Chromium against a fake native host and daemon
// (test/support/). Each test launches its own browser and profile, so the
// suite runs one test at a time. Needs `npm run build` first.

import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: 'list',
  outputDir: 'test-results',
});
