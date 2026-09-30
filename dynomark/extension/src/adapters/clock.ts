// clock.ts -- the Clock adapter: the wall clock, held monotonic (a Clock never
// goes backwards; the system clock can, e.g. after an NTP step).

import type { EpochMs } from '../domain/values.js';
import type { Clock } from '../ports/clock.js';

export class SystemClock implements Clock {
  private last = 0;

  constructor(private readonly wall: () => number = () => Date.now()) {}

  now(): EpochMs {
    this.last = Math.max(this.last, Math.floor(this.wall()));
    return this.last;
  }
}
