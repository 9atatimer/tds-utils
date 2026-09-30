// vitest.integration.config.ts -- the integration tier: port contract suites
// against the real chrome adapters in a real Chromium (test/integration).
// Needs dist/ built; run by `npm run e2e`, never by `npm test`.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/integration/**/*.test.ts'],
    testTimeout: 30_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
});
