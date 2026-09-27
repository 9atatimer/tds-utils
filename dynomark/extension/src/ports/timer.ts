// timer.ts -- the Timer port: run a callback after a delay. Debounces (tier-2
// search, tree.snapshot after owned-root changes) and reconnect backoff are
// workflow steps that wait; the wait is injected so tests run on fake time.

export interface Timer {
  /** Run `callback` once, `ms` milliseconds from now; returns a cancel that is safe to call more than once. */
  after(ms: number, callback: () => void): () => void;
}
