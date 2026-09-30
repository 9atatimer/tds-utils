// clock.contract.ts -- what every Clock must do; the fake runs it now, the
// real adapter will run the same suite.

import { describe, expect, it } from 'vitest';
import type { Clock } from '../../src/ports/clock.js';

/** Registers the Clock contract suite for one implementation. */
export function describeClockContract(name: string, make: () => Clock): void {
  describe(`Clock contract -- ${name}`, () => {
    it('Given a clock, When read, Then it returns EpochMs: a non-negative safe integer', () => {
      const now = make().now();
      expect(Number.isSafeInteger(now)).toBe(true);
      expect(now).toBeGreaterThanOrEqual(0);
    });

    it('Given successive reads, When compared, Then time never goes backwards', () => {
      const clock = make();
      const reads = Array.from({ length: 50 }, () => clock.now());
      expect(reads).toEqual([...reads].sort((a, b) => a - b));
    });
  });
}
