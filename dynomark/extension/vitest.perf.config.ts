// vitest.perf.config.ts -- the perf tier: wall-clock claims (Goal 4, tier 1)
// in test/perf. Run by `npm test` after the unit tier, one file at a time so
// no other test file competes for the CPU while samples are taken.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/perf/**/*.test.ts'],
    testTimeout: 30_000,
    fileParallelism: false,
  },
});
