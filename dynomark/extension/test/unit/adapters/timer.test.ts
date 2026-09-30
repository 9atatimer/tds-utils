// timer.test.ts -- the real Timer is setTimeout; it runs the Timer contract
// under Vitest's fake timers (the adapter is exactly the thing those fake, so
// there is no port below it to inject).

import { afterEach, beforeEach, vi } from 'vitest';
import { SystemTimer } from '../../../src/adapters/timer.js';
import { describeTimerContract } from '../../port-contracts/timer.contract.js';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describeTimerContract('SystemTimer', () => ({
  timer: new SystemTimer(),
  elapse: async (ms) => {
    await vi.advanceTimersByTimeAsync(ms);
  },
}));
