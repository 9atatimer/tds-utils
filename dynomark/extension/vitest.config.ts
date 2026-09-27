// vitest.config.ts -- the unit tier: one node-environment project over
// test/unit (pure, all ports faked), test/contract (golden contract files; the
// one allowed fixture I/O) and test/arch (mechanical layer checks over src/).
// test/integration (a real browser) has its own config and runs in `npm run e2e`.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
    exclude: ['test/integration/**', 'node_modules/**'],
    testTimeout: 1000,
  },
});
