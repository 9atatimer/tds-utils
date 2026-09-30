// FakeClock.ts -- an in-memory Clock that moves only when a test advances it.

import type { Clock } from '../../src/ports/clock.js';
import type { EpochMs } from '../../src/domain/values.js';

export class FakeClock implements Clock {
  private t: EpochMs;

  constructor(start: EpochMs) {
    this.t = start;
  }

  now(): EpochMs {
    return this.t;
  }

  /** Move time forward by `ms`; a negative step throws, as real time never runs backwards. */
  advance(ms: number): void {
    if (ms < 0) throw new RangeError(`FakeClock cannot move backwards (${ms} ms)`);
    this.t += ms;
  }
}
