// backoff.test.ts -- how long the extension waits before reconnecting to the
// daemon (design, "Transport contract", retryable errors: transport loss and
// daemon restart are retryable by reconnecting). Doubling from a base, capped.

import { describe, expect, it } from 'vitest';
import { RECONNECT_BACKOFF, backoffDelay } from '../../../src/domain/backoff.js';

describe('backoffDelay', () => {
  it('Given successive failed attempts, When delays are asked for, Then they double from the base', () => {
    const policy = { base_ms: 100, max_ms: 10_000 };
    expect([0, 1, 2, 3].map((n) => backoffDelay(n, policy))).toEqual([100, 200, 400, 800]);
  });

  it('Given many failed attempts, When a delay is asked for, Then it never exceeds the cap (and never overflows)', () => {
    const policy = { base_ms: 100, max_ms: 5_000 };
    expect(backoffDelay(10, policy)).toBe(5_000);
    expect(backoffDelay(10_000, policy)).toBe(5_000);
  });

  it('Given the reconnect policy, When read, Then it starts under a second and caps at 30 seconds', () => {
    expect(backoffDelay(0)).toBe(RECONNECT_BACKOFF.base_ms);
    expect(RECONNECT_BACKOFF.base_ms).toBeLessThan(1_000);
    expect(backoffDelay(50)).toBe(30_000);
  });
});
