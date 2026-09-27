// reconnect.ts -- reconnecting to the daemon (design, "Transport contract",
// retryable errors: transport loss and daemon restart are retried by
// reconnecting). One attempt at a time, backing off between failures; a
// success resets the backoff; a superseded or contract-violating connection
// is never retried.

import { backoffDelay, RECONNECT_BACKOFF, type BackoffPolicy } from '../domain/backoff.js';
import type { Timer } from '../ports/timer.js';
import { TransportLost } from '../ports/transport.js';
import { ContractViolation } from './connection.js';

// --- Predicates ---

function isFinal(error: unknown): boolean {
  return (error instanceof TransportLost && error.reason === 'superseded') || error instanceof ContractViolation;
}

// --- The reconnector ---

export class Reconnector {
  private attempt = 0;
  private cancel: (() => void) | undefined;
  private stopped = false;

  constructor(
    private readonly connect: () => Promise<unknown>,
    private readonly deps: { readonly timer: Timer; track(work: Promise<unknown>): void },
    private readonly policy: BackoffPolicy = RECONNECT_BACKOFF,
  ) {}

  /** Try now. */
  now(): void {
    if (!this.stopped) this.deps.track(this.tryConnect());
  }

  /** Try after the next backoff delay, unless an attempt is already scheduled. */
  schedule(): void {
    if (this.stopped || this.cancel !== undefined) return;
    const delay = backoffDelay(this.attempt, this.policy);
    this.attempt += 1;
    this.cancel = this.deps.timer.after(delay, () => {
      this.cancel = undefined;
      this.now();
    });
  }

  /** Never try again (superseded). */
  stop(): void {
    this.stopped = true;
    this.cancel?.();
    this.cancel = undefined;
  }

  private async tryConnect(): Promise<void> {
    try {
      await this.connect();
      this.attempt = 0;
    } catch (error) {
      if (isFinal(error)) this.stop();
      else this.schedule();
    }
  }
}
