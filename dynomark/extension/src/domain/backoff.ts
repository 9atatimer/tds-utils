// backoff.ts -- how long to wait before the next reconnect attempt (design,
// "Transport contract", retryable errors: transport loss and daemon restart
// are retried by reconnecting). Doubling from a base, capped.

// --- Types ---

export interface BackoffPolicy {
  readonly base_ms: number;
  readonly max_ms: number;
}

// --- Constants ---

/** Reconnect to the daemon: half a second, doubling, at most 30 seconds. */
export const RECONNECT_BACKOFF: BackoffPolicy = { base_ms: 500, max_ms: 30_000 };

// --- Pure helpers ---

/** The delay before attempt `attempt` (0 = the first retry): base * 2^attempt, capped at max. */
export function backoffDelay(attempt: number, policy: BackoffPolicy = RECONNECT_BACKOFF): number {
  const doublings = Math.min(Math.max(0, attempt), 30);
  return Math.min(policy.max_ms, policy.base_ms * 2 ** doublings);
}
