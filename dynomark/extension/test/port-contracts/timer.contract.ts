// timer.contract.ts -- what every Timer must do: run a callback once its
// delay has elapsed, in due order, never before, never after cancel. The
// debounce of tier-2 search and of tree.snapshot, and reconnect backoff, rest
// on it.

import { describe, expect, it } from 'vitest';
import type { Timer } from '../../src/ports/timer.js';

/** A Timer plus the out-of-band way to let time pass. */
export interface TimerHarness {
  readonly timer: Timer;
  elapse(ms: number): Promise<void>;
}

/** Registers the Timer contract suite for one implementation. */
export function describeTimerContract(name: string, make: () => TimerHarness): void {
  describe(`Timer contract -- ${name}`, () => {
    it('Given a callback due in 100 ms, When 99 ms pass, Then it has not run; When 1 more passes, Then it has run once', async () => {
      const { timer, elapse } = make();
      const calls: string[] = [];
      timer.after(100, () => calls.push('due'));
      await elapse(99);
      expect(calls).toEqual([]);
      await elapse(1);
      await elapse(500);
      expect(calls).toEqual(['due']);
    });

    it('Given callbacks due at 200 ms and 100 ms, When 200 ms pass, Then they ran in due order', async () => {
      const { timer, elapse } = make();
      const calls: string[] = [];
      timer.after(200, () => calls.push('late'));
      timer.after(100, () => calls.push('early'));
      await elapse(200);
      expect(calls).toEqual(['early', 'late']);
    });

    it('Given a cancelled callback, When its time passes, Then it never runs and cancelling again is harmless', async () => {
      const { timer, elapse } = make();
      const calls: string[] = [];
      const cancel = timer.after(50, () => calls.push('cancelled'));
      timer.after(50, () => calls.push('kept'));
      cancel();
      cancel();
      await elapse(100);
      expect(calls).toEqual(['kept']);
    });
  });
}
