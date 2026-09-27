// vitest.config.ts -- one node-environment project; the three test trees are
// test/unit (pure, all ports faked), test/contract (golden contract files; the
// one allowed fixture I/O) and test/arch (mechanical layer checks over src/).
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
    testTimeout: 1000,
  },
});
