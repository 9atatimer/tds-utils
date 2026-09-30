/// <reference types="node" />
// FakeTimer.ts -- an in-memory Timer on a FakeClock: callbacks run only when a
// test advances time, in due order, with the clock reading each due time.

import type { Timer } from '../../src/ports/timer.js';
import type { FakeClock } from './FakeClock.js';

interface Due {
  readonly at: number;
  readonly seq: number;
  readonly callback: () => void;
}

export class FakeTimer implements Timer {
  private queue: Due[] = [];
  private seq = 0;

  constructor(private readonly clock: FakeClock) {}

  after(ms: number, callback: () => void): () => void {
    const due: Due = { at: this.clock.now() + Math.max(0, ms), seq: (this.seq += 1), callback };
    this.queue.push(due);
    return () => {
      this.queue = this.queue.filter((d) => d !== due);
    };
  }

  /** Move time forward by `ms`, running each callback as its time comes, letting promises settle between them. */
  async advance(ms: number): Promise<void> {
    const end = this.clock.now() + ms;
    for (let next = this.nextDue(end); next !== undefined; next = this.nextDue(end)) {
      this.queue = this.queue.filter((d) => d !== next);
      this.clock.advance(next.at - this.clock.now());
      next.callback();
      await settle();
    }
    this.clock.advance(end - this.clock.now());
    await settle();
  }

  /** Drop every callback (the worker that scheduled them died). */
  clear(): void {
    this.queue = [];
  }

  /** How many callbacks are waiting. */
  pending(): number {
    return this.queue.length;
  }

  private nextDue(end: number): Due | undefined {
    return this.queue.filter((d) => d.at <= end).sort((a, b) => a.at - b.at || a.seq - b.seq)[0];
  }
}

/** Let every queued promise continuation run: one turn of the event loop (no wall-clock wait). */
function settle(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}
