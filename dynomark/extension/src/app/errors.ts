// errors.ts -- how a use case reports what the daemon refused (contract v1
// README, "Roles and errors"). Every request is answered by its `X.result` or
// by one `error`; the use cases turn the error into a thrown DaemonError so
// a caller can branch on the closed code set.

import type { Id } from '../domain/values.js';
import type { ErrorMessage } from '../wire/messages.js';
import type { ErrorCode } from '../wire/values.js';

// --- Types ---

export type { ErrorCode };

/** The daemon answered a request with `error`. */
export class DaemonError extends Error {
  readonly code: ErrorCode;
  readonly re: Id | null;

  constructor(error: ErrorMessage) {
    super(`daemon error ${error.code}: ${error.message}`);
    this.name = 'DaemonError';
    this.code = error.code;
    this.re = error.re;
  }
}

// --- Constants ---

/** Codes the contract says to retry with the same id (after backoff). */
const RETRYABLE: ReadonlySet<ErrorCode> = new Set<ErrorCode>(['busy', 'internal']);

// --- Predicates ---

/** True when the contract says a request answered with this code is retried with the same id. */
export function isRetryable(code: ErrorCode): boolean {
  return RETRYABLE.has(code);
}

// --- Helpers ---

/** The `X.result` frame, or a thrown DaemonError when the daemon answered `error`. */
export function resultOrThrow<T extends { readonly type: string }>(response: T | ErrorMessage): Exclude<T, ErrorMessage> {
  if (response.type === 'error') throw new DaemonError(response as ErrorMessage);
  return response as Exclude<T, ErrorMessage>;
}
